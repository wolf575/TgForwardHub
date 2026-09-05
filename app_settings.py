"""Small persistent settings shared by the web UI and workers."""
import json
import os
import threading
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
DATA_DIR = os.environ.get("DATA_DIR", DEFAULT_DATA_DIR)
SETTINGS_DIR = os.path.join(DATA_DIR, "config")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "app_settings.json")
SETTINGS_LOCK = threading.Lock()

TIMEZONE_OPTIONS = (
    ("Asia/Shanghai", "亚洲/上海"),
    ("Asia/Hong_Kong", "亚洲/香港"),
    ("Asia/Taipei", "亚洲/台北"),
    ("Asia/Singapore", "亚洲/新加坡"),
    ("Asia/Tokyo", "亚洲/东京"),
    ("Europe/London", "欧洲/伦敦"),
    ("Europe/Berlin", "欧洲/柏林"),
    ("America/New_York", "美洲/纽约"),
    ("America/Los_Angeles", "美洲/洛杉矶"),
    ("UTC", "协调世界时 UTC"),
)


def _read_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as settings_file:
            data = json.load(settings_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_settings(settings):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    temp_file = SETTINGS_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as settings_file:
        json.dump(settings, settings_file, ensure_ascii=False, indent=2)
    os.replace(temp_file, SETTINGS_FILE)


def get_app_settings():
    with SETTINGS_LOCK:
        settings = _read_settings()
    timezone_name = str(settings.get("timezone") or DEFAULT_TIMEZONE)
    if not is_valid_timezone(timezone_name):
        timezone_name = DEFAULT_TIMEZONE
    return {
        "timezone": timezone_name,
        "timezone_options": [
            {"value": value, "label": label} for value, label in TIMEZONE_OPTIONS
        ],
    }


def is_valid_timezone(timezone_name):
    try:
        ZoneInfo(str(timezone_name or ""))
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def get_app_timezone():
    return ZoneInfo(get_app_settings()["timezone"])


def save_app_timezone(timezone_name):
    timezone_name = str(timezone_name or "").strip()
    if not is_valid_timezone(timezone_name):
        raise ValueError("时区无效")
    with SETTINGS_LOCK:
        settings = _read_settings()
        settings["timezone"] = timezone_name
        _write_settings(settings)
    return get_app_settings()
