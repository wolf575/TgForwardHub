"""Batch forwarding service for the merged web UI.

Keeps the A-style task form semantics (source, target, id/time range, keyword
filters, reverse order) but performs forwarding directly with the B project's
Pyrogram clients.
"""
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone

from pyrogram import raw
from pyrogram.errors import (
    ChatForwardsRestricted,
    FileReferenceExpired,
    FloodWait,
    InternalServerError,
    MessageNotModified,
    Timeout as TelegramTimeout,
)
from database import DATA_DIR
from app_settings import get_app_timezone
from bot.handlers.messages import (
    _copy_single_private_media,
    _download_private_media_thumbnail,
    _get_private_media_group_messages,
    _get_private_media_payload,
    _nonempty_file,
    _send_downloaded_private_media_group,
    _send_downloaded_private_media_sequentially,
)
from bot.handlers.instances import get_acc_instance, get_bot_instance
from bot.utils.helpers import get_message_type
from bot.utils.logger import get_logger
from bot.workers.message_worker import MessageWorker
from pyrogram_compat import apply_pyrogram_peer_id_compat, normalize_private_channel_ref


apply_pyrogram_peer_id_compat()

logger = get_logger(__name__)


HISTORY_DB = os.path.join(DATA_DIR, "history.db")
DOWNLOADABLE_MEDIA_TYPES = {
    "Audio",
    "Document",
    "Photo",
    "Video",
    "Animation",
    "Sticker",
    "Voice",
    "VideoNote",
}

TASKS = {}
TASKS_LOCK = threading.Lock()
BATCH_FETCH_CHUNK_SIZE = 100


class BatchTaskStopped(Exception):
    """Raised when a paused/cancelled task must not start another send."""


PROGRESS_PHASES = {
    "queued": "排队中",
    "resolving": "解析来源与目标",
    "collecting": "收集消息",
    "preparing": "准备消息批次",
    "forwarding": "转发消息",
    "paused": "已暂停",
    "done": "已完成",
    "cancelled": "已取消",
    "error": "执行失败",
}
FILTER_FIELDS = (
    "exclude_keywords",
    "exclude_regex",
    "remove_keywords",
    "remove_regex",
)
FILTER_STATE_KEYS = {
    "exclude_keywords": "excludeKeywords",
    "exclude_regex": "excludeRegex",
    "remove_keywords": "removeKeywords",
    "remove_regex": "removeRegex",
}


def _connect():
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _history_conn():
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_history_db():
    with _history_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id TEXT PRIMARY KEY,
                taskName TEXT,
                targetId TEXT,
                sourceId TEXT,
                outputPath TEXT,
                task_spec TEXT,
                createdAt TEXT,
                state TEXT,
                jobId TEXT,
                status TEXT,
                exitCode INTEGER,
                progress TEXT,
                stdoutTail TEXT,
                stderrTail TEXT
            )
            """
        )
        conn.execute(
            """
            UPDATE history
            SET status = 'interrupted', exitCode = COALESCE(exitCode, 130)
            WHERE status IN ('running', 'paused')
            """
        )
        conn.execute(
            """
            DELETE FROM history
            WHERE id IN (
                SELECT id FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY TRIM(taskName) COLLATE NOCASE
                            ORDER BY createdAt DESC, rowid DESC
                        ) AS row_num
                    FROM history
                    WHERE TRIM(COALESCE(taskName, '')) <> ''
                )
                WHERE row_num > 1
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_history_unique_task_name
            ON history (TRIM(taskName) COLLATE NOCASE)
            WHERE TRIM(COALESCE(taskName, '')) <> ''
            """
        )


def _now_iso():
    return datetime.now(get_app_timezone()).isoformat(timespec="seconds")


def _task_name(value):
    return str(value or "").strip()


def _record_to_dict(row):
    item = dict(row)
    for key in ("state", "task_spec", "progress"):
        raw = item.get(key)
        if raw:
            try:
                item[key] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                item[key] = None
    return item


def save_history(record):
    task_name = _task_name(record.get("taskName"))
    record_id = record.get("id")
    with _history_conn() as conn:
        if task_name:
            conn.execute(
                """
                DELETE FROM history
                WHERE TRIM(taskName) COLLATE NOCASE = ?
                  AND id <> ?
                """,
                (task_name, record_id or ""),
            )
        conn.execute(
            """
            INSERT INTO history (
                id, taskName, targetId, sourceId, outputPath, task_spec,
                createdAt, state, jobId, status, exitCode, progress,
                stdoutTail, stderrTail
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                taskName=excluded.taskName,
                targetId=excluded.targetId,
                sourceId=excluded.sourceId,
                outputPath=excluded.outputPath,
                task_spec=excluded.task_spec,
                createdAt=excluded.createdAt,
                state=excluded.state,
                jobId=excluded.jobId,
                status=excluded.status,
                exitCode=excluded.exitCode,
                progress=excluded.progress,
                stdoutTail=excluded.stdoutTail,
                stderrTail=excluded.stderrTail
            """,
            (
                record_id,
                task_name,
                record.get("targetId") or "",
                record.get("sourceId") or "",
                record.get("outputPath") or "",
                json.dumps(record.get("task_spec") or {}, ensure_ascii=False),
                record.get("createdAt") or _now_iso(),
                json.dumps(record.get("state") or {}, ensure_ascii=False),
                record.get("jobId"),
                record.get("status"),
                record.get("exitCode"),
                json.dumps(record.get("progress") or {}, ensure_ascii=False),
                record.get("stdoutTail"),
                record.get("stderrTail"),
            ),
        )


def list_history():
    with _history_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM history ORDER BY createdAt DESC, rowid DESC"
        ).fetchall()
        return [_record_to_dict(row) for row in rows]


def get_history_record(job_id):
    with _history_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM history
            WHERE id = ? OR jobId = ?
            ORDER BY createdAt DESC, rowid DESC
            LIMIT 1
            """,
            (job_id, job_id),
        ).fetchone()
    return _record_to_dict(row) if row else None


def clear_history():
    with _history_conn() as conn:
        conn.execute("DELETE FROM history")


def delete_history_record(record_id):
    record_id = str(record_id or "").strip()
    if not record_id:
        return False
    with _history_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM history WHERE id = ? OR jobId = ?",
            (record_id, record_id),
        )
        return cursor.rowcount > 0


def _tail(value, limit=4000):
    value = value or ""
    return value[-limit:]


def _update_task(job_id, **changes):
    with TASKS_LOCK:
        task = TASKS.get(job_id)
        if task:
            task.update(changes)


def _persist_task_history(job_id):
    task = get_task(job_id)
    if not task:
        return
    spec = task.get("spec") or {}
    save_history(
        {
            "id": job_id,
            "taskName": task.get("taskName") or spec.get("task_name") or "",
            "targetId": task.get("targetId") or str(spec.get("target") or ""),
            "sourceId": task.get("sourceId") or str(spec.get("source") or ""),
            "outputPath": "",
            "task_spec": spec,
            "createdAt": task.get("createdAt") or _now_iso(),
            "state": task.get("state") or {},
            "jobId": job_id,
            "status": task.get("status"),
            "exitCode": task.get("exitCode"),
            "progress": task.get("progress") or {},
            "stdoutTail": task.get("stdoutTail") or "",
            "stderrTail": task.get("stderrTail") or "",
        }
    )


def get_task(job_id):
    with TASKS_LOCK:
        return dict(TASKS.get(job_id) or {})


def _parse_terms(raw):
    if not raw:
        return []
    raw = str(raw)
    terms = [x.strip() for x in re.split(r"[,|\n]+", raw) if x.strip()]
    return terms


def _matches_exclude(text, terms):
    if not terms:
        return False
    if hasattr(terms, "search"):
        return bool(terms.search(text or ""))
    pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
    return bool(pattern.search(text or ""))


def _compile_literal_terms(terms):
    if not terms:
        return None
    return re.compile(
        "|".join(re.escape(term) for term in terms),
        re.IGNORECASE,
    )


def _parse_regex_patterns(raw):
    """Parse one regex per non-empty line without splitting valid `|` patterns."""
    if not raw:
        return []
    return [
        line.strip()
        for line in str(raw).replace("\r\n", "\n").splitlines()
        if line.strip()
    ]


def _compile_regex_patterns(raw, field_name="正则表达式"):
    patterns = _parse_regex_patterns(raw)
    compiled = []
    try:
        for pattern in patterns:
            compiled.append(re.compile(pattern))
    except re.error as exc:
        raise ValueError(f"{field_name} 格式错误: {exc}") from exc
    return compiled


def _matches_exclude_regex(text, patterns):
    return any(pattern.search(text or "") for pattern in patterns)


def _caption_overrides(cleaned_texts, cleaned_text, count):
    """Build one caption value for every media-group item."""
    if cleaned_texts is None:
        return [cleaned_text] + [""] * max(0, count - 1)
    values = list(cleaned_texts)
    if len(values) < count:
        values.extend([""] * (count - len(values)))
    return values[:count]


def _result_message_ids(result):
    """Extract sent message IDs from high-level or raw forward results."""
    ids = []
    if isinstance(result, (list, tuple)):
        ids.extend(
            int(item.id)
            for item in result
            if getattr(item, "id", None) is not None
        )
    elif getattr(result, "id", None) is not None:
        ids.append(int(result.id))

    for update in getattr(result, "updates", []) or []:
        message = getattr(update, "message", None)
        if getattr(message, "id", None) is not None:
            ids.append(int(message.id))

    return sorted(set(ids))


def _edit_media_group_captions(
    worker,
    client,
    destination,
    result,
    captions,
    log=None,
):
    """Set captions one by one after the album itself was sent successfully."""
    message_ids = _result_message_ids(result)
    if not message_ids:
        raise RuntimeError("媒体组发送成功但无法获取目标消息 ID")
    if len(message_ids) < len(captions):
        _emit_log(
            f"媒体组返回 {len(message_ids)} 项，少于源媒体组 {len(captions)} 项，"
            "仅更新已返回条目的 caption",
            log,
            "warning",
        )

    for index, (message_id, caption) in enumerate(
        zip(message_ids, captions),
        start=1,
    ):
        desired = caption or ""
        try:
            _worker_execute(
                worker,
                f"更新媒体组第 {index} 项 caption",
                lambda message_id=message_id, desired=desired: (
                    client.edit_message_caption(
                        destination,
                        message_id,
                        caption=desired,
                    )
                ),
            )
        except MessageNotModified:
            continue
        except Exception as exc:
            _emit_log(
                f"媒体组第 {index} 项 caption 更新失败: "
                f"{type(exc).__name__}: {exc}",
                log,
                "warning",
            )


def _copy_media_group_and_set_captions(
    worker,
    client,
    destination,
    source_id,
    anchor_id,
    captions,
    log=None,
):
    result = _worker_execute(
        worker,
        "复制媒体组（保持原相册顺序）",
        lambda: client.copy_media_group(
            destination,
            source_id,
            anchor_id,
        ),
    )
    _edit_media_group_captions(
        worker,
        client,
        destination,
        result,
        captions,
        log,
    )
    return result


def _forward_media_group_and_set_captions(
    worker,
    client,
    destination,
    source_id,
    group_messages,
    captions,
    preserve_source,
    log=None,
):
    message_ids = [item.id for item in group_messages]
    if preserve_source:
        result = _worker_execute(
            worker,
            "转发媒体组（保持原相册顺序）",
            lambda: client.forward_messages(
                destination,
                source_id,
                message_ids,
            ),
        )
    else:
        result = _worker_execute(
            worker,
            "隐藏来源转发媒体组（保持原相册顺序）",
            lambda: _user_hidden_forward(
                client,
                source_id,
                destination,
                message_ids,
            ),
        )
    _edit_media_group_captions(
        worker,
        client,
        destination,
        result,
        captions,
        log,
    )
    return result


def _strip_trailing_blocks(text, terms):
    if not text or not terms:
        return text
    pattern = re.compile(
        r"\n\n(?:%s).*" % "|".join(re.escape(term) for term in terms),
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub("", text)


def _remove_matches(text, terms, patterns):
    """Delete literal terms and regex matches from forwarded text."""
    if not text:
        return text
    if terms:
        if hasattr(terms, "sub"):
            text = terms.sub("", text)
        else:
            for term in terms:
                text = re.sub(re.escape(term), "", text, flags=re.IGNORECASE)
    for pattern in patterns:
        text = pattern.sub("", text)
    return text


def _parse_timestamp(value, end_of_day=False):
    value = str(value or "").strip()
    if not value:
        return None
    if re.fullmatch(r"\d{10}", value):
        return int(value)
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=get_app_timezone())
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return int(dt.timestamp())
    except ValueError:
        return None


def _resolve_chat(client, ref):
    ref = normalize_private_channel_ref(ref)
    if not ref:
        raise ValueError("缺少聊天 ID")
    if ref.lower() == "me":
        return "me"
    if re.fullmatch(r"-?\d+", ref):
        return int(ref)
    chat = client.get_chat(ref)
    if chat and getattr(chat, "id", None) is not None:
        return chat.id
    raise ValueError(f"无法解析聊天: {ref}")


def _resolve_source_username(client, ref, chat_id):
    """Return a public source username when the client can resolve one."""
    candidates = []
    raw = str(ref or "").strip()

    link_match = re.match(
        r"^https?://(?:www\.)?t\.me/(?P<username>[A-Za-z0-9_]+)",
        raw,
        re.IGNORECASE,
    )
    if link_match and link_match.group("username").lower() not in (
        "c",
        "b",
        "+",
        "joinchat",
    ):
        explicit_username = link_match.group("username")
        candidates.append(explicit_username)
        # Collection-style usernames (for example @buzzav, @javslon) are real
        # public usernames even when get_chat cannot return a username field.
        return explicit_username

    if re.fullmatch(r"@?[A-Za-z0-9_]{5,32}", raw):
        explicit_username = raw.lstrip("@")
        candidates.append(explicit_username)
        return explicit_username

    normalized = normalize_private_channel_ref(ref)
    if not re.fullmatch(r"-?\d+", normalized):
        candidates.append(normalized)
    candidates.append(chat_id)

    for candidate in candidates:
        try:
            chat = client.get_chat(candidate)
        except Exception:
            continue
        username = getattr(chat, "username", None)
        if username:
            return str(username)
    return None


def _member_is_joined(client, chat_id):
    """Return True/False/None for a client's membership in ``chat_id``.

    ``None`` means the client does not expose ``get_chat_member`` and the
    caller should skip membership validation. This keeps the lightweight test
    doubles usable without forcing every test to implement Telegram chat APIs.
    """
    getter = getattr(client, "get_chat_member", None)
    if getter is None:
        return None
    try:
        member = getter(chat_id, "me")
    except Exception:
        return False
    if not member:
        return False
    status = getattr(member, "status", None)
    status_name = getattr(status, "name", None) if status else None
    if status_name in ("LEFT", "BANNED", "KICKED"):
        return False
    return True


def _can_join_chat_ref(ref):
    """Return whether ``ref`` is an explicit joinable link/username reference."""
    normalized = normalize_private_channel_ref(ref)
    if re.fullmatch(r"-?\d+", normalized):
        return False
    stripped = str(ref or "").strip()
    return stripped.startswith("@") or bool(
        re.match(r"^(?:https?://)?(?:www\.)?t\.me/", stripped, re.IGNORECASE)
    )


def _resolve_relay_chat(worker, acc, bot, ref):
    """Resolve and validate a Bot/user shared relay chat reference.

    The user client and Bot both need to be in the relay chat. If the Bot is
    missing and the reference is an invite link or public username, we try to
    let the Bot join automatically. Numeric IDs cannot be joined this way, so
    they fail with an explicit message instead of a later ``CHANNEL_INVALID``.
    """
    chat_id = _resolve_chat(acc, ref)
    if chat_id == "me":
        raise ValueError("中转缓冲会话必须是 Bot 和用户都已加入的频道或群组")

    user_joined = _member_is_joined(acc, chat_id)
    if user_joined is False:
        raise ValueError(f"用户客户端未加入中转会话 {chat_id}，请先加入并授予权限")

    bot_joined = _member_is_joined(bot, chat_id)
    if bot_joined is False and _can_join_chat_ref(ref):
        try:
            _worker_execute(
                worker,
                "Bot 加入中转缓冲会话",
                lambda: bot.join_chat(ref),
            )
            bot_joined = _member_is_joined(bot, chat_id)
        except Exception as exc:
            raise ValueError(
                f"Bot 自动加入中转会话失败: {type(exc).__name__}: {exc}"
            ) from exc

    if bot_joined is False:
        raise ValueError(
            f"Bot 未加入中转会话 {chat_id}；请先把 Bot 添加为该频道或群组成员"
            "并授予发消息权限，或改用 Bot 可以加入的邀请链接/公开用户名"
        )
    return chat_id


def _collect_message_ids(acc, source_id, spec, progress_callback=None):
    range_type = spec.get("range_type", "id")
    start = spec.get("start")
    end = spec.get("end")
    reverse = bool(spec.get("reverse"))

    if range_type == "time":
        start_ts = _parse_timestamp(start)
        end_ts = _parse_timestamp(end, end_of_day=True)
        if start_ts is None or end_ts is None:
            raise ValueError("时间范围格式不正确")
        if start_ts > end_ts:
            start_ts, end_ts = end_ts, start_ts

        ids = []
        scanned = 0
        offset_date = datetime.fromtimestamp(end_ts, tz=timezone.utc)
        for message in acc.get_chat_history(source_id, offset_date=offset_date):
            scanned += 1
            ts = message.date.timestamp()
            if ts < start_ts:
                break
            if ts <= end_ts:
                ids.append(message.id)
            if progress_callback and scanned % 100 == 0:
                progress_callback(scanned, len(ids))
        if not reverse:
            ids.reverse()
        if progress_callback:
            progress_callback(scanned, len(ids))
        return ids

    start_id = int(start)
    end_id = int(end)
    if start_id > end_id:
        start_id, end_id = end_id, start_id
    ids = list(range(start_id, end_id + 1))
    if reverse:
        ids.reverse()
    if progress_callback:
        progress_callback(len(ids), len(ids))
    return ids


def _validate_task_spec(spec):
    if not spec.get("source") or not spec.get("target"):
        raise ValueError("source 和 target 不能为空")

    spec["task_name"] = _task_name(spec.get("task_name"))

    forward_mode = str(spec.get("forward_mode") or "clone").lower()
    if forward_mode not in ("clone", "direct", "cache"):
        raise ValueError("forward_mode 只支持 clone、direct 或 cache")
    spec["forward_mode"] = forward_mode

    relay_chat = str(spec.get("relay_chat") or spec.get("buffer_chat") or "").strip()
    spec["relay_chat"] = relay_chat or None

    _compile_regex_patterns(spec.get("exclude_regex"), "排除正则")
    _compile_regex_patterns(spec.get("remove_regex"), "删除正则")

    range_type = spec.get("range_type", "id")
    if range_type not in ("id", "time"):
        raise ValueError("range_type 只支持 id 或 time")

    if range_type == "time":
        if _parse_timestamp(spec.get("start")) is None:
            raise ValueError("开始时间格式不正确")
        if _parse_timestamp(spec.get("end"), end_of_day=True) is None:
            raise ValueError("结束时间格式不正确")
    else:
        try:
            start = int(spec.get("start"))
            end = int(spec.get("end"))
        except (TypeError, ValueError) as exc:
            raise ValueError("消息 ID 范围必须是整数") from exc
        if start <= 0 or end <= 0:
            raise ValueError("消息 ID 必须是正数")
    return spec


def _filter_rule_set(spec):
    return {
        "exclude_terms": _compile_literal_terms(
            _parse_terms(spec.get("exclude_keywords"))
        ),
        "exclude_patterns": _compile_regex_patterns(
            spec.get("exclude_regex"),
            "排除正则",
        ),
        "remove_terms": _compile_literal_terms(
            _parse_terms(spec.get("remove_keywords"))
        ),
        "remove_patterns": _compile_regex_patterns(
            spec.get("remove_regex"),
            "删除正则",
        ),
    }


def _group_texts(group_messages):
    """Return every caption/text in a media group, preserving item order."""
    return [
        str(getattr(message, "caption", None) or getattr(message, "text", None) or "")
        for message in group_messages
    ]


def _plain_filter_text(value):
    """Build a normalized plain-text view before applying filter rules."""
    # Pyrogram keeps bold/quote/custom-emoji formatting in Str.entities while
    # str(value) exposes the underlying visible text; normalize that view.
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2028", "\n")
        .replace("\u2029", "\n")
        .replace("\xa0", " ")
        .replace("\x00", "")
    )
    return "".join(
        char
        for char in text
        if unicodedata.category(char) != "Cf"
        and char not in ("\ufe0e", "\ufe0f")
    )


def _unique_text_fragments(values):
    result = []
    seen = set()
    for value in values:
        if value is None:
            continue
        text = _plain_filter_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _message_filter_texts(message, include_reply=True):
    """Return visible text fragments, including quote and reply previews."""
    # Pyrogram 2.0.x does not expose Telegram quote_text directly, so the
    # referenced message is also used as a fallback for visible quote content.
    values = [
        getattr(message, attr, None)
        for attr in ("text", "caption", "quote_text", "quote_caption")
    ]

    quote = getattr(message, "quote", None)
    if isinstance(quote, dict):
        values.extend(
            quote.get(attr)
            for attr in ("text", "caption", "quote_text", "quote_caption")
        )
    elif quote is not None:
        values.extend(
            getattr(quote, attr, None)
            for attr in ("text", "caption", "quote_text", "quote_caption")
        )

    web_page = (
        getattr(message, "web_page", None)
        or getattr(message, "web_page_preview", None)
    )
    if web_page is not None:
        values.extend(
            getattr(web_page, attr, None)
            for attr in ("title", "description")
        )

    if include_reply:
        reply = getattr(message, "reply_to_message", None)
        if reply is not None and reply is not message:
            values.extend(_message_filter_texts(reply, include_reply=False))

    return _unique_text_fragments(values)


def _group_filter_texts(group_messages):
    texts = []
    for message in group_messages:
        texts.extend(_message_filter_texts(message))
    return _unique_text_fragments(texts)


def _apply_filter_rules(group_messages, rules):
    """Evaluate exclusion and deletion rules across primary and rich text."""
    primary_texts = _group_texts(group_messages)
    if not any(
        rules.get(field)
        for field in (
            "exclude_terms",
            "exclude_patterns",
            "remove_terms",
            "remove_patterns",
        )
    ):
        return {
            "excluded": False,
            "texts": primary_texts,
            "cleaned_texts": primary_texts,
            "text_changed": False,
            "rich_content_changed": False,
            "quote_text_present": False,
        }

    plain_primary_texts = [_plain_filter_text(text) for text in primary_texts]
    filter_texts = _group_filter_texts(group_messages)
    quote_text_present = any(
        bool(getattr(getattr(message, "quote", None), "text", None))
        for message in group_messages
    )
    exclude_terms = rules["exclude_terms"]
    exclude_patterns = rules["exclude_patterns"]
    remove_terms = rules["remove_terms"]
    remove_patterns = rules["remove_patterns"]

    excluded = any(
        _matches_exclude(text, exclude_terms)
        or _matches_exclude_regex(text, exclude_patterns)
        for text in filter_texts
    )
    if excluded:
        return {
            "excluded": True,
            "texts": primary_texts,
            "cleaned_texts": primary_texts,
            "text_changed": False,
            "rich_content_changed": False,
            "quote_text_present": quote_text_present,
        }

    cleaned_plain_texts = [
        _remove_matches(text, remove_terms, remove_patterns)
        for text in plain_primary_texts
    ]
    cleaned_filter_texts = [
        _remove_matches(text, remove_terms, remove_patterns)
        for text in filter_texts
    ]
    text_changed = any(
        cleaned != original
        for cleaned, original in zip(cleaned_filter_texts, filter_texts)
    )
    primary_changed = any(
        cleaned != original
        for cleaned, original in zip(cleaned_plain_texts, plain_primary_texts)
    )
    if primary_changed:
        cleaned_texts = cleaned_plain_texts
    elif text_changed:
        cleaned_texts = plain_primary_texts
    else:
        cleaned_texts = primary_texts
    return {
        "excluded": False,
        "texts": primary_texts,
        "cleaned_texts": cleaned_texts,
        "text_changed": text_changed,
        "rich_content_changed": text_changed and not primary_changed,
        "quote_text_present": quote_text_present,
    }


def _group_text(group_messages):
    return next((text for text in _group_texts(group_messages) if text), "")


def _worker_execute(worker, name, operation):
    """Run a Pyrogram operation through the worker's FloodWait handling."""
    if worker is None:
        return operation()
    return worker._execute_with_flood_retry(name, operation)


def _user_hidden_forward(acc, source_id, dest_id, message_ids, drop_author=True):
    """Forward using the user client and Telegram's native hidden-author flag.

    Pyrogram's high-level ``forward_messages`` does not expose ``drop_author``.
    Telegram Desktop uses this flag for "forward without original sender", and
    the raw path can preserve Telegram-cached media where ``copy_message`` is
    rejected by a restricted source.
    """
    return acc.invoke(
        raw.functions.messages.ForwardMessages(
            from_peer=acc.resolve_peer(source_id),
            to_peer=acc.resolve_peer(dest_id),
            id=list(message_ids),
            random_id=[acc.rnd_id() for _ in message_ids],
            drop_author=drop_author,
        )
    )


def _relay_message_ids(result, fallback_message_id=None):
    """Extract message IDs from a Pyrogram copy/send result.

    ``copy_media_group`` returns a list of messages while ``copy_message`` and
    ``send_message`` return a single message. The fallback exists only for
    minimal test doubles and is never used for a successful real result.
    """
    if result is None:
        raise RuntimeError("Bot 中转未返回可转发的消息 ID")

    if isinstance(result, (list, tuple)):
        message_ids = [
            int(getattr(item, "id"))
            for item in result
            if getattr(item, "id", None) is not None
        ]
        if not message_ids:
            raise RuntimeError("Bot 中转未返回可转发的消息 ID")
        return message_ids

    message_id = getattr(result, "id", None)
    if message_id is None:
        message_id = fallback_message_id
    if message_id is None:
        raise RuntimeError("Bot 中转未返回可转发的消息 ID")
    return [int(message_id)]


def _bot_source_ref(source_id, group_messages, source_username=None):
    """Return the best Bot-readable source reference for a batch unit.

    Pyrogram's Bot client can resolve a public username directly, while a
    numeric chat ID may require an access hash that the Bot client has not
    cached yet. Use the username from the fetched message when available.
    """
    if source_username:
        return source_username
    chat = getattr(group_messages[0], "chat", None)
    username = getattr(chat, "username", None)
    return username or source_id


def _copy_messages_to_relay(
    bot,
    relay_id,
    source_id,
    group_messages,
    cleaned_text,
    text_changed,
    source_username=None,
    cleaned_texts=None,
    worker=None,
):
    """Copy one batch unit into the relay chat using the Bot identity."""
    source_ref = _bot_source_ref(source_id, group_messages, source_username)

    # Resolve and cache the source peer in the Bot client before copying.
    # Numeric IDs are often unavailable until the Bot has successfully read
    # the chat once, especially for private channels where the Bot is a member.
    anchor = group_messages[0]
    try:
        bot.get_messages(source_ref, anchor.id)
    except Exception:
        pass

    if len(group_messages) > 1:
        if text_changed:
            result = _copy_media_group_and_set_captions(
                worker,
                bot,
                relay_id,
                source_ref,
                anchor.id,
                _caption_overrides(
                    cleaned_texts,
                    cleaned_text,
                    len(group_messages),
                ),
            )
        else:
            result = bot.copy_media_group(
                relay_id,
                source_ref,
                anchor.id,
            )
        return _relay_message_ids(result)

    message = group_messages[0]
    if get_message_type(message) in ("Text", None):
        if text_changed:
            result = bot.send_message(relay_id, cleaned_text)
        else:
            result = bot.copy_message(relay_id, source_ref, message.id)
        return _relay_message_ids(result)

    kwargs = {"caption": cleaned_text} if text_changed else {}
    result = bot.copy_message(relay_id, source_ref, message.id, **kwargs)
    return _relay_message_ids(result)


def _forward_cache_via_bot_relay(
    worker,
    bot,
    acc,
    source_id,
    dest_id,
    relay_id,
    group_messages,
    cleaned_text,
    text_changed,
    log=None,
    source_username=None,
    cleaned_texts=None,
):
    """Relay a restricted cached-copy through Bot, then hidden-forward as user."""
    try:
        resolved_username = source_username
        if not resolved_username:
            resolved_username = _resolve_source_username(
                acc,
                source_id,
                source_id,
            )
        if not resolved_username:
            resolved_username = _resolve_source_username(
                bot,
                source_id,
                source_id,
            )
        if not resolved_username and group_messages:
            chat = getattr(group_messages[0], "chat", None)
            resolved_username = getattr(chat, "username", None)

        source_ref = _bot_source_ref(
            source_id,
            group_messages,
            resolved_username,
        )
        if str(source_ref).lstrip("-").isdigit():
            _emit_log(
                "来源未解析到公开 username；Bot 将尝试用数字 ID 读取来源会话。"
                "若这是私有频道且 Bot 不是成员，中转会回退到下载重传",
                log,
                "warning",
            )
        _emit_log(
            f"Bot 中转受限消息: {source_ref} -> 缓冲会话 {relay_id}，"
            "RPC=copy_message/copy_media_group",
            log,
        )
        relay_ids = _worker_execute(
            worker,
            "Bot 复制受限消息到中转缓冲会话",
            lambda: _copy_messages_to_relay(
                bot,
                relay_id,
                source_id,
                group_messages,
                cleaned_text,
                text_changed,
                source_username=resolved_username,
                cleaned_texts=cleaned_texts,
                worker=worker,
            ),
        )
        _emit_log(
            f"Bot 已复制到缓冲会话 {relay_id}，准备由用户客户端隐藏转发: "
            f"{relay_ids} -> {dest_id}",
            log,
        )
        _worker_execute(
            worker,
            "用户客户端从中转缓冲会话隐藏转发",
            lambda: _user_hidden_forward(
                acc,
                relay_id,
                dest_id,
                relay_ids,
                drop_author=True,
            ),
        )
        _emit_log(
            f"受限消息已通过 Bot 中转完成: {source_id} -> {relay_id} -> {dest_id}",
            log,
        )
        return True
    except Exception as exc:
        _emit_log(
            f"Bot 中转失败，将回退到用户客户端下载重传: "
            f"{type(exc).__name__}: {exc}",
            log,
            "warning",
        )
        return False


def _emit_log(message, log, level="info"):
    """Write a batch step to the container log and the in-memory task log."""
    if log is not None:
        try:
            log(message, level=level)
        except Exception:
            pass
    else:
        getattr(logger, level, logger.info)("[batch] %s", message)


def _is_transient_download_error(exc):
    return isinstance(
        exc,
        (
            FloodWait,
            InternalServerError,
            TelegramTimeout,
            TimeoutError,
            ConnectionError,
            OSError,
        ),
    )


def _download_batch_media_with_retry(
    acc,
    item,
    file_name,
    log,
    attempts=3,
):
    """Download one media item, retrying Telegram's transient failures."""
    item_id = getattr(item, "id", "unknown")
    last_error = None
    for attempt in range(1, attempts + 1):
        _emit_log(
            f"开始下载媒体用于重传 {item_id}，第 {attempt}/{attempts} 次",
            log,
        )
        try:
            file_path = acc.download_media(item, file_name=file_name)
            if file_path is None:
                last_error = RuntimeError(
                    f"媒体 {item_id} 下载失败：Telegram 未返回文件数据"
                )
                _emit_log(
                    f"媒体 {item_id} 第 {attempt}/{attempts} 次下载返回空结果，"
                    "将稍后重试",
                    log,
                    "warning",
                )
                if attempt < attempts:
                    time.sleep(1.5 * attempt)
                    continue
                break
            if os.path.isfile(file_path) and not _nonempty_file(file_path):
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                    except OSError as exc:
                        _emit_log(
                            f"媒体 {item_id} 空文件删除失败: {exc}",
                            log,
                            "warning",
                        )
                last_error = RuntimeError(
                    f"媒体 {item_id} 下载失败：Telegram 返回了 0 字节文件"
                )
                _emit_log(
                    f"媒体 {item_id} 第 {attempt}/{attempts} 次下载得到 "
                    "0 字节文件，将稍后重试",
                    log,
                    "warning",
                )
                if attempt < attempts:
                    time.sleep(1.5 * attempt)
                    continue
                break
            _emit_log(
                f"媒体 {item_id} 下载完成，用于重传: {file_path}",
                log,
            )
            return file_path
        except FloodWait as exc:
            last_error = exc
            wait = int(getattr(exc, "value", 0) or 0) + 1
            _emit_log(
                f"媒体 {item_id} 重传下载遇到 FloodWait，等待 {wait} 秒",
                log,
                "warning",
            )
            if attempt < attempts:
                time.sleep(wait)
                continue
        except Exception as exc:
            last_error = exc
            if not _is_transient_download_error(exc):
                raise
            _emit_log(
                f"媒体 {item_id} 重传下载失败: {type(exc).__name__}: {exc}",
                log,
                "warning",
            )
            if attempt < attempts:
                time.sleep(1.5 * attempt)
                continue

    raise last_error


def _download_batch_media_group_items(
    acc,
    source_id,
    group_messages,
    log,
    attempts=3,
    max_workers=4,
):
    """Download album items in bounded parallel, then restore album order."""
    work_dir = tempfile.mkdtemp(prefix="tg_forward_album_")
    indexed_downloads = [None] * len(group_messages)
    log_lock = threading.Lock()

    def thread_log(message, level="info"):
        with log_lock:
            _emit_log(message, log, level)

    def download_item(index, item):
        try:
            file_path = _download_batch_media_with_retry(
                acc,
                item,
                os.path.join(work_dir, ""),
                thread_log,
                attempts=attempts,
            )
        except ValueError as exc:
            if "doesn't contain any downloadable media" in str(exc):
                thread_log(
                    f"媒体组消息 {item.id} 没有可下载媒体，已跳过",
                    "warning",
                )
                return None
            raise

        payload = _get_private_media_payload(item)
        thumb = None
        if get_message_type(item) in (
            "Document",
            "Video",
            "Audio",
            "Animation",
            "VideoNote",
        ):
            thumb = _download_private_media_thumbnail(
                acc,
                payload,
                work_dir,
                index,
            )
        return (item, file_path, thumb)

    try:
        if max_workers > 1 and len(group_messages) > 1:
            _emit_log(
                f"并行下载媒体组 {len(group_messages)} 项，"
                f"最多 {max_workers} 个并发",
                log,
            )
            with ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="tg_forward_download",
            ) as executor:
                futures = {
                    executor.submit(download_item, index, item): index
                    for index, item in enumerate(group_messages)
                }
                for future in as_completed(futures):
                    index = futures[future]
                    result = future.result()
                    if result is not None:
                        indexed_downloads[index] = result
        else:
            for index, item in enumerate(group_messages):
                indexed_downloads[index] = download_item(index, item)

        downloads = [download for download in indexed_downloads if download]
        downloadable_messages = [download[0] for download in downloads]

        if not downloads:
            raise RuntimeError(
                f"媒体组消息 {group_messages[0].id} 没有可下载的媒体"
            )
        return downloadable_messages, downloads, work_dir
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def _download_batch_media_group_with_retry(
    acc,
    source_id,
    group_messages,
    log,
    attempts=3,
    max_workers=4,
):
    """Download a fallback media group with transient-error retries."""
    item_ids = [item.id for item in group_messages]
    last_error = None
    for attempt in range(1, attempts + 1):
        _emit_log(
            f"开始下载媒体组用于重传 {item_ids}，第 {attempt}/{attempts} 次",
            log,
        )
        try:
            result = _download_batch_media_group_items(
                acc,
                source_id,
                group_messages,
                log,
                attempts=attempts,
                max_workers=max_workers,
            )
            downloaded_messages, downloads, work_dir = result
            _emit_log(
                "媒体组重传下载完成，共 "
                f"{len(downloads)}/{len(group_messages)} 项: {item_ids}",
                log,
            )
            return result
        except FloodWait as exc:
            last_error = exc
            wait = int(getattr(exc, "value", 0) or 0) + 1
            _emit_log(
                f"媒体组 {item_ids} 重传下载遇到 FloodWait，等待 {wait} 秒",
                log,
                "warning",
            )
            if attempt < attempts:
                time.sleep(wait)
                continue
        except Exception as exc:
            last_error = exc
            if not _is_transient_download_error(exc):
                raise
            _emit_log(
                "媒体组重传下载失败 "
                f"{item_ids}: {type(exc).__name__}: {exc}",
                log,
                "warning",
            )
            if attempt < attempts:
                time.sleep(1.5 * attempt)
                continue

    raise last_error


def _reupload_batch_media_group(
    worker,
    acc,
    source_id,
    dest_id,
    group_messages,
    cleaned_text,
    text_changed,
    log=None,
    cleaned_texts=None,
    wait_for_active=None,
):
    if wait_for_active is not None and not wait_for_active():
        raise BatchTaskStopped()
    group_messages, downloads, work_dir = _download_batch_media_group_with_retry(
        acc,
        source_id,
        group_messages,
        log,
    )
    try:
        if wait_for_active is not None and not wait_for_active():
            raise BatchTaskStopped()
        _emit_log(
            f"开始上传媒体组重传 {[item.id for item in group_messages]}",
            log,
        )
        _worker_execute(
            worker,
            "上传媒体组重传",
            lambda: _send_downloaded_private_media_group(
                acc,
                dest_id,
                group_messages,
                downloads,
                caption_override=cleaned_text if text_changed else None,
                caption_entities_override=None if text_changed else None,
                caption_overrides=cleaned_texts if text_changed else None,
            ),
        )
        _emit_log(
            f"媒体组 {[item.id for item in group_messages]} 重传上传完成",
            log,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        _emit_log(
            f"已清理媒体组重传临时目录: {work_dir}",
            log,
        )
    return len(group_messages)


def _forward_batch_media_group(
    worker,
    acc,
    source_id,
    dest_id,
    group_messages,
    cleaned_text,
    text_changed,
    preserve_source,
    log=None,
    restricted_source_ids=None,
    cache_send=False,
    bot=None,
    relay_chat_id=None,
    source_username=None,
    cleaned_texts=None,
    wait_for_active=None,
):
    anchor = group_messages[0]

    if cache_send:
        try:
            _emit_log(
                f"媒体组 {anchor.id} 使用用户客户端缓存复制: "
                f"{source_id} -> {dest_id}，RPC=copy_media_group",
                log,
            )
            if text_changed and cleaned_texts is not None:
                _copy_media_group_and_set_captions(
                    worker,
                    acc,
                    dest_id,
                    source_id,
                    anchor.id,
                    _caption_overrides(
                        cleaned_texts,
                        cleaned_text,
                        len(group_messages),
                    ),
                    log,
                )
            elif text_changed:
                _copy_media_group_and_set_captions(
                    worker,
                    acc,
                    dest_id,
                    source_id,
                    anchor.id,
                    _caption_overrides(
                        None,
                        cleaned_text,
                        len(group_messages),
                    ),
                    log,
                )
            else:
                _worker_execute(
                    worker,
                    "复制媒体组（缓存发送）",
                    lambda: acc.copy_media_group(
                        dest_id,
                        source_id,
                        anchor.id,
                    ),
                )
            _emit_log(
                f"媒体组 {anchor.id} 已通过缓存复制原样发送: "
                f"{source_id} -> {dest_id}",
                log,
            )
            return len(group_messages), False
        except Exception as exc:
            restricted = isinstance(exc, ChatForwardsRestricted)
            _emit_log(
                f"媒体组 {anchor.id} 缓存复制"
                f"{'受限（准备 Bot 中转）' if restricted else '失败'}: "
                f"{type(exc).__name__}: {exc}",
                log,
                "info" if restricted else "warning",
            )
            if restricted and restricted_source_ids is not None:
                restricted_source_ids.add(source_id)
                _emit_log(
                    f"来源 {source_id} 已确认限制缓存复制",
                    log,
                    "warning",
                )
            if bot is not None and relay_chat_id is not None:
                if _forward_cache_via_bot_relay(
                    worker,
                    bot,
                    acc,
                    source_id,
                    dest_id,
                    relay_chat_id,
                    group_messages,
                    cleaned_text,
                    text_changed,
                    log,
                    source_username=source_username,
                    cleaned_texts=cleaned_texts,
                ):
                    return len(group_messages), False
            reuploaded = _reupload_batch_media_group(
                worker,
                acc,
                source_id,
                dest_id,
                group_messages,
                cleaned_text,
                text_changed,
                log,
                cleaned_texts=cleaned_texts,
                wait_for_active=wait_for_active,
            )
            return len(group_messages), True

    if not preserve_source and not text_changed:
        try:
            _emit_log(
                "开始用户客户端原生缓存隐藏转发媒体组: "
                f"{source_id} -> {dest_id}，"
                "RPC=messages.ForwardMessages(drop_author=True)",
                log,
            )
            _worker_execute(
                worker,
                "用户客户端缓存隐藏转发媒体组",
                lambda: _user_hidden_forward(
                    acc,
                    source_id,
                    dest_id,
                    [item.id for item in group_messages],
                ),
            )
            _emit_log(
                f"媒体组 {anchor.id} 已通过用户客户端原生缓存隐藏转发: "
                f"{source_id} -> {dest_id}，无需下载重传",
                log,
            )
            return len(group_messages), False
        except Exception as exc:
            _emit_log(
                f"用户客户端原生隐藏转发媒体组 {anchor.id} 失败: "
                f"{source_id} -> {dest_id}，{type(exc).__name__}: {exc}",
                log,
                "warning",
            )
            if isinstance(exc, ChatForwardsRestricted) and restricted_source_ids is not None:
                restricted_source_ids.add(source_id)
                _emit_log(
                    f"来源 {source_id} 已确认限制缓存转发，后续消息将直接下载重传",
                    log,
                    "warning",
                )
            reuploaded = _reupload_batch_media_group(
                worker,
                acc,
                source_id,
                dest_id,
                group_messages,
                cleaned_text,
                text_changed,
                log,
                wait_for_active=wait_for_active,
            )
            return len(group_messages), True

    try:
        if text_changed:
            if cleaned_texts is not None:
                _forward_media_group_and_set_captions(
                    worker,
                    acc,
                    dest_id,
                    source_id,
                    group_messages,
                    _caption_overrides(
                        cleaned_texts,
                        cleaned_text,
                        len(group_messages),
                    ),
                    preserve_source,
                    log,
                )
            else:
                _copy_media_group_and_set_captions(
                    worker,
                    acc,
                    dest_id,
                    source_id,
                    anchor.id,
                    _caption_overrides(
                        None,
                        cleaned_text,
                        len(group_messages),
                    ),
                    log,
                )
        else:
            _worker_execute(
                worker,
                "转发媒体组",
                lambda: acc.forward_messages(
                    dest_id,
                    source_id,
                    [item.id for item in group_messages],
                ),
            )
        return len(group_messages), False
    except Exception as exc:
        _emit_log(
            f"媒体组直接发送失败，准备下载重传: {type(exc).__name__}: {exc}",
            log,
            "warning",
        )
        if isinstance(exc, ChatForwardsRestricted) and restricted_source_ids is not None:
            restricted_source_ids.add(source_id)
            _emit_log(
                f"来源 {source_id} 已确认限制缓存转发，后续消息将直接下载重传",
                log,
                "warning",
            )
        reuploaded = _reupload_batch_media_group(
            worker,
            acc,
            source_id,
            dest_id,
            group_messages,
            cleaned_text,
            text_changed,
            log,
            cleaned_texts=cleaned_texts,
            wait_for_active=wait_for_active,
        )
        return len(group_messages), True


def _reupload_batch_single_media(
    worker,
    acc,
    dest_id,
    message,
    cleaned_text,
    text_changed,
    log=None,
    wait_for_active=None,
):
    if wait_for_active is not None and not wait_for_active():
        raise BatchTaskStopped()
    work_dir = tempfile.mkdtemp(prefix="tg_forward_batch_media_")
    try:
        file_path = _download_batch_media_with_retry(
            acc,
            message,
            os.path.join(work_dir, ""),
            log,
        )
        _emit_log(f"开始下载媒体 {message.id} 的重传缩略图", log)
        thumb = _download_private_media_thumbnail(
            acc,
            _get_private_media_payload(message),
            work_dir,
            0,
        )
        if thumb:
            _emit_log(f"媒体 {message.id} 重传缩略图下载完成: {thumb}", log)
        else:
            _emit_log(f"媒体 {message.id} 无重传缩略图或下载失败", log)
        if wait_for_active is not None and not wait_for_active():
            raise BatchTaskStopped()
        _emit_log(f"开始上传受限单条媒体 {message.id}: {file_path}", log)
        _worker_execute(
            worker,
            "上传受限单条媒体",
            lambda: _send_downloaded_private_media_sequentially(
                acc,
                dest_id,
                message,
                file_path,
                thumb=thumb,
                caption_override=cleaned_text if text_changed else None,
                caption_entities_override=None if text_changed else None,
            ),
        )
        _emit_log(f"受限单条媒体 {message.id} 上传完成", log)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        _emit_log(f"已清理受限单条媒体临时目录: {work_dir}", log)
    return 1


def _forward_batch_single_media(
    worker,
    acc,
    source_id,
    dest_id,
    message,
    cleaned_text,
    text_changed,
    preserve_source,
    log=None,
    restricted_source_ids=None,
    cache_send=False,
    bot=None,
    relay_chat_id=None,
    source_username=None,
    wait_for_active=None,
):
    if cache_send:
        try:
            _emit_log(
                f"单条媒体 {message.id} 使用用户客户端缓存复制: "
                f"{source_id} -> {dest_id}，RPC=copy_message",
                log,
            )
            _worker_execute(
                worker,
                "复制单条媒体（缓存发送）",
                lambda: _copy_single_private_media(
                    acc,
                    dest_id,
                    source_id,
                    message,
                    caption=cleaned_text if text_changed else None,
                ),
            )
            _emit_log(
                f"单条媒体 {message.id} 已通过缓存复制原样发送: "
                f"{source_id} -> {dest_id}",
                log,
            )
            return 1, False
        except Exception as exc:
            restricted = isinstance(exc, ChatForwardsRestricted)
            _emit_log(
                f"单条媒体 {message.id} 缓存复制"
                f"{'受限（准备 Bot 中转）' if restricted else '失败'}: "
                f"{type(exc).__name__}: {exc}",
                log,
                "info" if restricted else "warning",
            )
            if restricted and restricted_source_ids is not None:
                restricted_source_ids.add(source_id)
                _emit_log(
                    f"来源 {source_id} 已确认限制缓存复制",
                    log,
                    "warning",
                )
            if bot is not None and relay_chat_id is not None:
                if _forward_cache_via_bot_relay(
                    worker,
                    bot,
                    acc,
                    source_id,
                    dest_id,
                    relay_chat_id,
                    [message],
                    cleaned_text,
                    text_changed,
                    log,
                    source_username=source_username,
                ):
                    return 1, False
            if get_message_type(message) not in DOWNLOADABLE_MEDIA_TYPES:
                raise
            count = _reupload_batch_single_media(
                worker,
                acc,
                dest_id,
                message,
                cleaned_text,
                text_changed,
                log,
                wait_for_active=wait_for_active,
            )
            return count, True

    if not preserve_source and not text_changed:
        try:
            _emit_log(
                "开始用户客户端原生缓存隐藏转发单条媒体: "
                f"{source_id} -> {dest_id}，"
                "RPC=messages.ForwardMessages(drop_author=True)",
                log,
            )
            _worker_execute(
                worker,
                "用户客户端缓存隐藏转发单条媒体",
                lambda: _user_hidden_forward(
                    acc,
                    source_id,
                    dest_id,
                    [message.id],
                ),
            )
            _emit_log(
                f"单条媒体 {message.id} 已通过用户客户端原生缓存隐藏转发: "
                f"{source_id} -> {dest_id}，无需下载重传",
                log,
            )
            return 1, False
        except Exception as exc:
            _emit_log(
                f"用户客户端原生隐藏转发单条媒体 {message.id} 失败: "
                f"{source_id} -> {dest_id}，{type(exc).__name__}: {exc}",
                log,
                "warning",
            )
            if isinstance(exc, ChatForwardsRestricted) and restricted_source_ids is not None:
                restricted_source_ids.add(source_id)
                _emit_log(
                    f"来源 {source_id} 已确认限制缓存转发，后续消息将直接下载重传",
                    log,
                    "warning",
                )
            if get_message_type(message) not in DOWNLOADABLE_MEDIA_TYPES:
                raise
            count = _reupload_batch_single_media(
                worker,
                acc,
                dest_id,
                message,
                cleaned_text,
                text_changed,
                log,
                wait_for_active=wait_for_active,
            )
            return count, True

    try:
        if text_changed:
            _worker_execute(
                worker,
                "复制单条媒体并修改 caption",
                lambda: acc.copy_message(
                    dest_id,
                    source_id,
                    message.id,
                    caption=cleaned_text,
                ),
            )
        else:
            _worker_execute(
                worker,
                "转发单条媒体",
                lambda: acc.forward_messages(dest_id, source_id, message.id),
            )
        return 1, False
    except Exception as exc:
        _emit_log(
            f"单条媒体直接发送失败: {type(exc).__name__}: {exc}",
            log,
            "warning",
        )
        if isinstance(exc, ChatForwardsRestricted) and restricted_source_ids is not None:
            restricted_source_ids.add(source_id)
            _emit_log(
                f"来源 {source_id} 的单条缓存复制受限，后续消息将直接下载重传",
                log,
                "warning",
            )
        if get_message_type(message) not in DOWNLOADABLE_MEDIA_TYPES:
            raise
        count = _reupload_batch_single_media(
            worker,
            acc,
            dest_id,
            message,
            cleaned_text,
            text_changed,
            log,
            wait_for_active=wait_for_active,
        )
        return count, True


def _forward_batch_text(
    worker,
    acc,
    source_id,
    dest_id,
    message,
    cleaned_text,
    text_changed,
    preserve_source,
    log=None,
    restricted_source_ids=None,
    cache_send=False,
    bot=None,
    relay_chat_id=None,
    source_username=None,
):
    if cache_send:
        try:
            if text_changed:
                _worker_execute(
                    worker,
                    "发送修改后的文本",
                    lambda: acc.send_message(dest_id, cleaned_text),
                )
            else:
                _worker_execute(
                    worker,
                    "复制文本消息（缓存发送）",
                    lambda: acc.copy_message(dest_id, source_id, message.id),
                )
            return 1, False
        except Exception as exc:
            restricted = isinstance(exc, ChatForwardsRestricted)
            _emit_log(
                f"文本消息 {message.id} 缓存复制"
                f"{'受限（准备 Bot 中转）' if restricted else '失败'}: "
                f"{type(exc).__name__}: {exc}",
                log,
                "info" if restricted else "warning",
            )
            if restricted and restricted_source_ids is not None:
                restricted_source_ids.add(source_id)
            if bot is not None and relay_chat_id is not None:
                if _forward_cache_via_bot_relay(
                    worker,
                    bot,
                    acc,
                    source_id,
                    dest_id,
                    relay_chat_id,
                    [message],
                    cleaned_text,
                    text_changed,
                    log,
                    source_username=source_username,
                ):
                    return 1, False
            _worker_execute(
                worker,
                "发送受限文本消息",
                lambda: acc.send_message(
                    dest_id,
                    cleaned_text if text_changed else message.text or "",
                    entities=None if text_changed else message.entities,
                ),
            )
            return 1, True

    if not preserve_source and not text_changed:
        try:
            _emit_log(
                "开始用户客户端原生缓存隐藏转发文本消息: "
                f"{source_id} -> {dest_id}，"
                "RPC=messages.ForwardMessages(drop_author=True)",
                log,
            )
            _worker_execute(
                worker,
                "用户客户端缓存隐藏转发文本消息",
                lambda: _user_hidden_forward(
                    acc,
                    source_id,
                    dest_id,
                    [message.id],
                ),
            )
            _emit_log(
                f"文本消息 {message.id} 已通过用户客户端原生缓存隐藏转发: "
                f"{source_id} -> {dest_id}",
                log,
            )
            return 1, False
        except Exception as exc:
            _emit_log(
                f"用户客户端原生隐藏转发文本消息 {message.id} 失败: "
                f"{source_id} -> {dest_id}，{type(exc).__name__}: {exc}",
                log,
                "warning",
            )
            if isinstance(exc, ChatForwardsRestricted) and restricted_source_ids is not None:
                restricted_source_ids.add(source_id)
            _worker_execute(
                worker,
                "发送受限文本消息",
                lambda: acc.send_message(
                    dest_id,
                    cleaned_text if text_changed else message.text or "",
                    entities=None if text_changed else message.entities,
                ),
            )
            return 1, True

    try:
        if text_changed:
            _worker_execute(
                worker,
                "发送修改后的文本",
                lambda: acc.send_message(dest_id, cleaned_text),
            )
        else:
            _worker_execute(
                worker,
                "转发文本消息",
                lambda: acc.forward_messages(dest_id, source_id, message.id),
            )
        return 1, False
    except Exception as exc:
        if isinstance(exc, ChatForwardsRestricted) and restricted_source_ids is not None:
            restricted_source_ids.add(source_id)
            _emit_log(
                f"来源 {source_id} 的文本缓存复制受限，后续文本将直接重新发送",
                log,
                "warning",
            )
        _worker_execute(
            worker,
            "发送受限文本消息",
            lambda: acc.send_message(
                dest_id,
                cleaned_text if text_changed else message.text or "",
                entities=None if text_changed else message.entities,
            ),
        )
        return 1, True


def _forward_batch_unit(
    worker,
    acc,
    source_id,
    dest_id,
    group_messages,
    cleaned_text,
    text_changed,
    preserve_source,
    log=None,
    restricted_source_ids=None,
    cache_send=False,
    bot=None,
    relay_chat_id=None,
    source_username=None,
    cleaned_texts=None,
    wait_for_active=None,
):
    if wait_for_active is not None and not wait_for_active():
        raise BatchTaskStopped()
    if restricted_source_ids is not None and source_id in restricted_source_ids:
        if cache_send and bot is not None and relay_chat_id is not None:
            _emit_log(
                f"来源 {source_id} 已确认限制缓存复制，"
                "直接尝试 Bot 中转缓冲会话",
                log,
            )
            if _forward_cache_via_bot_relay(
                worker,
                bot,
                acc,
                source_id,
                dest_id,
                relay_chat_id,
                group_messages,
                cleaned_text,
                text_changed,
                log,
                source_username=source_username,
                cleaned_texts=cleaned_texts,
            ):
                return len(group_messages), False
        _emit_log(
            f"来源 {source_id} 已确认限制缓存转发，"
            "直接使用用户客户端下载重传，跳过重复 RPC 探测",
            log,
        )
        return _reupload_batch_unit(
            worker,
            acc,
            dest_id,
            group_messages,
            cleaned_text,
            text_changed,
            log,
            cleaned_texts=cleaned_texts,
            wait_for_active=wait_for_active,
        )

    if len(group_messages) > 1:
        return _forward_batch_media_group(
            worker,
            acc,
            source_id,
            dest_id,
            group_messages,
            cleaned_text,
            text_changed,
            preserve_source,
            log,
            restricted_source_ids,
            cache_send=cache_send,
            bot=bot,
            relay_chat_id=relay_chat_id,
            source_username=source_username,
            cleaned_texts=cleaned_texts,
            wait_for_active=wait_for_active,
        )

    message = group_messages[0]
    msg_type = get_message_type(message)
    if msg_type == "Text" or msg_type is None:
        return _forward_batch_text(
            worker,
            acc,
            source_id,
            dest_id,
            message,
            cleaned_text,
            text_changed,
            preserve_source,
            log,
            restricted_source_ids,
            cache_send=cache_send,
            bot=bot,
            relay_chat_id=relay_chat_id,
            source_username=source_username,
        )
    return _forward_batch_single_media(
        worker,
        acc,
        source_id,
        dest_id,
        message,
        cleaned_text,
        text_changed,
        preserve_source,
        log,
        restricted_source_ids,
        cache_send=cache_send,
        bot=bot,
        relay_chat_id=relay_chat_id,
        source_username=source_username,
        wait_for_active=wait_for_active,
    )


def _reupload_batch_unit(
    worker,
    acc,
    dest_id,
    group_messages,
    cleaned_text,
    text_changed,
    log=None,
    cleaned_texts=None,
    wait_for_active=None,
):
    """Handle a cached-forward-restricted source without trying forbidden RPCs."""
    if len(group_messages) > 1:
        return (
            _reupload_batch_media_group(
                worker,
                acc,
                None,
                dest_id,
                group_messages,
                cleaned_text,
                text_changed,
                log,
                cleaned_texts=cleaned_texts,
                wait_for_active=wait_for_active,
            ),
            True,
        )

    message = group_messages[0]
    msg_type = get_message_type(message)
    if msg_type in ("Text", None):
        text = cleaned_text if text_changed else message.text or ""
        if not text.strip():
            return 0, True
        _emit_log(
            f"受限来源文本消息 {message.id} 直接使用用户客户端重新发送",
            log,
        )
        _worker_execute(
            worker,
            "发送受限文本消息",
            lambda: acc.send_message(
                dest_id,
                text,
                entities=None if text_changed else message.entities,
            ),
        )
        return 1, True

    return (
        _reupload_batch_single_media(
            worker,
            acc,
            dest_id,
            message,
            cleaned_text,
            text_changed,
            log,
            wait_for_active=wait_for_active,
        ),
        True,
    )


def _wait_until_task_active(job_id, log=None):
    task = get_task(job_id)
    if task.get("cancelled"):
        return False
    if not task.get("paused"):
        return True

    if log is not None:
        log("任务已暂停，等待继续")
    event = task.get("resume_event")
    if event is not None:
        event.wait()
    else:
        while get_task(job_id).get("paused"):
            time.sleep(0.2)

    task = get_task(job_id)
    if task.get("cancelled"):
        return False
    if log is not None:
        log("任务已继续")
    return True


def _run_batch_task(job_id, spec):
    log_lines = []
    last_persist = time.monotonic()
    started_monotonic = time.monotonic()
    started_at = _now_iso()

    def persist(force=False):
        nonlocal last_persist
        now = time.monotonic()
        if force or now - last_persist >= 1.0:
            _persist_task_history(job_id)
            last_persist = now

    def log(message, level="info"):
        line = f"[{_now_iso()}] {message}"
        log_lines.append(line)
        getattr(logger, level, logger.info)(
            "[batch:%s] %s",
            job_id,
            message,
        )
        _update_task(job_id, stdoutTail=_tail("\n".join(log_lines)))
        persist()

    def finish_cancelled():
        log("任务已取消")
        current = get_task(job_id).get("progress") or {}
        _update_task(
            job_id,
            status="cancelled",
            exitCode=130,
            stderrTail=_tail("\n".join(log_lines)),
        )
        publish_progress(
            "cancelled",
            total=current.get("total", 0),
            processed=current.get("processed", 0),
            success=current.get("success", 0),
            failed=current.get("failed", 0),
            skipped=current.get("skipped", 0),
            fetched=current.get("fetched", 0),
            scanned=current.get("scanned", 0),
            collected=current.get("collected", 0),
            current_id=current.get("current_id"),
        )
        persist(force=True)

    def publish_progress(phase, **values):
        elapsed = max(0.0, time.monotonic() - started_monotonic)
        total = int(values.get("total") or 0)
        processed = int(values.get("processed") or 0)
        fetched = int(values.get("fetched") or 0)
        eta_seconds = None
        if phase == "forwarding" and total > 0 and processed > 0 and elapsed > 0:
            eta_seconds = max(
                0,
                round((total - processed) * elapsed / processed),
            )
        percent = (
            min(100.0, round(processed * 100.0 / total, 1))
            if total > 0
            else None
        )
        progress = {
            "phase": phase,
            "phase_label": PROGRESS_PHASES.get(phase, phase),
            "started_at": started_at,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": eta_seconds,
            "percent": percent,
            "total": total,
            "fetched": fetched,
            "processed": processed,
            "success": int(values.get("success") or 0),
            "failed": int(values.get("failed") or 0),
            "skipped": int(values.get("skipped") or 0),
            "scanned": int(values.get("scanned") or 0),
            "collected": int(values.get("collected") or 0),
            "current_id": values.get("current_id"),
        }
        _update_task(job_id, progress=progress)
        persist()
        return progress

    try:
        acc = get_acc_instance()
        if acc is None:
            raise RuntimeError("用户客户端尚未初始化，请先完成 /setup 配置")

        publish_progress("resolving")
        log("正在解析来源与目标")
        worker = MessageWorker(None, acc, max_retries=3)
        source_ref = spec.get("source")
        source_id = _resolve_chat(acc, source_ref)
        source_username = _resolve_source_username(acc, source_ref, source_id)
        dest_id = _resolve_chat(acc, spec.get("target"))
        cache_send = str(spec.get("forward_mode", "clone")).lower() == "cache"
        bot = get_bot_instance()
        relay_chat_id = None
        relay_ref = spec.get("relay_chat")
        if relay_ref and cache_send:
            try:
                relay_chat_id = _resolve_relay_chat(worker, acc, bot, relay_ref)
            except Exception as exc:
                log(
                    "中转缓冲会话无法解析，本次任务将不启用 Bot 中转: "
                    f"{type(exc).__name__}: {exc}",
                    level="warning",
                )
        publish_progress("collecting", scanned=0, collected=0)
        log("正在收集消息范围")
        ids = _collect_message_ids(
            acc,
            source_id,
            spec,
            progress_callback=lambda scanned, collected: publish_progress(
                "collecting",
                scanned=scanned,
                collected=collected,
            ),
        )

        total = len(ids)
        if not _wait_until_task_active(job_id, log):
            finish_cancelled()
            return
        publish_progress("preparing", total=total)
        log(f"开始处理 {total} 条消息: {source_id} -> {dest_id}")

        forward_mode = str(spec.get("forward_mode", "clone")).lower()
        preserve_source = forward_mode == "direct"
        mode = {
            "clone": "隐藏来源",
            "direct": "保留来源",
            "cache": "缓存发送",
        }.get(forward_mode, "隐藏来源")
        log(
            f"网页批量转发身份: 用户客户端；模式: {mode}；"
            "隐藏来源使用 messages.ForwardMessages(drop_author=True)，"
            "缓存发送使用 copy_message/copy_media_group，"
            + (
                f"受限时使用 Bot 中转缓冲会话 {relay_chat_id}"
                if cache_send and bot is not None and relay_chat_id is not None
                else "不使用 Bot 身份"
            )
        )
        processed = success = failed = skipped = 0
        handled_ids = set()
        group_cache = {}
        restricted_source_ids = set()
        last_logged_bucket = 0
        logged_quote_filter = False
        filter_signature = None
        filter_rules = None

        for chunk_start in range(0, total, BATCH_FETCH_CHUNK_SIZE):
            chunk_ids = ids[chunk_start:chunk_start + BATCH_FETCH_CHUNK_SIZE]
            if not _wait_until_task_active(job_id, log):
                finish_cancelled()
                return

            publish_progress(
                "preparing",
                total=total,
                fetched=chunk_start,
                processed=processed,
                success=success,
                failed=failed,
                skipped=skipped,
                current_id=chunk_ids[0] if chunk_ids else None,
            )
            try:
                fetched_messages = _worker_execute(
                    worker,
                    "批量读取消息",
                    lambda: acc.get_messages(source_id, chunk_ids),
                )
                if not isinstance(fetched_messages, list):
                    fetched_messages = [fetched_messages]
            except Exception as exc:
                log(
                    f"批量读取消息失败，回退逐条读取: "
                    f"{type(exc).__name__}: {exc}",
                    level="warning",
                )
                fetched_messages = []
                for message_id in chunk_ids:
                    try:
                        fetched_messages.append(
                            acc.get_messages(source_id, message_id)
                        )
                    except Exception:
                        fetched_messages.append(None)

            message_map = {
                getattr(item, "id", None): item
                for item in fetched_messages
                if item is not None and not getattr(item, "empty", False)
            }
            fetched_count = min(chunk_start + len(chunk_ids), total)

            for message_id in chunk_ids:
                if not _wait_until_task_active(job_id, log):
                    finish_cancelled()
                    return
                if message_id in handled_ids:
                    continue

                unit_count = 1
                group_messages = None
                try:
                    message = message_map.get(message_id)
                    if not message:
                        skipped += 1
                        processed += 1
                        publish_progress(
                            "forwarding",
                            total=total,
                            fetched=fetched_count,
                            processed=processed,
                            success=success,
                            failed=failed,
                            skipped=skipped,
                            current_id=message_id,
                        )
                        continue

                    media_group_id = getattr(message, "media_group_id", None)
                    if media_group_id and media_group_id in group_cache:
                        group_messages = group_cache[media_group_id]
                    else:
                        group_messages = _get_private_media_group_messages(
                            acc,
                            source_id,
                            message,
                        )
                        if media_group_id:
                            group_cache[media_group_id] = group_messages
                    group_ids = [item.id for item in group_messages]
                    handled_ids.update(group_ids)
                    unit_count = len(group_messages)

                    if not _wait_until_task_active(job_id, log):
                        finish_cancelled()
                        return

                    task = get_task(job_id)
                    task_spec = task.get("spec") or spec
                    next_filter_signature = tuple(
                        str(task_spec.get(field) or "")
                        for field in FILTER_FIELDS
                    )
                    if next_filter_signature != filter_signature:
                        filter_rules = _filter_rule_set(task_spec)
                        filter_signature = next_filter_signature
                    filtered = _apply_filter_rules(
                        group_messages,
                        filter_rules,
                    )
                    if (
                        filtered["quote_text_present"]
                        and not logged_quote_filter
                    ):
                        log(
                            "检测到 Telegram 引用文本，已通过 Pyrofork quote "
                            "字段纳入纯文本过滤"
                        )
                        logged_quote_filter = True
                    if filtered["excluded"]:
                        skipped += unit_count
                        processed += unit_count
                        publish_progress(
                            "forwarding",
                            total=total,
                            fetched=fetched_count,
                            processed=processed,
                            success=success,
                            failed=failed,
                            skipped=skipped,
                            current_id=message_id,
                        )
                        continue

                    cleaned_texts = filtered["cleaned_texts"]
                    text_changed = filtered["text_changed"]
                    if filtered["rich_content_changed"]:
                        log(
                            f"消息 {message_id} 的引用、回复或链接预览命中删除规则，"
                            "将移除富文本预览后重发正文"
                        )
                    cleaned_text = next(
                        (text for text in cleaned_texts if text),
                        "",
                    )
                    if unit_count == 1 and get_message_type(
                        group_messages[0]
                    ) in ("Text", None) and not cleaned_text.strip():
                        skipped += unit_count
                        processed += unit_count
                        publish_progress(
                            "forwarding",
                            total=total,
                            fetched=fetched_count,
                            processed=processed,
                            success=success,
                            failed=failed,
                            skipped=skipped,
                            current_id=message_id,
                        )
                        continue

                    sent_count, used_fallback = _forward_batch_unit(
                        worker,
                        acc,
                        source_id,
                        dest_id,
                        group_messages,
                        cleaned_text,
                        text_changed,
                        preserve_source,
                        log,
                        restricted_source_ids,
                        cache_send=cache_send,
                        bot=bot,
                        relay_chat_id=relay_chat_id,
                        source_username=source_username,
                        cleaned_texts=cleaned_texts,
                        wait_for_active=lambda: _wait_until_task_active(
                            job_id,
                            log,
                        ),
                    )
                    success += sent_count
                    processed += sent_count
                    if used_fallback:
                        fallback_label = "媒体组" if unit_count > 1 else "消息"
                        log(
                            f"消息 {message_id} 受限，已通过用户客户端下载后重传"
                            f"（{fallback_label}，共 {sent_count} 项）"
                        )
                except BatchTaskStopped:
                    finish_cancelled()
                    return
                except Exception as exc:
                    unit_count = len(group_messages) if group_messages else 1
                    failed += unit_count
                    processed += unit_count
                    log(
                        f"消息 {message_id} 失败: {type(exc).__name__}: {exc}",
                        level="error",
                    )

                publish_progress(
                    "forwarding",
                    total=total,
                    fetched=fetched_count,
                    processed=processed,
                    success=success,
                    failed=failed,
                    skipped=skipped,
                    current_id=message_id,
                )
                log_bucket = processed // 10
                if log_bucket > last_logged_bucket:
                    last_logged_bucket = log_bucket
                    log(
                        f"进度 {processed}/{total}，成功 {success}，"
                        f"失败 {failed}，跳过 {skipped}"
                    )

        if get_task(job_id).get("cancelled"):
            finish_cancelled()
            return

        log(f"任务完成: 成功 {success}，失败 {failed}，跳过 {skipped}")
        publish_progress(
            "done" if failed == 0 else "error",
            total=total,
            fetched=total,
            processed=processed,
            success=success,
            failed=failed,
            skipped=skipped,
        )
        _update_task(
            job_id,
            status="done" if failed == 0 else "error",
            exitCode=0 if failed == 0 else 1,
            stderrTail=_tail("\n".join(log_lines)),
        )
        persist(force=True)
    except Exception as exc:
        if get_task(job_id).get("cancelled"):
            finish_cancelled()
            return
        log(f"任务异常终止: {type(exc).__name__}: {exc}")
        current = get_task(job_id).get("progress") or {}
        publish_progress(
            "error",
            total=current.get("total", 0),
            fetched=current.get("fetched", 0),
            processed=current.get("processed", 0),
            success=current.get("success", 0),
            failed=current.get("failed", 0),
            skipped=current.get("skipped", 0),
            current_id=current.get("current_id"),
        )
        _update_task(
            job_id,
            status="error",
            exitCode=1,
            stderrTail=_tail("\n".join(log_lines)),
        )
        persist(force=True)
    finally:
        _update_task(job_id, active=False)


def submit_batch_task(spec):
    spec = _validate_task_spec(dict(spec or {}))

    job_id = str(uuid.uuid4())
    state = {
        "taskName": spec.get("task_name") or "",
        "sourceId": spec.get("source") or "",
        "targetId": spec.get("target") or "",
        "rangeType": spec.get("range_type") or "id",
        "startValue": spec.get("start") or "",
        "endValue": spec.get("end") or "",
        "forwardMode": spec.get("forward_mode") or "clone",
        "relayChat": spec.get("relay_chat") or "",
        "excludeKeywords": spec.get("exclude_keywords") or "",
        "excludeRegex": spec.get("exclude_regex") or "",
        "removeKeywords": spec.get("remove_keywords") or "",
        "removeRegex": spec.get("remove_regex") or "",
        "desc": bool(spec.get("reverse")),
    }
    task = {
        "id": job_id,
        "status": "running",
        "active": True,
        "exitCode": None,
        "cancelled": False,
        "paused": False,
        "resume_event": threading.Event(),
        "progress": {
            "phase": "queued",
            "phase_label": PROGRESS_PHASES["queued"],
            "total": 0,
            "fetched": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        },
        "stdoutTail": "",
        "stderrTail": "",
        "spec": spec,
        "taskName": spec.get("task_name") or "",
        "sourceId": str(spec.get("source") or ""),
        "targetId": str(spec.get("target") or ""),
        "createdAt": _now_iso(),
        "state": state,
    }
    task["resume_event"].set()
    with TASKS_LOCK:
        task_name_key = _task_name(task.get("taskName")).casefold()
        if task_name_key:
            for existing in TASKS.values():
                existing_active = existing.get(
                    "active",
                    existing.get("status") == "running",
                )
                if (
                    existing_active
                    and _task_name(existing.get("taskName")).casefold()
                    == task_name_key
                ):
                    raise ValueError(
                        f"同名任务正在运行: {task.get('taskName')}"
                    )
        TASKS[job_id] = task

    try:
        save_history(
            {
                "id": job_id,
                "taskName": spec.get("task_name") or "",
                "targetId": str(spec.get("target") or ""),
                "sourceId": str(spec.get("source") or ""),
                "outputPath": "",
                "task_spec": spec,
                "createdAt": _now_iso(),
                "state": state,
                "jobId": job_id,
                "status": "running",
                "exitCode": None,
                "progress": {},
                "stdoutTail": "",
                "stderrTail": "",
            }
        )
    except Exception:
        with TASKS_LOCK:
            TASKS.pop(job_id, None)
        raise

    threading.Thread(target=_run_batch_task, args=(job_id, spec), daemon=True).start()
    return job_id


def update_batch_rules(job_id, rules):
    if not isinstance(rules, dict):
        raise ValueError("规则格式不正确")

    updates = {
        field: str(rules[field] or "")
        for field in FILTER_FIELDS
        if field in rules
    }
    if not updates:
        raise ValueError("没有可更新的规则")

    if "exclude_regex" in updates:
        _compile_regex_patterns(updates["exclude_regex"], "排除正则")
    if "remove_regex" in updates:
        _compile_regex_patterns(updates["remove_regex"], "删除正则")

    with TASKS_LOCK:
        task = TASKS.get(job_id)
        if not task:
            return False
        active = task.get("active", task.get("status") in ("running", "paused"))
        if not active or task.get("status") not in ("running", "paused"):
            return False

        spec = dict(task.get("spec") or {})
        spec.update(updates)
        state = dict(task.get("state") or {})
        state.update(
            {
                FILTER_STATE_KEYS[field]: value
                for field, value in updates.items()
            }
        )
        task["spec"] = spec
        task["state"] = state

    _persist_task_history(job_id)
    return spec


def pause_batch_task(job_id):
    with TASKS_LOCK:
        task = TASKS.get(job_id)
        if not task or task.get("status") != "running" or not task.get("active"):
            return False
        event = task.get("resume_event")
        if event is not None:
            event.clear()
        task["paused"] = True
        task["status"] = "paused"
        progress = dict(task.get("progress") or {})
        progress["phase"] = "paused"
        progress["phase_label"] = PROGRESS_PHASES["paused"]
        task["progress"] = progress
    _persist_task_history(job_id)
    return True


def resume_batch_task(job_id):
    with TASKS_LOCK:
        task = TASKS.get(job_id)
        if not task or task.get("status") != "paused" or not task.get("active"):
            return False
        task["paused"] = False
        task["status"] = "running"
        progress = dict(task.get("progress") or {})
        progress["phase"] = "forwarding"
        progress["phase_label"] = PROGRESS_PHASES["forwarding"]
        progress["eta_seconds"] = None
        task["progress"] = progress
        event = task.get("resume_event")
        if event is not None:
            event.set()
    _persist_task_history(job_id)
    return True


def cancel_batch_task(job_id):
    with TASKS_LOCK:
        task = TASKS.get(job_id)
        if not task:
            return False
        active = task.get("active", task.get("status") == "running")
        if not active or task.get("status") not in ("running", "paused"):
            return False
        task["cancelled"] = True
        task["paused"] = False
        task["status"] = "cancelled"
        task["exitCode"] = 130
        event = task.get("resume_event")
        if event is not None:
            event.set()
    _persist_task_history(job_id)
    return True


def batch_status(job_id):
    task = get_task(job_id)
    if not task:
        history = get_history_record(job_id)
        if not history:
            return None
        return {
            "jobId": job_id,
            "status": history.get("status") or "unknown",
            "exitCode": history.get("exitCode"),
            "paused": history.get("status") == "paused",
            "progress": history.get("progress") or {},
            "stdoutTail": history.get("stdoutTail") or "",
            "stderrTail": history.get("stderrTail") or "",
            "spec": history.get("task_spec") or {},
        }
    return {
        "jobId": job_id,
        "status": task.get("status"),
        "exitCode": task.get("exitCode"),
        "paused": bool(task.get("paused")),
        "progress": task.get("progress") or {},
        "stdoutTail": task.get("stdoutTail") or "",
        "stderrTail": task.get("stderrTail") or "",
        "spec": task.get("spec") or {},
    }


init_history_db()
