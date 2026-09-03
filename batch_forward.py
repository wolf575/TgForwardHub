"""Batch forwarding service for the merged web UI.

Keeps the A-style task form semantics (source, target, id/time range, keyword
filters, reverse order) but performs forwarding directly with the B project's
Pyrogram clients.
"""
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import DATA_DIR
from bot.handlers.instances import get_acc_instance
from bot.workers.message_worker import MessageWorker


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


def _strip_trailing_blocks(text, terms):
    if not text or not terms:
        return text
    pattern = re.compile(
        r"\n\n(?:%s).*" % "|".join(re.escape(term) for term in terms),
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub("", text)


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
    ref = str(ref or "").strip()
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

        exclude = _parse_terms(spec.get("exclude_keywords"))
        remove = _parse_terms(spec.get("remove_keywords"))
        preserve_source = str(spec.get("forward_mode", "clone")).lower() != "clone"
        processed = success = failed = skipped = 0

        for index, message_id in enumerate(ids, start=1):
            task = get_task(job_id)
            if task.get("cancelled"):
                log("任务已取消")
                _update_task(job_id, status="cancelled", exitCode=130)
                _persist_task_history(job_id)
                return

            try:
                message = acc.get_messages(source_id, message_id)
                if not message or getattr(message, "empty", False):
                    skipped += 1
                else:
                    text = message.text or message.caption or ""
                    if _matches_exclude(text, exclude):
                        skipped += 1
                    else:
                        cleaned = _strip_trailing_blocks(text, remove)
                        if cleaned != text:
                            worker._forward_with_modified_text(message, dest_id, cleaned, preserve_source)
                        elif preserve_source:
                            worker._forward_with_source(message, dest_id)
                        else:
                            worker._copy_without_source(message, dest_id)
                        success += 1
            except Exception as exc:
                failed += 1
                log(f"消息 {message_id} 失败: {type(exc).__name__}: {exc}")

            processed += 1
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
    if not spec.get("source") or not spec.get("target"):
        raise ValueError("source 和 target 不能为空")

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
        "removeKeywords": spec.get("remove_keywords") or "",
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
