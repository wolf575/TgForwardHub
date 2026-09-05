"""Web setup helpers for the merged web service.

The Telegram user authorization is intentionally run in a separate Python
process.  Pyrogram's synchronous wrapper is easiest to drive from a process's
main thread, while the merged service runs the Telegram bot on its main
thread.  Running temporary auth clients in Flask worker threads can leave a
request hanging until Cloudflare returns HTTP 503.

This module therefore only creates and monitors small JSON job files.  The
actual Telegram calls happen in :file:`web_auth_worker.py`.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Dict, Optional


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
CONFIG_DIR = os.path.join(DATA_DIR, "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
SESSION_DIR = os.path.join(DATA_DIR, "auth_sessions")
AUTH_JOBS_DIR = os.path.join(DATA_DIR, "auth_jobs")
WORKER_SCRIPT = os.path.join(BASE_DIR, "web_auth_worker.py")

_AUTH_WORKER_TIMEOUT = 660
_finalize_lock = threading.Lock()
_job_lock = threading.Lock()
_finalize_scheduled: set = set()
_SETUP_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _ensure_dirs() -> None:
    for path in (CONFIG_DIR, SESSION_DIR, AUTH_JOBS_DIR):
        os.makedirs(path, exist_ok=True)


def _job_path(setup_id: str) -> str:
    if not _SETUP_ID_RE.fullmatch(setup_id or ""):
        raise ValueError("invalid setup id")
    return os.path.join(AUTH_JOBS_DIR, f"{setup_id}.json")


def _read_job(setup_id: str) -> Optional[Dict[str, Any]]:
    _ensure_dirs()
    path = _job_path(setup_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _write_job(setup_id: str, data: Dict[str, Any]) -> None:
    """Write a sensitive auth job with owner-only permissions."""
    _ensure_dirs()
    path = _job_path(setup_id)
    temp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    try:
        with os.fdopen(os.open(temp_path, flags, 0o600), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _update_job(setup_id: str, **fields: Any) -> Dict[str, Any]:
    """Merge fields into a job file and persist it."""
    with _job_lock:
        job = _read_job(setup_id) or {"setup_id": setup_id}
        job.update(fields)
        job["updated_at"] = time.time()
        _write_job(setup_id, job)
    return job


def _remove_session_files(session_name: str) -> None:
    for suffix in ("", "-journal"):
        path = os.path.join(SESSION_DIR, f"{session_name}.session{suffix}")
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def _monitor_worker(
    setup_id: str,
    process: subprocess.Popen,
) -> None:
    """Kill an auth subprocess if Telegram does not finish in a bounded time."""
    try:
        process.wait(timeout=_AUTH_WORKER_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        _update_job(
            setup_id,
            status="error",
            error="Telegram 登录流程超时，请稍后重试",
        )


def _spawn_worker(setup_id: str, action: str) -> Optional[Dict[str, Any]]:
    """Start an auth subprocess and return immediately."""
    worker_env = os.environ.copy()
    worker_env["TG_FORWARD_HUB_AUTH_ACTION"] = action

    popen_kwargs: Dict[str, Any] = {
        "stdout": sys.stdout,
        "stderr": sys.stderr,
        "env": worker_env,
    }
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(
            [sys.executable, WORKER_SCRIPT, setup_id, action],
            **popen_kwargs,
        )
    except Exception as exc:
        _update_job(setup_id, status="error", error=f"无法启动 Telegram 鉴权进程: {exc}")
        return _read_job(setup_id)

    threading.Thread(
        target=_monitor_worker,
        args=(setup_id, process),
        name=f"WebAuthMonitor-{setup_id[:8]}",
        daemon=True,
    ).start()
    return None


def _read_current_config() -> Dict[str, Any]:
    _ensure_dirs()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _env_value(key: str) -> Optional[str]:
    value = os.environ.get(key)
    if value:
        value = value.strip()
        return value or None
    return None


def load_visible_config() -> Dict[str, Any]:
    """Return configuration values suitable for the setup page."""
    current = _read_current_config()
    token = current.get("TOKEN") or _env_value("TOKEN") or ""
    api_id = current.get("ID") or _env_value("ID") or ""
    api_hash = current.get("HASH") or _env_value("HASH") or ""
    session_string = current.get("STRING") or _env_value("STRING") or ""

    return {
        "token": token,
        "api_id": api_id,
        "api_hash": api_hash,
        "has_session": bool(session_string),
        "session_masked": _mask_session(session_string),
    }


def save_configuration(
    token: str,
    api_id: str,
    api_hash: str,
    session_string: Optional[str] = None,
    preserve_existing_session: bool = False,
) -> Dict[str, Any]:
    """Persist bot credentials to the durable web configuration file."""
    _ensure_dirs()

    token = (token or "").strip()
    api_id = (api_id or "").strip()
    api_hash = (api_hash or "").strip()
    session_string = (session_string or "").strip()

    current = _read_current_config()
    existing_session = current.get("STRING") or _env_value("STRING") or ""

    if preserve_existing_session and not session_string and existing_session:
        session_string = existing_session

    config_data = {
        "TOKEN": token,
        "ID": api_id,
        "HASH": api_hash,
        "STRING": session_string or None,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)

    return {
        "token": token,
        "api_id": api_id,
        "api_hash": api_hash,
        "has_session": bool(session_string),
        "session_masked": _mask_session(session_string),
    }


def _mask_session(session_string: str) -> str:
    if not session_string:
        return ""
    if len(session_string) <= 12:
        return "*" * min(len(session_string), 4)
    return session_string[:4] + "..." + session_string[-4:]


def _request_client_restart() -> None:
    """Ask the running bot/user clients to stop so the background loop reloads config."""
    try:
        from bot.handlers.instances import stop_and_clear_instances
        stop_and_clear_instances()
    except Exception:
        pass


def _finalize_finished_job(setup_id: str) -> Optional[Dict[str, Any]]:
    """Persist an exported session and restart clients exactly once."""
    with _finalize_lock:
        if setup_id in _finalize_scheduled:
            return _read_job(setup_id)
        _finalize_scheduled.add(setup_id)

    job = _read_job(setup_id)
    if not job or job.get("status") != "done" or not job.get("session_string"):
        return None

    saved = save_configuration(
        job.get("token", ""),
        job.get("api_id", ""),
        job.get("api_hash", ""),
        session_string=job["session_string"],
        preserve_existing_session=False,
    )
    _update_job(
        setup_id,
        saved=saved,
        restart_queued=True,
        message="Session String 已自动生成并写入配置",
    )
    _request_client_restart()

    session_name = job.get("session_name")
    if session_name:
        _remove_session_files(session_name)
    try:
        os.remove(_job_path(setup_id))
    except OSError:
        pass
    return saved


def get_setup_status(setup_id: str) -> Dict[str, Any]:
    """Return a JSON-safe snapshot of an auth flow for frontend polling."""
    job = _read_job(setup_id)
    if not job:
        return {"setup_id": setup_id, "stage": "idle", "status": "missing"}

    saved = None
    if job.get("status") == "done" and job.get("session_string"):
        saved = _finalize_finished_job(setup_id)

    return {
        "setup_id": setup_id,
        "stage": job.get("stage"),
        "status": job.get("status"),
        "phone_number": job.get("phone_number"),
        "message": job.get("message"),
        "error": job.get("error"),
        "session_string": job.get("session_string"),
        "saved": saved or job.get("saved"),
    }


def start_session_auth(
    token: str,
    api_id: str,
    api_hash: str,
    phone_number: str,
) -> Dict[str, Any]:
    """Request a Telegram login code through an isolated subprocess."""
    _ensure_dirs()

    try:
        api_id_int = int(str(api_id).strip())
    except (TypeError, ValueError):
        return {"error": "API ID 必须是纯数字"}

    phone_number = (phone_number or "").strip()
    api_hash = (api_hash or "").strip()
    token = (token or "").strip()

    if not phone_number:
        return {"error": "手机号不能为空"}
    if not api_hash:
        return {"error": "API Hash 不能为空"}
    if not token:
        return {"error": "Bot Token 不能为空"}

    setup_id = uuid.uuid4().hex
    session_name = f"web_auth_{setup_id}"
    job = {
        "setup_id": setup_id,
        "session_name": session_name,
        "phone_number": phone_number,
        "token": token,
        "api_id": str(api_id_int),
        "api_hash": api_hash,
        "stage": "code",
        "status": "queued",
        "message": "正在启动 Telegram 登录流程",
        "error": None,
        "session_string": None,
        "saved": None,
        "phone_code_hash": None,
        "restart_queued": False,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _write_job(setup_id, job)

    spawn_error = _spawn_worker(setup_id, "start")
    if spawn_error:
        return {"error": spawn_error.get("error", "无法启动 Telegram 鉴权进程")}

    return {
        "setup_id": setup_id,
        "stage": "pending",
        "phone_number": phone_number,
    }


def submit_code(setup_id: str, code: str) -> Dict[str, Any]:
    """Queue a Telegram login code for the already-running auth worker."""
    job = _read_job(setup_id)
    if not job:
        return {"error": "登录流程不存在或已过期，请重新开始"}

    code = (code or "").strip()
    if not code:
        return {
            "stage": "code",
            "setup_id": setup_id,
            "error": "验证码不能为空",
        }

    allowed_statuses = {"sent"}
    if job.get("status") not in allowed_statuses:
        return {"error": "验证码尚未发送或登录流程已过期，请重新开始"}

    _update_job(
        setup_id,
        status="queued",
        error=None,
        message="正在验证验证码",
        login_code=code,
    )

    return {
        "setup_id": setup_id,
        "stage": "pending",
    }


def submit_password(setup_id: str, password: str) -> Dict[str, Any]:
    """Queue a two-factor password for the already-running auth worker."""
    job = _read_job(setup_id)
    if not job:
        return {"error": "登录流程不存在或已过期，请重新开始"}

    password = password or ""
    if not password.strip():
        return {
            "stage": "password",
            "setup_id": setup_id,
            "error": "两步验证密码不能为空",
        }

    allowed_statuses = {"ready", "error"}
    if job.get("status") not in allowed_statuses:
        return {"error": "两步验证流程不存在或已过期，请重新开始"}

    _update_job(
        setup_id,
        status="queued",
        error=None,
        message="正在完成两步验证",
        two_factor_password=password,
    )

    return {
        "setup_id": setup_id,
        "stage": "pending",
    }
