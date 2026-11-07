"""Small persistent settings shared by the web UI and workers."""
import json
import os
import threading
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_BATCH_COMPLETION_NOTIFICATIONS = True
DEFAULT_CLIENT_BATCH_NOTIFICATIONS = False
DEFAULT_NOTIFY_CONFIG = {}
MAX_NOTIFY_CONFIG_BYTES = 64 * 1024
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
    batch_completion_notifications = settings.get(
        "batch_completion_notifications_enabled",
        DEFAULT_BATCH_COMPLETION_NOTIFICATIONS,
    )
    if not isinstance(batch_completion_notifications, bool):
        batch_completion_notifications = str(
            batch_completion_notifications
        ).strip().lower() in {"1", "true", "yes", "on"}
    client_batch_notifications = settings.get(
        "client_batch_notifications_enabled",
        DEFAULT_CLIENT_BATCH_NOTIFICATIONS,
    )
    if not isinstance(client_batch_notifications, bool):
        client_batch_notifications = str(
            client_batch_notifications
        ).strip().lower() in {"1", "true", "yes", "on"}
    notify_config = settings.get("notify_config", DEFAULT_NOTIFY_CONFIG)
    if not isinstance(notify_config, dict):
        notify_config = {}
    return {
        "timezone": timezone_name,
        "timezone_options": [
            {"value": value, "label": label} for value, label in TIMEZONE_OPTIONS
        ],
        "batch_completion_notifications_enabled": (
            batch_completion_notifications
        ),
        "client_batch_notifications_enabled": (
            client_batch_notifications
        ),
        "notify_config": dict(notify_config),
    }


def is_valid_timezone(timezone_name):
    try:
        ZoneInfo(str(timezone_name or ""))
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def get_app_timezone():
    return ZoneInfo(get_app_settings()["timezone"])


def batch_completion_notifications_enabled():
    return bool(
        get_app_settings()["batch_completion_notifications_enabled"]
    )


def client_batch_notifications_enabled():
    return bool(
        get_app_settings()["client_batch_notifications_enabled"]
    )


def get_notify_config():
    """Return the web-managed notify.py channel configuration."""
    return dict(get_app_settings().get("notify_config") or {})


def _normalize_notify_config(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("通知配置必须是 JSON 对象")
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_NOTIFY_CONFIG_BYTES:
        raise ValueError("通知配置不能超过 64 KiB")
    return value


def save_app_preferences(
    timezone_name=None,
    batch_completion_notifications_enabled=None,
    client_batch_notifications_enabled=None,
    notify_config=None,
):
    """Save optional app preferences without overwriting unrelated settings."""
    with SETTINGS_LOCK:
        settings = _read_settings()
        if timezone_name is not None:
            timezone_name = str(timezone_name or "").strip()
            if not is_valid_timezone(timezone_name):
                raise ValueError("时区无效")
            settings["timezone"] = timezone_name
        if batch_completion_notifications_enabled is not None:
            settings["batch_completion_notifications_enabled"] = bool(
                batch_completion_notifications_enabled
            )
        if client_batch_notifications_enabled is not None:
            settings["client_batch_notifications_enabled"] = bool(
                client_batch_notifications_enabled
            )
        if notify_config is not None:
            settings["notify_config"] = _normalize_notify_config(
                notify_config
            )
        _write_settings(settings)
    return get_app_settings()


def save_app_timezone(timezone_name):
    return save_app_preferences(timezone_name=timezone_name)
