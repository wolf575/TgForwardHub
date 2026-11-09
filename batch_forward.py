"""Batch forwarding service for the merged web UI.

Keeps the A-style task form semantics (source, target, id/time range, keyword
filters, reverse order) but performs forwarding directly with the B project's
Pyrogram clients.
"""
import json
import os
import queue
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unicodedata
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone

from pyrogram.errors import (
    ChatForwardsRestricted,
    FileReferenceExpired,
    FloodWait,
    InternalServerError,
    MessageNotModified,
    Timeout as TelegramTimeout,
)
from database import DATA_DIR
from app_settings import (
    client_batch_notifications_enabled,
    get_app_timezone,
    get_notify_config,
)
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
from bot.core.client import client_sync_timeout, set_client_sync_timeout
from bot.utils.helpers import get_message_type
from bot.utils.logger import get_logger
from bot.workers.message_worker import MessageWorker
from pyrogram_compat import (
    apply_pyrofork_messages_topics_compat,
    apply_pyrogram_peer_id_compat,
    normalize_private_channel_ref,
)


apply_pyrogram_peer_id_compat()
apply_pyrofork_messages_topics_compat()

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
DEFAULT_RATE_LIMIT_PER_MINUTE = 25
_EMPTY_CAPTION_SENTINEL = "\u2063"
_BATCH_SCAN_END = object()
BATCH_SYNC_TIMEOUT_SECONDS = float(
    os.environ.get("BATCH_SYNC_TIMEOUT_SECONDS", "120")
)
BATCH_DOWNLOAD_TIMEOUT_SECONDS = float(
    os.environ.get("BATCH_DOWNLOAD_TIMEOUT_SECONDS", "900")
)
BATCH_STALL_TIMEOUT_SECONDS = float(
    os.environ.get("BATCH_STALL_TIMEOUT_SECONDS", "900")
)


class BatchTaskStopped(Exception):
    """Raised when a paused/cancelled task must not start another send."""


class _BatchScanFailure:
    def __init__(self, error):
        self.error = error


class BatchRateLimiter:
    """Rolling one-minute limiter for batch send units."""

    def __init__(self, limit_per_minute, log=None, progress_callback=None):
        self.limit_per_minute = max(1, int(limit_per_minute))
        self.log = log
        self.progress_callback = progress_callback
        self.sent_at = deque()

    def wait(self, units=1):
        units = max(1, int(units))
        while True:
            now = time.monotonic()
            while self.sent_at and now - self.sent_at[0] >= 60:
                self.sent_at.popleft()
            if len(self.sent_at) + units <= self.limit_per_minute:
                self.sent_at.extend([now] * units)
                return
            wait_seconds = max(
                0.1,
                60 - (now - self.sent_at[0]) + 0.05,
            )
            if self.progress_callback is not None:
                self.progress_callback(wait_seconds)
            if self.log is not None:
                self.log(
                    f"速率限制: 每分钟最多 {self.limit_per_minute} 个发送单元，"
                    f"等待 {wait_seconds:.1f} 秒后继续",
                    level="warning",
                )
            time.sleep(wait_seconds)


def _batch_notification_payload(task_name, job_id, status, progress, error=None):
    label = "执行完成" if status == "done" else "执行失败"
    content = (
        f"任务: {task_name or '未命名任务'}\n"
        f"状态: {label}\n"
        f"任务 ID: {job_id}\n"
        f"总数: {int(progress.get('total') or 0)}\n"
        f"已处理: {int(progress.get('processed') or 0)}\n"
        f"成功: {int(progress.get('success') or 0)}\n"
        f"失败: {int(progress.get('failed') or 0)}\n"
        f"跳过: {int(progress.get('skipped') or 0)}"
    )
    elapsed = progress.get("elapsed_seconds")
    if elapsed is not None:
        content += f"\n耗时: {elapsed} 秒"
    if error:
        content += f"\n错误: {str(error)[:500]}"
    return f"TgForwardHub {label}", content


def _send_batch_notification(task_name, job_id, status, progress, error=None):
    try:
        if not client_batch_notifications_enabled():
            return
        from notify import send_with_config

        title, content = _batch_notification_payload(
            task_name,
            job_id,
            status,
            progress,
            error,
        )
        send_with_config(title, content, get_notify_config())
    except Exception:
        logger.exception("批量任务通知发送失败")


def _queue_batch_notification(task_name, job_id, status, progress, error=None):
    threading.Thread(
        target=_send_batch_notification,
        args=(task_name, job_id, status, progress, error),
        daemon=True,
        name="BatchNotification",
    ).start()


PROGRESS_PHASES = {
    "queued": "排队中",
    "resolving": "解析来源与目标",
    "collecting": "收集消息",
    "preparing": "准备消息批次",
    "forwarding": "转发消息",
    "rate_limit": "等待速率限制",
    "flood_wait": "等待 Telegram 限流",
    "stalled": "任务疑似卡住",
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
    variants = _filter_text_variants(text)
    if hasattr(terms, "search"):
        return any(terms.search(value) for value in variants)
    pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
    return any(pattern.search(value) for value in variants)


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
            # Rich-text captions commonly contain line breaks. DOTALL keeps
            # user patterns useful even when the UI does not preserve an
            # explicit (?s) prefix.
            compiled.append(re.compile(pattern, re.DOTALL))
    except re.error as exc:
        raise ValueError(f"{field_name} 格式错误: {exc}") from exc
    return compiled


def _matches_exclude_regex(text, patterns):
    variants = _filter_text_variants(text)
    return any(pattern.search(value) for pattern in patterns for value in variants)


def _caption_overrides(cleaned_texts, cleaned_text, count):
    """Build one caption value for every media-group item."""
    if cleaned_texts is None:
        return [cleaned_text] + [""] * max(0, count - 1)
    values = list(cleaned_texts)
    if len(values) < count:
        values.extend([""] * (count - len(values)))
    return values[:count]


def _result_message_ids(result):
    """Extract sent message IDs in album order from high-level/raw results."""
    ids = []

    def add_message_id(value):
        if value is None:
            return
        try:
            message_id = int(value)
        except (TypeError, ValueError):
            return
        if message_id not in ids:
            ids.append(message_id)

    if isinstance(result, (list, tuple)):
        for item in result:
            add_message_id(getattr(item, "id", None))
    elif getattr(result, "id", None) is not None:
        add_message_id(result.id)

    for update in getattr(result, "updates", []) or []:
        message = getattr(update, "message", None)
        add_message_id(getattr(message, "id", None))

    return ids


def _media_group_caption_values(group_messages, captions):
    """Build copy_media_group captions without retaining filtered source text.

    Pyrogram treats an empty list item as "not supplied" and keeps the source
    caption. Use ``None`` when the source item had no caption, and a tiny
    invisible sentinel only when an existing caption must be cleared after the
    album is sent. Non-empty filtered captions are sent in the initial RPC.
    """
    values = list(captions or [])
    originals = (
        _group_texts(group_messages)
        if group_messages
        else [""] * len(values)
    )
    result = []
    for index, desired in enumerate(values):
        if desired is None:
            result.append(None)
            continue
        desired = str(desired)
        original = originals[index] if index < len(originals) else ""
        if desired:
            result.append(desired)
        elif original:
            result.append(_EMPTY_CAPTION_SENTINEL)
        else:
            # Keep an already-empty source caption empty without an edit.
            result.append(None)
    return result


def _edit_media_group_captions(
    worker,
    client,
    destination,
    result,
    captions,
    log=None,
    indexes=None,
):
    """Clear sentinel captions after the album itself was sent successfully."""
    message_ids = _result_message_ids(result)
    if not message_ids:
        raise RuntimeError("媒体组发送成功但无法获取目标消息 ID")
    if indexes is None:
        indexes = range(len(captions))
    indexes = list(indexes)
    if indexes and max(indexes) >= len(message_ids):
        _emit_log(
            f"媒体组返回 {len(message_ids)} 项，少于源媒体组 {len(captions)} 项，"
            "仅更新已返回条目的 caption",
            log,
            "warning",
        )

    for index in indexes:
        if index < 0 or index >= len(message_ids) or index >= len(captions):
            continue
        message_id = message_ids[index]
        caption = captions[index]
        desired = caption or ""
        try:
            _worker_execute(
                worker,
                f"清空媒体组第 {index + 1} 项 caption",
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
                f"媒体组第 {index + 1} 项 caption 更新失败: "
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
    group_messages=None,
):
    """Copy an album with filtered captions in the initial request.

    This avoids the old send-then-edit sequence for normal filtered captions.
    Only an existing caption that becomes empty needs a follow-up edit because
    Pyrogram 2.x treats an empty list item as "keep the original caption".
    """
    caption_values = _media_group_caption_values(
        group_messages,
        captions,
    )
    result = _worker_execute(
        worker,
        "复制媒体组并携带过滤后的 caption（保持原相册顺序）",
        lambda: client.copy_media_group(
            destination,
            source_id,
            anchor_id,
            captions=caption_values,
        ),
    )
    clear_indexes = [
        index
        for index, caption in enumerate(caption_values)
        if caption == _EMPTY_CAPTION_SENTINEL
    ]
    if clear_indexes:
        _edit_media_group_captions(
            worker,
            client,
            destination,
            result,
            [""] * len(caption_values),
            log,
            indexes=clear_indexes,
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
    # Numeric private IDs already identify the source. Resolving them through
    # get_chat adds a slow network round trip and is unnecessary for batch
    # collection; the source username can be discovered from fetched messages.
    if re.fullmatch(r"-?\d+", normalized):
        return None
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


def _collect_message_ids(
    acc,
    source_id,
    spec,
    progress_callback=None,
    message_cache=None,
):
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
                if message_cache is not None:
                    if _message_primary_text(message) or _message_filter_texts(
                        message
                    ):
                        message_cache[message.id] = message
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


def _iter_batch_chunks(
    acc,
    worker,
    source_id,
    spec,
    collected_messages,
    log=None,
    progress_callback=None,
    stop_event=None,
):
    """Yield sendable chunks; time ranges forward while history is scanned."""
    range_type = spec.get("range_type", "id")
    reverse = bool(spec.get("reverse"))

    if range_type == "time":
        start_ts = _parse_timestamp(spec.get("start"))
        end_ts = _parse_timestamp(spec.get("end"), end_of_day=True)
        if start_ts is None or end_ts is None:
            raise ValueError("时间范围格式不正确")
        if start_ts > end_ts:
            start_ts, end_ts = end_ts, start_ts

        batch_messages = []
        scanned = 0
        collected = 0
        seen_ids = set()

        # Pyrofork reverses each page when ``reverse=True`` but still advances
        # its offset with the last message after that reversal. That repeats
        # the same page. Fetch one explicit page at a time and move the cursor
        # with Telegram's monotonic ID rules instead.
        offset_id = 0
        if reverse:
            offset_date = datetime.fromtimestamp(end_ts + 1, tz=timezone.utc)
            page_offset = 0
            page_reverse = False
        else:
            offset_date = datetime.fromtimestamp(
                max(0, start_ts - 1),
                tz=timezone.utc,
            )
            page_offset = -BATCH_FETCH_CHUNK_SIZE
            page_reverse = True

        while stop_event is None or not stop_event.is_set():
            kwargs = {
                "limit": BATCH_FETCH_CHUNK_SIZE,
                "offset_id": offset_id,
                "offset_date": offset_date,
            }
            if page_offset:
                kwargs["offset"] = page_offset
            if page_reverse:
                kwargs["reverse"] = True
            try:
                page = list(acc.get_chat_history(source_id, **kwargs) or [])
            except TypeError:
                # Pyrofork 2.3.x supports reverse pagination. This fallback
                # only covers lightweight/older clients and still advances the
                # cursor so a page cannot be replayed indefinitely.
                kwargs.pop("offset", None)
                kwargs.pop("reverse", None)
                page = list(
                    acc.get_chat_history(
                        source_id,
                        limit=BATCH_FETCH_CHUNK_SIZE,
                        offset_id=offset_id,
                        offset_date=offset_date,
                    )
                    or []
                )

            page = [message for message in page if message is not None]
            if not page:
                break

            page_ids = [
                getattr(message, "id", None)
                for message in page
                if getattr(message, "id", None) is not None
            ]
            new_page_ids = [
                message_id
                for message_id in page_ids
                if message_id not in seen_ids
            ]
            if page_ids and not new_page_ids:
                if log is not None:
                    log(
                        "消息历史分页返回了重复内容，已停止继续扫描以避免重复转发",
                        level="warning",
                    )
                break

            scanned += len(new_page_ids)
            reached_boundary = False
            for message in page:
                if stop_event is not None and stop_event.is_set():
                    return
                message_id = getattr(message, "id", None)
                message_date = getattr(message, "date", None)
                if message_id is None or message_date is None:
                    continue
                if message_id in seen_ids:
                    continue
                ts = message_date.timestamp()
                if reverse:
                    if ts < start_ts:
                        reached_boundary = True
                        break
                    if ts > end_ts:
                        continue
                else:
                    if ts < start_ts:
                        continue
                    if ts > end_ts:
                        reached_boundary = True
                        break

                seen_ids.add(message_id)
                collected += 1
                if _message_primary_text(message) or _message_filter_texts(message):
                    collected_messages[message_id] = message
                batch_messages.append(message)
                if len(batch_messages) >= BATCH_FETCH_CHUNK_SIZE:
                    if progress_callback:
                        progress_callback(scanned, collected)
                    yield (
                        [item.id for item in batch_messages],
                        batch_messages,
                        collected,
                        collected,
                        scanned,
                    )
                    batch_messages = []

            if progress_callback:
                progress_callback(scanned, collected)
            if reached_boundary:
                break

            cursor_messages = [
                message
                for message in page
                if getattr(message, "id", None) is not None
                and getattr(message, "date", None) is not None
            ]
            if not cursor_messages:
                break
            ordered_page = sorted(cursor_messages, key=lambda item: item.id)
            if reverse:
                next_offset_id = ordered_page[0].id
                if offset_id and next_offset_id >= offset_id:
                    break
                offset_date = ordered_page[0].date
            else:
                next_offset_id = ordered_page[-1].id + 1
                if offset_id and next_offset_id <= offset_id:
                    break
                offset_date = ordered_page[-1].date
            offset_id = next_offset_id

        if batch_messages:
            yield (
                [item.id for item in batch_messages],
                batch_messages,
                collected,
                collected,
                scanned,
            )
        return

    ids = _collect_message_ids(
        acc,
        source_id,
        spec,
        progress_callback=progress_callback,
        message_cache=collected_messages,
    )
    total = len(ids)
    for chunk_start in range(0, total, BATCH_FETCH_CHUNK_SIZE):
        if stop_event is not None and stop_event.is_set():
            return
        chunk_ids = ids[chunk_start:chunk_start + BATCH_FETCH_CHUNK_SIZE]
        fetched_messages = []
        missing_ids = []
        for message_id in chunk_ids:
            cached_message = collected_messages.get(message_id)
            if cached_message is not None:
                fetched_messages.append(cached_message)
            else:
                missing_ids.append(message_id)
        if missing_ids:
            try:
                batch_messages = _worker_execute(
                    worker,
                    "批量读取消息",
                    lambda: acc.get_messages(source_id, missing_ids),
                )
                if not isinstance(batch_messages, list):
                    batch_messages = [batch_messages]
                fetched_messages.extend(batch_messages)
            except Exception as exc:
                if log is not None:
                    log(
                        f"批量读取消息失败，回退逐条读取: "
                        f"{type(exc).__name__}: {exc}",
                        level="warning",
                    )
                for message_id in missing_ids:
                    try:
                        fetched_messages.append(
                            acc.get_messages(source_id, message_id)
                        )
                    except Exception:
                        fetched_messages.append(None)
        yield (
            chunk_ids,
            fetched_messages,
            min(chunk_start + len(chunk_ids), total),
            total,
            min(chunk_start + len(chunk_ids), total),
        )


def _start_batch_scan(
    acc,
    worker,
    source_id,
    spec,
    collected_messages,
    stop_event,
    log=None,
    progress_callback=None,
    complete_callback=None,
):
    """Run history scanning independently from the forwarding consumer."""
    scan_queue = queue.Queue()

    def scan():
        try:
            for chunk in _iter_batch_chunks(
                acc,
                worker,
                source_id,
                spec,
                collected_messages,
                log=log,
                progress_callback=progress_callback,
                stop_event=stop_event,
            ):
                if stop_event.is_set():
                    break
                scan_queue.put(chunk)
            if not stop_event.is_set() and complete_callback is not None:
                complete_callback()
        except Exception as exc:
            if not stop_event.is_set():
                scan_queue.put(_BatchScanFailure(exc))
        finally:
            scan_queue.put(_BATCH_SCAN_END)

    thread = threading.Thread(
        target=scan,
        daemon=True,
        name="BatchScanner",
    )
    thread.start()
    return scan_queue, thread


def _iter_scanned_chunks(scan_queue, stop_event=None, should_stop=None):
    while True:
        try:
            item = scan_queue.get(timeout=0.5)
        except queue.Empty:
            if (
                (stop_event is not None and stop_event.is_set())
                or (should_stop is not None and should_stop())
            ):
                return
            continue
        if item is _BATCH_SCAN_END:
            return
        if isinstance(item, _BatchScanFailure):
            raise item.error
        yield item


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

    raw_rate_limit = spec.get("rate_limit_per_minute")
    try:
        rate_limit = int(
            DEFAULT_RATE_LIMIT_PER_MINUTE
            if raw_rate_limit is None
            else raw_rate_limit
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("每分钟转发上限必须是整数") from exc
    if rate_limit < 1 or rate_limit > 1000:
        raise ValueError("每分钟转发上限必须在 1 到 1000 之间")
    spec["rate_limit_per_minute"] = rate_limit

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


def _raw_message_value(message, *names):
    """Read a field from Pyrofork's optional raw MTProto message."""
    try:
        raw = getattr(message, "raw", None)
    except Exception:
        raw = None
    if raw is None:
        return None
    for name in names:
        try:
            value = getattr(raw, name, None)
        except Exception:
            value = None
        if value:
            return value
    return None


def _message_primary_text(message):
    """Return high-level text, falling back to raw MTProto text."""
    value = getattr(message, "caption", None) or getattr(message, "text", None)
    if value:
        return value
    return _raw_message_value(message, "message") or ""


def _group_texts(group_messages):
    """Return every caption/text in a media group, preserving item order."""
    return [
        str(_message_primary_text(message))
        for message in group_messages
    ]


def _visible_filter_text(value):
    """Return visible text without changing user-visible symbols."""
    text = str(value or "")
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
    )


def _plain_filter_text(value):
    """Return an NFKC compatibility view for legacy/full-width rules."""
    return _visible_filter_text(unicodedata.normalize("NFKC", str(value or "")))


def _filter_text_variants(value):
    """Return visible text first, then an NFKC fallback when they differ."""
    visible = _visible_filter_text(value)
    without_variation_selectors = visible.replace("\ufe0e", "").replace(
        "\ufe0f",
        "",
    )
    normalized = _plain_filter_text(value)
    variants = [visible, without_variation_selectors, normalized]
    result = []
    for variant in variants:
        if variant not in result:
            result.append(variant)
    return result


def _remove_filter_matches(text, terms, patterns):
    """Remove matches while preserving the original visible characters."""
    visible = _visible_filter_text(text)
    cleaned_visible = _remove_matches(visible, terms, patterns)
    if cleaned_visible != visible:
        return True, cleaned_visible

    without_variation_selectors = visible.replace("\ufe0e", "").replace(
        "\ufe0f",
        "",
    )
    cleaned_without_variation_selectors = _remove_matches(
        without_variation_selectors,
        terms,
        patterns,
    )
    if cleaned_without_variation_selectors != without_variation_selectors:
        return True, cleaned_without_variation_selectors

    normalized = _plain_filter_text(text)
    cleaned_normalized = _remove_matches(normalized, terms, patterns)
    if cleaned_normalized != normalized:
        return True, cleaned_normalized
    return False, visible


def _unique_text_fragments(values):
    result = []
    seen = set()
    for value in values:
        if value is None:
            continue
        text = _visible_filter_text(value)
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
    raw_text = _raw_message_value(message, "message")
    if raw_text:
        values.append(raw_text)

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

    raw_reply = _raw_message_value(message, "reply_to")
    if raw_reply is not None:
        values.extend(
            getattr(raw_reply, attr, None)
            for attr in ("text", "caption", "quote_text", "quote_caption")
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
        or bool(
            getattr(
                _raw_message_value(message, "reply_to"),
                "quote_text",
                None,
            )
        )
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

    cleaned_plain_texts = []
    primary_changed = False
    for text in primary_texts:
        changed, cleaned = _remove_filter_matches(
            text,
            remove_terms,
            remove_patterns,
        )
        primary_changed = primary_changed or changed
        cleaned_plain_texts.append(cleaned)

    text_changed = primary_changed
    for text in filter_texts:
        changed, _ = _remove_filter_matches(
            text,
            remove_terms,
            remove_patterns,
        )
        text_changed = text_changed or changed
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


def _copy_relay_messages(client, destination, relay_id, relay_message_ids):
    """Copy relayed messages without raw ``ForwardMessages`` result parsing."""
    if len(relay_message_ids) > 1:
        return client.copy_media_group(
            destination,
            relay_id,
            relay_message_ids[0],
        )
    return client.copy_message(
        destination,
        relay_id,
        relay_message_ids[0],
    )


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
                group_messages=group_messages,
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
            f"Bot 已复制到缓冲会话 {relay_id}，准备由用户客户端复制到目标: "
            f"{relay_ids} -> {dest_id}",
            log,
        )
        _worker_execute(
            worker,
            "用户客户端复制中转缓冲消息",
            lambda: _copy_relay_messages(
                acc,
                dest_id,
                relay_id,
                relay_ids,
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
            with client_sync_timeout(BATCH_DOWNLOAD_TIMEOUT_SECONDS):
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
            with client_sync_timeout(BATCH_DOWNLOAD_TIMEOUT_SECONDS):
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
    use_copy = cache_send or not preserve_source or text_changed
    try:
        if use_copy:
            _emit_log(
                f"媒体组 {anchor.id} 使用用户客户端缓存复制: "
                f"{source_id} -> {dest_id}，RPC=copy_media_group",
                log,
            )
            if text_changed:
                captions = _caption_overrides(
                    cleaned_texts,
                    cleaned_text,
                    len(group_messages),
                )
                _copy_media_group_and_set_captions(
                    worker,
                    acc,
                    dest_id,
                    source_id,
                    anchor.id,
                    captions,
                    log,
                    group_messages=group_messages,
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
                f"媒体组 {anchor.id} 已通过缓存复制发送: "
                f"{source_id} -> {dest_id}",
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
            _emit_log(
                f"媒体组 {anchor.id} 已通过直接转发发送: "
                f"{source_id} -> {dest_id}",
                log,
            )
        return len(group_messages), False
    except Exception as exc:
        action = "缓存复制" if use_copy else "直接转发"
        restricted = isinstance(exc, ChatForwardsRestricted)
        _emit_log(
            f"媒体组 {anchor.id} {action}失败: "
            f"{type(exc).__name__}: {exc}",
            log,
            "warning",
        )
        if restricted and restricted_source_ids is not None:
            restricted_source_ids.add(source_id)
            _emit_log(
                f"来源 {source_id} 已确认限制缓存转发，后续消息将直接下载重传",
                log,
                "warning",
            )
        if cache_send and bot is not None and relay_chat_id is not None:
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
        with client_sync_timeout(BATCH_DOWNLOAD_TIMEOUT_SECONDS):
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
    use_copy = cache_send or not preserve_source or text_changed
    try:
        if use_copy:
            _emit_log(
                f"单条媒体 {message.id} 使用用户客户端缓存复制: "
                f"{source_id} -> {dest_id}，RPC=copy_message",
                log,
            )
            _worker_execute(
                worker,
                "复制单条媒体",
                lambda: _copy_single_private_media(
                    acc,
                    dest_id,
                    source_id,
                    message,
                    caption=cleaned_text if text_changed else None,
                ),
            )
            _emit_log(
                f"单条媒体 {message.id} 已通过缓存复制发送: "
                f"{source_id} -> {dest_id}",
                log,
            )
        else:
            _worker_execute(
                worker,
                "转发单条媒体",
                lambda: acc.forward_messages(dest_id, source_id, message.id),
            )
            _emit_log(
                f"单条媒体 {message.id} 已通过直接转发发送: "
                f"{source_id} -> {dest_id}",
                log,
            )
        return 1, False
    except Exception as exc:
        action = "缓存复制" if use_copy else "直接转发"
        restricted = isinstance(exc, ChatForwardsRestricted)
        _emit_log(
            f"单条媒体 {message.id} {action}失败: "
            f"{type(exc).__name__}: {exc}",
            log,
            "warning",
        )
        if restricted and restricted_source_ids is not None:
            restricted_source_ids.add(source_id)
            _emit_log(
                f"来源 {source_id} 的单条缓存复制受限，后续消息将直接下载重传",
                log,
                "warning",
            )
        if cache_send and bot is not None and relay_chat_id is not None:
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
    use_copy = cache_send or not preserve_source or text_changed
    try:
        if use_copy and text_changed:
            _worker_execute(
                worker,
                "发送修改后的文本",
                lambda: acc.send_message(dest_id, cleaned_text),
            )
        elif use_copy:
            _worker_execute(
                worker,
                "复制文本消息",
                lambda: acc.copy_message(dest_id, source_id, message.id),
            )
        else:
            _worker_execute(
                worker,
                "转发文本消息",
                lambda: acc.forward_messages(dest_id, source_id, message.id),
            )
        _emit_log(
            f"文本消息 {message.id} 已通过"
            f"{'缓存复制' if use_copy else '直接转发'}发送: "
            f"{source_id} -> {dest_id}",
            log,
        )
        return 1, False
    except Exception as exc:
        restricted = isinstance(exc, ChatForwardsRestricted)
        _emit_log(
            f"文本消息 {message.id} "
            f"{'缓存复制' if use_copy else '直接转发'}失败: "
            f"{type(exc).__name__}: {exc}",
            log,
            "warning",
        )
        if restricted and restricted_source_ids is not None:
            restricted_source_ids.add(source_id)
            _emit_log(
                f"来源 {source_id} 的文本缓存复制受限，后续文本将直接重新发送",
                log,
                "warning",
            )
        if cache_send and bot is not None and relay_chat_id is not None:
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
    last_activity = [time.monotonic()]
    flood_wait_until = [0.0]
    stream_state = {
        "enabled": False,
        "scanning": False,
        "scan_complete": False,
        "scanned": 0,
        "collected": 0,
    }
    persist_lock = threading.Lock()
    scan_stop_event = threading.Event()
    scan_thread = None

    def persist(force=False):
        nonlocal last_persist
        with persist_lock:
            now = time.monotonic()
            last_activity[0] = now
            if force or now - last_persist >= 1.0:
                _persist_task_history(job_id)
                last_persist = now

    def log(message, level="info"):
        last_activity[0] = time.monotonic()
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
        last_activity[0] = time.monotonic()
        elapsed = max(0.0, time.monotonic() - started_monotonic)
        total = int(values.get("total") or 0)
        if stream_state["enabled"] and phase not in (
            "done",
            "error",
            "cancelled",
        ):
            total = 0
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
            "scanned": int(
                values.get("scanned", stream_state["scanned"]) or 0
            ),
            "collected": int(
                values.get("collected", stream_state["collected"]) or 0
            ),
            "current_id": values.get("current_id"),
            "wait_seconds": int(values.get("wait_seconds") or 0),
            "stalled_seconds": int(values.get("stalled_seconds") or 0),
            "streaming": bool(stream_state["enabled"]),
            "scanning": bool(stream_state["scanning"]),
            "scan_complete": bool(stream_state["scan_complete"]),
            "pending": max(
                0,
                int(
                    values.get("collected", stream_state["collected"]) or 0
                )
                - processed,
            ),
        }
        _update_task(job_id, progress=progress)
        persist()
        return progress

    def handle_worker_event(event):
        event_type = str(event.get("type") or "")
        operation = str(event.get("operation") or "Telegram 操作")
        current = get_task(job_id).get("progress") or {}
        if event_type == "flood_wait":
            wait_seconds = max(1, int(event.get("wait_seconds") or 0))
            flood_wait_until[0] = time.monotonic() + wait_seconds + 2
            publish_progress(
                "flood_wait",
                total=current.get("total", 0),
                fetched=current.get("fetched", 0),
                processed=current.get("processed", 0),
                success=current.get("success", 0),
                failed=current.get("failed", 0),
                skipped=current.get("skipped", 0),
                scanned=current.get("scanned", 0),
                collected=current.get("collected", 0),
                current_id=current.get("current_id"),
                wait_seconds=wait_seconds,
            )
            log(
                f"{operation} 遇到 Telegram FloodWait，需要等待 "
                f"{wait_seconds} 秒后自动重试 "
                f"({event.get('attempt', 1)}/{event.get('max_attempts', 1)})",
                level="warning",
            )
        elif event_type == "flood_wait_resumed":
            flood_wait_until[0] = 0.0
            log(f"{operation} 的 FloodWait 已结束，继续执行")
        elif event_type == "flood_wait_exhausted":
            flood_wait_until[0] = 0.0
            log(
                f"{operation} 的 FloodWait 重试次数已耗尽，本条消息将记为失败",
                level="error",
            )

    def watchdog():
        interval = 15.0
        while True:
            task = get_task(job_id)
            if (
                not task
                or not task.get("active")
                or task.get("status") in ("done", "error", "cancelled")
            ):
                return
            time.sleep(interval)
            now = time.monotonic()
            if now < flood_wait_until[0]:
                continue
            idle_seconds = now - last_activity[0]
            if idle_seconds < BATCH_STALL_TIMEOUT_SECONDS:
                continue
            with TASKS_LOCK:
                task = TASKS.get(job_id)
                if not task or not task.get("active"):
                    return
                progress = dict(task.get("progress") or {})
                progress.update(
                    {
                        "phase": "stalled",
                        "phase_label": PROGRESS_PHASES["stalled"],
                        "stalled_seconds": round(idle_seconds),
                    }
                )
                task["progress"] = progress
                warning = (
                    f"[{_now_iso()}] 警告: 任务已超过 "
                    f"{int(idle_seconds)} 秒没有进度更新，当前操作可能卡住；"
                    "可在日志面板查看最后一条消息，必要时取消后重试"
                )
                task["stdoutTail"] = _tail(
                    "\n".join([task.get("stdoutTail") or "", warning]).strip()
                )
                _persist_task_history(job_id)
            logger.error("[batch:%s] %s", job_id, warning)
            return

    threading.Thread(
        target=watchdog,
        daemon=True,
        name=f"BatchWatchdog-{job_id[:8]}",
    ).start()

    try:
        set_client_sync_timeout(BATCH_SYNC_TIMEOUT_SECONDS)
        acc = get_acc_instance()
        if acc is None:
            raise RuntimeError("用户客户端尚未初始化，请先完成 /setup 配置")

        publish_progress("resolving")
        log("正在解析来源与目标")
        worker = MessageWorker(None, acc, max_retries=3)
        if hasattr(worker, "set_event_callback"):
            worker.set_event_callback(handle_worker_event)
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
        streaming_time = str(spec.get("range_type") or "id") == "time"
        stream_state["enabled"] = streaming_time
        stream_state["scanning"] = streaming_time
        stream_state["scan_complete"] = not streaming_time
        collected_messages = {}
        forward_mode = str(spec.get("forward_mode", "clone")).lower()
        preserve_source = forward_mode == "direct"
        mode = {
            "clone": "隐藏来源",
            "direct": "保留来源",
            "cache": "缓存发送",
        }.get(forward_mode, "隐藏来源")
        log(
            f"网页批量转发身份: 用户客户端；模式: {mode}；"
            "隐藏来源使用 copy_message/copy_media_group；"
            "保留来源使用 forward_messages；"
            + (
                f"受限时使用 Bot 中转缓冲会话 {relay_chat_id}"
                if cache_send and bot is not None and relay_chat_id is not None
                else "不使用 Bot 身份"
            )
        )
        if streaming_time:
            log("开始边扫描边批量转发；每收集 100 条消息即开始处理")
        else:
            log("正在收集消息范围")
        processed = success = failed = skipped = 0
        handled_ids = set()
        group_cache = {}
        restricted_source_ids = set()
        last_logged_bucket = 0
        logged_quote_filter = False
        filter_signature = None
        filter_rules = None
        rate_limit_value = spec.get("rate_limit_per_minute")
        rate_limit_per_minute = (
            int(rate_limit_value) if rate_limit_value is not None else 0
        )

        def rate_progress(wait_seconds):
            current = get_task(job_id).get("progress") or {}
            publish_progress(
                "rate_limit",
                total=current.get("total", 0),
                fetched=current.get("fetched", 0),
                processed=current.get("processed", 0),
                success=current.get("success", 0),
                failed=current.get("failed", 0),
                skipped=current.get("skipped", 0),
                scanned=current.get("scanned", 0),
                collected=current.get("collected", 0),
                current_id=current.get("current_id"),
                wait_seconds=round(wait_seconds),
            )

        rate_limiter = (
            BatchRateLimiter(
                rate_limit_per_minute,
                log=log,
                progress_callback=rate_progress,
            )
            if rate_limit_per_minute > 0
            else None
        )
        total = 0
        stream_total = 0
        logged_total = False

        def update_scan_progress(scanned, collected):
            stream_state["scanned"] = scanned
            stream_state["collected"] = collected
            current = dict(get_task(job_id).get("progress") or {})
            current.update(
                {
                    "scanned": scanned,
                    "collected": collected,
                    "streaming": streaming_time,
                    "scanning": stream_state["scanning"],
                    "scan_complete": stream_state["scan_complete"],
                    "pending": max(
                        0,
                        collected - int(current.get("processed") or 0),
                    ),
                }
            )
            _update_task(job_id, progress=current)
            persist()

        def mark_scan_complete():
            stream_state["scanning"] = False
            stream_state["scan_complete"] = True
            current = dict(get_task(job_id).get("progress") or {})
            current.update(
                {
                    "scanned": stream_state["scanned"],
                    "collected": stream_state["collected"],
                    "streaming": streaming_time,
                    "scanning": False,
                    "scan_complete": True,
                    "pending": max(
                        0,
                        stream_state["collected"]
                        - int(current.get("processed") or 0),
                    ),
                }
            )
            _update_task(job_id, progress=current)
            persist(force=True)

        scan_queue, scan_thread = _start_batch_scan(
            acc,
            worker,
            source_id,
            spec,
            collected_messages,
            scan_stop_event,
            log=log,
            progress_callback=update_scan_progress,
            complete_callback=mark_scan_complete,
        )

        for (
            chunk_ids,
            fetched_messages,
            fetched_count,
            chunk_total,
            chunk_scanned,
        ) in _iter_scanned_chunks(
            scan_queue,
            stop_event=scan_stop_event,
            should_stop=lambda: bool(get_task(job_id).get("cancelled")),
        ):
            stream_state["scanned"] = chunk_scanned
            stream_state["collected"] = chunk_total
            stream_total = max(stream_total, chunk_total)
            total = 0 if streaming_time else chunk_total
            if not streaming_time and not logged_total:
                log(f"开始处理 {total} 条消息: {source_id} -> {dest_id}")
                logged_total = True
            if not _wait_until_task_active(job_id, log):
                finish_cancelled()
                return

            publish_progress(
                "forwarding" if streaming_time else "preparing",
                total=total,
                fetched=fetched_count,
                scanned=chunk_scanned,
                collected=chunk_total,
                processed=processed,
                success=success,
                failed=failed,
                skipped=skipped,
                current_id=chunk_ids[0] if chunk_ids else None,
            )
            message_map = {
                getattr(item, "id", None): item
                for item in fetched_messages
                if item is not None and not getattr(item, "empty", False)
            }

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
                        group_messages = [
                            collected_messages.get(item.id, item)
                            for item in group_messages
                        ]
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

                    if rate_limiter is not None:
                        rate_limiter.wait(1)
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

        if streaming_time:
            total = stream_total
            stream_state["enabled"] = False
            stream_state["scanning"] = False

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
        final_task = get_task(job_id)
        _queue_batch_notification(
            final_task.get("taskName") or spec.get("task_name"),
            job_id,
            "done" if failed == 0 else "error",
            final_task.get("progress") or {},
        )
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
        final_task = get_task(job_id)
        _queue_batch_notification(
            final_task.get("taskName") or spec.get("task_name"),
            job_id,
            "error",
            final_task.get("progress") or {},
            exc,
        )
    finally:
        scan_stop_event.set()
        if scan_thread is not None and scan_thread.is_alive():
            scan_thread.join(timeout=2)
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
        "rateLimitPerMinute": spec.get("rate_limit_per_minute"),
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


def list_active_tasks():
    with TASKS_LOCK:
        tasks = [
            {
                "jobId": job_id,
                "taskName": task.get("taskName") or "",
                "status": task.get("status") or "",
                "paused": bool(task.get("paused")),
                "createdAt": task.get("createdAt") or "",
                "progress": task.get("progress") or {},
                "stdoutTail": task.get("stdoutTail") or "",
                "stderrTail": task.get("stderrTail") or "",
                "spec": task.get("spec") or {},
            }
            for job_id, task in TASKS.items()
            if task.get("active")
            and task.get("status") in ("running", "paused")
        ]
    return sorted(
        tasks,
        key=lambda item: item.get("createdAt") or "",
        reverse=True,
    )


init_history_db()
