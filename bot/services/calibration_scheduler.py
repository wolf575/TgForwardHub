"""Background scheduler for automatic magnet filename calibration."""

import logging
import os
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_thread = None
_thread_lock = threading.Lock()


def _helper_path():
    container_path = "/app/calibrate_helper.py"
    if os.path.exists(container_path):
        return container_path
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "calibrate_helper.py")


def _process_task(task):
    from database import update_calibration_task

    info_hash = (task.get("magnet_hash") or "").strip()
    if not info_hash or info_hash == "unknown":
        update_calibration_task(
            task["id"],
            "failed",
            error_message="缺少有效的 magnet hash",
            next_retry_seconds=None,
        )
        return

    try:
        result = subprocess.run(
            [sys.executable, _helper_path(), info_hash],
            capture_output=True,
            text=True,
            timeout=30,
        )
        filename = result.stdout.strip()
        if result.returncode == 0 and filename:
            update_calibration_task(task["id"], "success")
        else:
            message = result.stderr.strip() or "校准未返回文件名"
            update_calibration_task(
                task["id"],
                "failed",
                error_message=message,
                next_retry_seconds=3600,
            )
    except Exception as exc:
        update_calibration_task(
            task["id"],
            "failed",
            error_message=str(exc),
            next_retry_seconds=3600,
        )


def _run(interval):
    while not _stop_event.is_set():
        try:
            from database import get_pending_calibration_tasks

            tasks = get_pending_calibration_tasks(limit=5)
            if tasks:
                logger.info("自动校准调度器发现 %s 个待处理任务", len(tasks))
            for task in tasks:
                if _stop_event.is_set():
                    break
                _process_task(task)
        except Exception:
            logger.exception("自动校准调度器执行失败")

        _stop_event.wait(interval)


def start_scheduler(interval=60):
    global _thread

    with _thread_lock:
        if _thread and _thread.is_alive():
            return _thread

        _stop_event.clear()
        _thread = threading.Thread(
            target=_run,
            args=(interval,),
            name="calibration-scheduler",
            daemon=True,
        )
        _thread.start()
        return _thread


def stop_scheduler():
    global _thread

    _stop_event.set()
    with _thread_lock:
        thread = _thread
        _thread = None

    if thread and thread.is_alive():
        thread.join(timeout=3)

