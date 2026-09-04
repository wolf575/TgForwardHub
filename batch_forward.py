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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pyrogram.errors import ChatForwardsRestricted, FileReferenceExpired

from database import DATA_DIR
from bot.handlers.messages import (
    _copy_single_private_media,
    _download_private_media_group,
    _download_private_media_thumbnail,
    _get_private_media_group_messages,
    _get_private_media_payload,
    _send_downloaded_private_media_group,
    _send_downloaded_private_media_sequentially,
)
from bot.handlers.instances import get_acc_instance
from bot.utils.helpers import get_message_type
from bot.workers.message_worker import MessageWorker
from pyrogram_compat import apply_pyrogram_peer_id_compat, normalize_private_channel_ref


apply_pyrogram_peer_id_compat()


CHINA_TZ = ZoneInfo("Asia/Shanghai")
HISTORY_DB = os.path.join(DATA_DIR, "history.db")

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


def _now_iso():
    return datetime.now(CHINA_TZ).isoformat(timespec="seconds")


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
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
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
    if forward_mode not in ("clone", "direct"):
        raise ValueError("forward_mode 只支持 clone 或 direct")
    spec["forward_mode"] = forward_mode

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


def _reupload_batch_media_group(
    worker,
    acc,
    source_id,
    dest_id,
    group_messages,
    cleaned_text,
    text_changed,
):
    group_messages, downloads, work_dir = _download_private_media_group(
        acc,
        source_id,
        group_messages[0],
    )
    try:
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
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
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
):
    anchor = group_messages[0]
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
        elif preserve_source:
            _worker_execute(
                worker,
                "转发媒体组",
                lambda: acc.forward_messages(
                    dest_id,
                    source_id,
                    [item.id for item in group_messages],
                ),
            )
        else:
            _worker_execute(
                worker,
                "复制媒体组",
                lambda: acc.copy_media_group(dest_id, source_id, anchor.id),
            )
        return len(group_messages), False
    except (ChatForwardsRestricted, FileReferenceExpired):
        count = _reupload_batch_media_group(
            worker,
            acc,
            source_id,
            dest_id,
            group_messages,
            cleaned_text,
            text_changed,
        )
        return count, True


def _reupload_batch_single_media(
    worker,
    acc,
    dest_id,
    message,
    cleaned_text,
    text_changed,
):
    work_dir = tempfile.mkdtemp(prefix="tg_forward_batch_media_")
    try:
        file_path = acc.download_media(
            message,
            file_name=os.path.join(work_dir, ""),
        )
        if file_path is None:
            raise RuntimeError(f"消息 {message.id} 下载失败")
        thumb = _download_private_media_thumbnail(
            acc,
            _get_private_media_payload(message),
            work_dir,
            0,
        )
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
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
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
):
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
        elif preserve_source:
            _worker_execute(
                worker,
                "转发单条媒体",
                lambda: acc.forward_messages(
                    dest_id,
                    source_id,
                    message.id,
                ),
            )
        else:
            _worker_execute(
                worker,
                "复制单条媒体",
                lambda: _copy_single_private_media(
                    acc,
                    dest_id,
                    source_id,
                    message,
                ),
            )
        return 1, False
    except (ChatForwardsRestricted, FileReferenceExpired):
        count = _reupload_batch_single_media(
            worker,
            acc,
            dest_id,
            message,
            cleaned_text,
            text_changed,
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
):
    try:
        if text_changed:
            _worker_execute(
                worker,
                "发送修改后的文本",
                lambda: acc.send_message(dest_id, cleaned_text),
            )
        elif preserve_source:
            _worker_execute(
                worker,
                "转发文本消息",
                lambda: acc.forward_messages(dest_id, source_id, message.id),
            )
        else:
            _worker_execute(
                worker,
                "复制文本消息",
                lambda: acc.copy_message(dest_id, source_id, message.id),
            )
        return 1, False
    except (ChatForwardsRestricted, FileReferenceExpired):
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
):
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
    )


def _run_batch_task(job_id, spec):
    log_lines = []

    def log(message):
        line = f"[{_now_iso()}] {message}"
        log_lines.append(line)
        _update_task(job_id, stdoutTail=_tail("\n".join(log_lines)))

    try:
        acc = get_acc_instance()
        if acc is None:
            raise RuntimeError("用户客户端尚未初始化，请先完成 /setup 配置")

        worker = MessageWorker(None, acc, max_retries=3)
        source_id = _resolve_chat(acc, spec.get("source"))
        dest_id = _resolve_chat(acc, spec.get("target"))
        ids = _collect_message_ids(acc, source_id, spec)

        total = len(ids)
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
        preserve_source = str(spec.get("forward_mode", "clone")).lower() != "clone"
        processed = success = failed = skipped = 0
        handled_ids = set()

        for index, message_id in enumerate(ids, start=1):
            task = get_task(job_id)
            if task.get("cancelled"):
                log("任务已取消")
                _update_task(job_id, status="cancelled", exitCode=130)
                _persist_task_history(job_id)
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
                log(f"消息 {message_id} 失败: {type(exc).__name__}: {exc}")

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
            if index % 10 == 0:
                log(f"进度 {processed}/{total}，成功 {success}，失败 {failed}，跳过 {skipped}")
            time.sleep(0.1)

        log(f"任务完成: 成功 {success}，失败 {failed}，跳过 {skipped}")
        _update_task(
            job_id,
            status="done" if failed == 0 else "error",
            exitCode=0 if failed == 0 else 1,
            stderrTail=_tail("\n".join(log_lines)),
        )
        _persist_task_history(job_id)
    except Exception as exc:
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
        return True


def batch_status(job_id):
    task = get_task(job_id)
    if not task:
        return None
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
