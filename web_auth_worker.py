"""Isolated Telegram user authorization worker.

Run by :func:`web_setup._spawn_worker`.  Keeping this work in a separate
process mirrors Save-Restricted-Bot's original process model and keeps the
Flask request short enough for Cloudflare.
"""

import sys
import traceback
from typing import Any, Dict


from web_setup import (
    SESSION_DIR,
    _read_job,
    _remove_session_files,
    _update_job,
)


def _friendly_pyrogram_error(exc: Exception) -> str:
    name = exc.__class__.__name__
    message = str(exc)

    if name == "TimeoutError":
        return "登录流程超时，请检查服务器到 Telegram 的网络连通性后重试"
    if name == "PhoneCodeInvalid":
        return "验证码不正确，请检查后重新输入"
    if name == "PhoneCodeExpired":
        return "验证码已过期，请重新获取验证码"
    if name == "PhoneCodeEmpty":
        return "验证码为空"
    if name == "SessionPasswordNeeded":
        return "需要输入两步验证密码"
    if name == "FloodWait":
        wait = ""
        try:
            wait = str(getattr(exc, "value", "") or getattr(exc, "seconds", "") or "")
        except Exception:
            pass
        return f"Telegram 触发限流，请等待 {wait} 秒后重试"
    if name == "ApiIdInvalid":
        return "API ID 无效"
    if name == "PhoneNumberInvalid":
        return "手机号格式无效，请使用带国家代码的格式，例如 +8613800138000"
    if name == "PhoneNumberBanned":
        return "该手机号已被 Telegram 限制"
    if name == "PasswordHashInvalid":
        return "两步验证密码不正确"

    if "AUTH_KEY_UNREGISTERED" in message or "api_id" in message.lower():
        return "API 凭据错误，请检查 API ID 和 API Hash"
    if "PHONE_NUMBER_INVALID" in message:
        return "手机号格式无效，请使用带国家代码的格式，例如 +8613800138000"
    if "PHONE_CODE_INVALID" in message:
        return "验证码不正确"
    if "PHONE_CODE_EXPIRED" in message:
        return "验证码已过期"
    if "SESSION_PASSWORD_NEEDED" in message:
        return "需要输入两步验证密码"
    if "FLOOD_WAIT" in message:
        return "请求过于频繁，请稍后重试"

    return f"登录失败: {message or name}"


def _load_required_job(setup_id: str) -> Dict[str, Any]:
    job = _read_job(setup_id)
    if not job:
        raise RuntimeError("登录流程不存在或已过期，请重新开始")
    return job


def _new_client(job: Dict[str, Any]) -> Any:
    from pyrogram import Client

    return Client(
        job["session_name"],
        api_id=int(job["api_id"]),
        api_hash=job["api_hash"],
        phone_number=job.get("phone_number"),
        workdir=SESSION_DIR,
        in_memory=False,
    )


def _disconnect(client: Any) -> None:
    if client is None:
        return
    try:
        client.disconnect()
    except Exception:
        pass


def run_start(setup_id: str) -> int:
    job = _load_required_job(setup_id)
    _update_job(setup_id, status="running", message="正在连接 Telegram 并发送验证码")

    client = None
    try:
        client = _new_client(job)
        client.connect()
        sent_code = client.send_code(job["phone_number"])
        phone_code_hash = getattr(sent_code, "phone_code_hash", None)
        if not phone_code_hash:
            raise RuntimeError("Telegram 未返回验证码哈希")
        _update_job(
            setup_id,
            stage="code",
            status="sent",
            phone_code_hash=phone_code_hash,
            message=None,
            error=None,
        )
        return 0
    except Exception as exc:
        _update_job(
            setup_id,
            status="error",
            stage="code",
            error=_friendly_pyrogram_error(exc),
        )
        _remove_session_files(job["session_name"])
        print(
            f"[web-auth] start failed for {setup_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        traceback.print_exc()
        return 1
    finally:
        _disconnect(client)


def run_code(setup_id: str) -> int:
    job = _load_required_job(setup_id)
    code = str(job.get("login_code") or "").strip()
    if not code:
        _update_job(setup_id, status="error", error="验证码不能为空")
        return 1

    _update_job(setup_id, status="running", message="正在验证验证码")
    client = None
    try:
        from pyrogram.errors import SessionPasswordNeeded

        client = _new_client(job)
        client.connect()
        try:
            client.sign_in(
                job["phone_number"],
                job["phone_code_hash"],
                code,
            )
        except SessionPasswordNeeded:
            _update_job(
                setup_id,
                stage="password",
                status="ready",
                message="账号已开启两步验证，请输入两步验证密码",
                error=None,
            )
            return 0

        session_string = client.export_session_string()
        _update_job(
            setup_id,
            stage="done",
            status="done",
            session_string=session_string,
            message="Session String 已生成，正在写入配置",
            error=None,
        )
        return 0
    except Exception as exc:
        _update_job(
            setup_id,
            status="error",
            error=_friendly_pyrogram_error(exc),
        )
        print(
            f"[web-auth] code failed for {setup_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        traceback.print_exc()
        return 1
    finally:
        _disconnect(client)


def run_password(setup_id: str) -> int:
    job = _load_required_job(setup_id)
    password = str(job.get("two_factor_password") or "")
    if not password:
        _update_job(setup_id, status="error", error="两步验证密码不能为空")
        return 1

    _update_job(setup_id, status="running", message="正在完成两步验证")
    client = None
    try:
        client = _new_client(job)
        client.connect()
        client.check_password(password)
        session_string = client.export_session_string()
        _update_job(
            setup_id,
            stage="done",
            status="done",
            session_string=session_string,
            message="Session String 已生成，正在写入配置",
            error=None,
        )
        return 0
    except Exception as exc:
        _update_job(
            setup_id,
            status="error",
            error=_friendly_pyrogram_error(exc),
        )
        print(
            f"[web-auth] password failed for {setup_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        traceback.print_exc()
        return 1
    finally:
        _disconnect(client)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: web_auth_worker.py SETUP_ID ACTION", file=sys.stderr)
        return 2

    setup_id = sys.argv[1]
    action = sys.argv[2]
    if action == "start":
        return run_start(setup_id)
    if action == "code":
        return run_code(setup_id)
    if action == "password":
        return run_password(setup_id)
    print(f"unknown action: {action}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
