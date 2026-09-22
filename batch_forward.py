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
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from pyrogram import raw
from pyrogram.errors import (
    ChatForwardsRestricted,
    FileReferenceExpired,
    FloodWait,
    InternalServerError,
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


def _connect():
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_history_db():
    with _connect() as conn:
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
            WHERE status = 'running'
            """
        )


def _now_iso():
    return datetime.now(get_app_timezone()).isoformat(timespec="seconds")


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
    with _connect() as conn:
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
                record.get("id"),
                record.get("taskName") or "",
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
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM history ORDER BY createdAt DESC").fetchall()
        return [_record_to_dict(row) for row in rows]


def get_history_record(job_id):
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM history
            WHERE id = ? OR jobId = ?
            ORDER BY createdAt DESC
            LIMIT 1
            """,
            (job_id, job_id),
        ).fetchone()
    return _record_to_dict(row) if row else None


def clear_history():
    with _connect() as conn:
        conn.execute("DELETE FROM history")


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
    pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
    return bool(pattern.search(text or ""))


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
    for term in terms:
        text = re.sub(re.escape(term), "", text, flags=re.IGNORECASE)
    for pattern in patterns:
        text = pattern.sub("", text)
    return text


def _parse_timestamp(value):
    value = str(value or "").strip()
    if not value:
        return None
    if re.fullmatch(r"\d{10}", value):
        return int(value)
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=get_app_timezone())
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


def _collect_message_ids(acc, source_id, spec):
    range_type = spec.get("range_type", "id")
    start = spec.get("start")
    end = spec.get("end")
    reverse = bool(spec.get("reverse"))

    if range_type == "time":
        start_ts = _parse_timestamp(start)
        end_ts = _parse_timestamp(end)
        if start_ts is None or end_ts is None:
            raise ValueError("时间范围格式不正确")
        if start_ts > end_ts:
            start_ts, end_ts = end_ts, start_ts

        ids = []
        offset_date = datetime.fromtimestamp(end_ts, tz=timezone.utc)
        for message in acc.iter_history(source_id, offset_date=offset_date, limit=1000):
            ts = message.date.timestamp()
            if ts < start_ts:
                break
            ids.append(message.id)
        if reverse:
            ids.reverse()
        return ids

    start_id = int(start)
    end_id = int(end)
    if start_id > end_id:
        start_id, end_id = end_id, start_id
    ids = list(range(start_id, end_id + 1))
    if reverse:
        ids.reverse()
    return ids


def _validate_task_spec(spec):
    if not spec.get("source") or not spec.get("target"):
        raise ValueError("source 和 target 不能为空")

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
        if _parse_timestamp(spec.get("end")) is None:
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
        "exclude_terms": _parse_terms(spec.get("exclude_keywords")),
        "exclude_patterns": _compile_regex_patterns(
            spec.get("exclude_regex"),
            "排除正则",
        ),
        "remove_terms": _parse_terms(spec.get("remove_keywords")),
        "remove_patterns": _compile_regex_patterns(
            spec.get("remove_regex"),
            "删除正则",
        ),
    }


def _group_text(group_messages):
    for message in group_messages:
        caption = getattr(message, "caption", None)
        if caption:
            return caption
        text = getattr(message, "text", None)
        if text:
            return text
    return ""


def _worker_execute(worker, name, operation):
    """Run a Pyrogram operation through the worker's FloodWait handling."""
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
):
    """Copy one batch unit into the relay chat using the Bot identity."""
    source_ref = _bot_source_ref(source_id, group_messages, source_username)
    if len(group_messages) > 1:
        anchor = group_messages[0]
        kwargs = {"captions": [cleaned_text]} if text_changed else {}
        result = bot.copy_media_group(
            relay_id,
            source_ref,
            anchor.id,
            **kwargs,
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
):
    """Relay a restricted cached-copy through Bot, then hidden-forward as user."""
    try:
        source_ref = _bot_source_ref(source_id, group_messages, source_username)
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
                source_username=source_username,
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
            f"开始下载受限媒体 {item_id}，第 {attempt}/{attempts} 次",
            log,
        )
        try:
            file_path = acc.download_media(item, file_name=file_name)
            if file_path is None:
                last_error = RuntimeError(
                    f"媒体 {item_id} 下载失败：Telegram 未返回文件数据"
                )
                _emit_log(
                    f"受限媒体 {item_id} 第 {attempt}/{attempts} 次下载返回空结果，"
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
                            f"受限媒体 {item_id} 空文件删除失败: {exc}",
                            log,
                            "warning",
                        )
                last_error = RuntimeError(
                    f"媒体 {item_id} 下载失败：Telegram 返回了 0 字节文件"
                )
                _emit_log(
                    f"受限媒体 {item_id} 第 {attempt}/{attempts} 次下载得到 "
                    "0 字节文件，将稍后重试",
                    log,
                    "warning",
                )
                if attempt < attempts:
                    time.sleep(1.5 * attempt)
                    continue
                break
            _emit_log(
                f"受限媒体 {item_id} 下载完成: {file_path}",
                log,
            )
            return file_path
        except FloodWait as exc:
            last_error = exc
            wait = int(getattr(exc, "value", 0) or 0) + 1
            _emit_log(
                f"受限媒体 {item_id} 下载遇到 FloodWait，等待 {wait} 秒",
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
                f"受限媒体 {item_id} 下载失败: {type(exc).__name__}: {exc}",
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
            f"开始下载受限媒体组 {item_ids}，第 {attempt}/{attempts} 次",
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
                "受限媒体组下载完成，共 "
                f"{len(downloads)}/{len(group_messages)} 项: {item_ids}",
                log,
            )
            return result
        except FloodWait as exc:
            last_error = exc
            wait = int(getattr(exc, "value", 0) or 0) + 1
            _emit_log(
                f"受限媒体组 {item_ids} 下载遇到 FloodWait，等待 {wait} 秒",
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
                "受限媒体组下载失败 "
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
):
    group_messages, downloads, work_dir = _download_batch_media_group_with_retry(
        acc,
        source_id,
        group_messages,
        log,
    )
    try:
        _emit_log(
            f"开始上传受限媒体组 {[item.id for item in group_messages]}",
            log,
        )
        _worker_execute(
            worker,
            "上传受限媒体组",
            lambda: _send_downloaded_private_media_group(
                acc,
                dest_id,
                group_messages,
                downloads,
                caption_override=cleaned_text if text_changed else None,
                caption_entities_override=None if text_changed else None,
            ),
        )
        _emit_log(
            f"受限媒体组 {[item.id for item in group_messages]} 上传完成",
            log,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        _emit_log(
            f"已清理受限媒体组临时目录: {work_dir}",
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
):
    anchor = group_messages[0]

    if cache_send:
        try:
            _emit_log(
                f"媒体组 {anchor.id} 使用用户客户端缓存复制: "
                f"{source_id} -> {dest_id}，RPC=copy_media_group",
                log,
            )
            copy_kwargs = {"captions": [cleaned_text]} if text_changed else {}
            _worker_execute(
                worker,
                "复制媒体组（缓存发送）",
                lambda: acc.copy_media_group(
                    dest_id,
                    source_id,
                    anchor.id,
                    **copy_kwargs,
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
            )
            return len(group_messages), True

    try:
        if text_changed:
            _worker_execute(
                worker,
                "复制媒体组并修改 caption",
                lambda: acc.copy_media_group(
                    dest_id,
                    source_id,
                    anchor.id,
                    captions=[cleaned_text],
                ),
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
):
    work_dir = tempfile.mkdtemp(prefix="tg_forward_batch_media_")
    try:
        file_path = _download_batch_media_with_retry(
            acc,
            message,
            os.path.join(work_dir, ""),
            log,
        )
        _emit_log(f"开始下载受限媒体 {message.id} 的缩略图", log)
        thumb = _download_private_media_thumbnail(
            acc,
            _get_private_media_payload(message),
            work_dir,
            0,
        )
        if thumb:
            _emit_log(f"受限媒体 {message.id} 缩略图下载完成: {thumb}", log)
        else:
            _emit_log(f"受限媒体 {message.id} 无缩略图或缩略图下载失败", log)
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
):
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
    )


def _reupload_batch_unit(
    worker,
    acc,
    dest_id,
    group_messages,
    cleaned_text,
    text_changed,
    log=None,
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
        ),
        True,
    )


def _run_batch_task(job_id, spec):
    log_lines = []

    def log(message, level="info"):
        line = f"[{_now_iso()}] {message}"
        log_lines.append(line)
        getattr(logger, level, logger.info)(
            "[batch:%s] %s",
            job_id,
            message,
        )
        _update_task(job_id, stdoutTail=_tail("\n".join(log_lines)))
        _persist_task_history(job_id)

    def finish_cancelled():
        log("任务已取消")
        _update_task(
            job_id,
            status="cancelled",
            exitCode=130,
            stderrTail=_tail("\n".join(log_lines)),
        )
        _persist_task_history(job_id)

    try:
        acc = get_acc_instance()
        if acc is None:
            raise RuntimeError("用户客户端尚未初始化，请先完成 /setup 配置")

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
        ids = _collect_message_ids(acc, source_id, spec)

        total = len(ids)
        if get_task(job_id).get("cancelled"):
            finish_cancelled()
            return
        _update_task(
            job_id,
            status="running",
            progress={"total": total, "processed": 0, "success": 0, "failed": 0, "skipped": 0},
        )
        log(f"开始处理 {total} 条消息: {source_id} -> {dest_id}")

        rules = _filter_rule_set(spec)
        exclude_terms = rules["exclude_terms"]
        exclude_patterns = rules["exclude_patterns"]
        remove_terms = rules["remove_terms"]
        remove_patterns = rules["remove_patterns"]
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
        restricted_source_ids = set()

        for index, message_id in enumerate(ids, start=1):
            task = get_task(job_id)
            if task.get("cancelled"):
                finish_cancelled()
                return

            unit_count = 1
            group_messages = None
            try:
                if message_id in handled_ids:
                    continue

                message = acc.get_messages(source_id, message_id)
                if not message or getattr(message, "empty", False):
                    skipped += 1
                    processed += 1
                    continue

                group_messages = _get_private_media_group_messages(
                    acc,
                    source_id,
                    message,
                )
                group_ids = [item.id for item in group_messages]
                handled_ids.update(group_ids)
                unit_count = len(group_messages)
                text = _group_text(group_messages)

                if _matches_exclude(text, exclude_terms) or _matches_exclude_regex(
                    text,
                    exclude_patterns,
                ):
                    skipped += unit_count
                    processed += unit_count
                    continue

                cleaned = _remove_matches(text, remove_terms, remove_patterns)
                text_changed = cleaned != text
                if unit_count == 1 and get_message_type(
                    group_messages[0]
                ) in ("Text", None) and not cleaned.strip():
                    skipped += unit_count
                    processed += unit_count
                    continue

                sent_count, used_fallback = _forward_batch_unit(
                    worker,
                    acc,
                    source_id,
                    dest_id,
                    group_messages,
                    cleaned,
                    text_changed,
                    preserve_source,
                    log,
                    restricted_source_ids,
                    cache_send=cache_send,
                    bot=bot,
                    relay_chat_id=relay_chat_id,
                    source_username=source_username,
                )
                success += sent_count
                processed += sent_count
                if used_fallback:
                    fallback_label = "媒体组" if unit_count > 1 else "消息"
                    log(
                        f"消息 {message_id} 受限，已通过用户客户端下载后重传"
                        f"（{fallback_label}，共 {sent_count} 项）"
                    )
            except Exception as exc:
                unit_count = len(group_messages) if group_messages else 1
                failed += unit_count
                processed += unit_count
                log(
                    f"消息 {message_id} 失败: {type(exc).__name__}: {exc}",
                    level="error",
                )

            _update_task(
                job_id,
                progress={
                    "total": total,
                    "processed": processed,
                    "success": success,
                    "failed": failed,
                    "skipped": skipped,
                },
            )
            _persist_task_history(job_id)
            if index % 10 == 0:
                log(f"进度 {processed}/{total}，成功 {success}，失败 {failed}，跳过 {skipped}")
            time.sleep(0.1)

        if get_task(job_id).get("cancelled"):
            finish_cancelled()
            return

        log(f"任务完成: 成功 {success}，失败 {failed}，跳过 {skipped}")
        _update_task(
            job_id,
            status="done" if failed == 0 else "error",
            exitCode=0 if failed == 0 else 1,
            stderrTail=_tail("\n".join(log_lines)),
        )
        _persist_task_history(job_id)
    except Exception as exc:
        if get_task(job_id).get("cancelled"):
            finish_cancelled()
            return
        log(f"任务异常终止: {type(exc).__name__}: {exc}")
        _update_task(
            job_id,
            status="error",
            exitCode=1,
            stderrTail=_tail("\n".join(log_lines)),
        )
        _persist_task_history(job_id)


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
        "exitCode": None,
        "cancelled": False,
        "progress": {},
        "stdoutTail": "",
        "stderrTail": "",
        "spec": spec,
        "taskName": spec.get("task_name") or "",
        "sourceId": str(spec.get("source") or ""),
        "targetId": str(spec.get("target") or ""),
        "createdAt": _now_iso(),
        "state": state,
    }
    with TASKS_LOCK:
        TASKS[job_id] = task

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

    threading.Thread(target=_run_batch_task, args=(job_id, spec), daemon=True).start()
    return job_id


def cancel_batch_task(job_id):
    with TASKS_LOCK:
        task = TASKS.get(job_id)
        if not task:
            return False
        task["cancelled"] = True
        task["status"] = "cancelled"
        task["exitCode"] = 130
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
            "progress": history.get("progress") or {},
            "stdoutTail": history.get("stdoutTail") or "",
            "stderrTail": history.get("stderrTail") or "",
            "spec": history.get("task_spec") or {},
        }
    return {
        "jobId": job_id,
        "status": task.get("status"),
        "exitCode": task.get("exitCode"),
        "progress": task.get("progress") or {},
        "stdoutTail": task.get("stdoutTail") or "",
        "stderrTail": task.get("stderrTail") or "",
        "spec": task.get("spec") or {},
    }


init_history_db()
