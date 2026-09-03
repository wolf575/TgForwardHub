"""Calibration manager used by the record mode.

The upstream repository did not ship a complete calibration implementation.
This module provides the expected singleton API and queues newly saved magnet
notes when automatic calibration is enabled.
"""

import logging
import re
import threading

logger = logging.getLogger(__name__)

_manager = None
_lock = threading.Lock()


class CalibrationManager:
    def __init__(self):
        self._config = self._load_config()

    def _load_config(self):
        try:
            from database import get_calibration_config

            config = get_calibration_config()
            if config:
                return config
        except Exception:
            logger.exception("无法读取自动校准配置")

        return {
            "enabled": 0,
            "filter_mode": "empty_only",
            "first_delay": 600,
            "retry_delay_1": 3600,
            "retry_delay_2": 14400,
            "retry_delay_3": 28800,
            "max_retries": 3,
            "concurrent_limit": 5,
            "timeout_per_magnet": 30,
            "batch_timeout": 300,
        }

    def reload_config(self):
        self._config = self._load_config()
        return self._config

    def is_enabled(self):
        return bool(self._config.get("enabled", 0))

    def add_note_to_calibration_queue(self, note_id):
        if not note_id:
            return

        try:
            from database import add_calibration_task, get_note_by_id

            note = get_note_by_id(note_id)
            if not note:
                logger.warning("校准任务找不到笔记 note_id=%s", note_id)
                return

            magnet_link = note.get("magnet_link") or ""
            match = re.search(
                r"xt=urn:btih:([a-zA-Z0-9]+)",
                magnet_link or "",
                re.IGNORECASE,
            )
            magnet_hash = match.group(1) if match else (magnet_link[:40] or "unknown")
            delay = int(self._config.get("first_delay", 600) or 600)
            add_calibration_task(note_id, magnet_hash, delay_seconds=delay)
        except Exception:
            logger.exception("加入校准队列失败 note_id=%s", note_id)


def get_calibration_manager():
    global _manager

    if _manager is None:
        with _lock:
            if _manager is None:
                _manager = CalibrationManager()
    return _manager

