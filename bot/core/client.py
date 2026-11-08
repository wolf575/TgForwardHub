"""
客户端初始化模块
职责：初始化Bot客户端和User客户端
"""
import asyncio
import functools
import inspect
import os
import pyrogram
from pyrogram import Client
from bot.utils.logger import get_logger
from config import load_config, getenv
from pyrogram_compat import apply_pyrogram_peer_id_compat


apply_pyrogram_peer_id_compat()

logger = get_logger(__name__)

# Pyrogram's default is 1. The user client performs batch download/upload
# fallback work, so a small bounded increase avoids serializing every file
# transfer without changing the Bot's message-forwarding behavior.
USER_MAX_CONCURRENT_TRANSMISSIONS = 4


def _update_client_options():
    """Keep update polling enabled across Pyrogram and Pyrofork versions."""
    options = {"no_updates": False}
    try:
        parameters = inspect.signature(Client).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "skip_updates" in parameters:
        options["skip_updates"] = False
    return options


_LOOP_BRIDGE_ATTR = "_tgfh_loop_bridge_installed"
_LOOP_BRIDGE_SKIP = {
    "authorize",
    "connect",
    "disconnect",
    "initialize",
    "restart",
    "run",
    "start",
    "stop",
}


def _invoke_on_client_loop(client, function, *args, **kwargs):
    """Invoke a Pyrofork async method on the loop owned by the client."""
    coroutine = function(client, *args, **kwargs)
    return _await_on_client_loop(client, coroutine)


def _await_on_client_loop(client, awaitable):
    """Await an awaitable on the loop owned by the client."""
    loop = getattr(client, "loop", None)
    if loop is None or loop.is_closed():
        raise RuntimeError("Telegram client event loop is unavailable")

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is loop:
        return awaitable

    if loop.is_running():
        return asyncio.run_coroutine_threadsafe(awaitable, loop).result()
    return loop.run_until_complete(awaitable)


def _invoke_async_generator_on_client_loop(
    client,
    function,
    *args,
    **kwargs,
):
    """Return a sync iterator backed by the client-owned event loop."""
    loop = getattr(client, "loop", None)
    if loop is None or loop.is_closed():
        raise RuntimeError("Telegram client event loop is unavailable")

    generator = function(client, *args, **kwargs)
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    if running_loop is loop:
        return generator

    def sync_iterator():
        try:
            while True:
                try:
                    yield _await_on_client_loop(
                        client,
                        generator.__anext__(),
                    )
                except StopAsyncIteration:
                    break
        finally:
            try:
                _await_on_client_loop(client, generator.aclose())
            except Exception:
                pass

    return sync_iterator()


def install_client_loop_bridge(client):
    """Bind Pyrofork's sync method wrappers to the client's own event loop.

    Pyrofork captures the default event loop when its sync wrappers are
    imported. That loop can differ from the loop later assigned to a client
    when the web app imports modules from a background thread. Sync handlers
    then schedule work onto a loop that is not running, so Telegram receives
    the update but the handler appears to hang while sending a reply.

    Replacing only the public async methods on the client instance keeps the
    existing Bot/User Client business logic intact while making every sync
    call use the same loop as the client that owns the dispatcher.
    """
    if client is None or getattr(client, _LOOP_BRIDGE_ATTR, False):
        return client

    loop = getattr(client, "loop", None)
    if loop is None or loop.is_closed():
        return client

    installed = 0
    for name in dir(client):
        if name.startswith("_") or name in _LOOP_BRIDGE_SKIP:
            continue
        try:
            wrapped = getattr(client, name)
        except Exception:
            continue
        function = getattr(wrapped, "__wrapped__", None)
        is_coroutine = function is not None and inspect.iscoroutinefunction(
            function
        )
        is_async_generator = (
            function is not None
            and inspect.isasyncgenfunction(function)
        )
        if not is_coroutine and not is_async_generator:
            continue

        if is_coroutine:
            def sync_bridge(*args, __function=function, **kwargs):
                return _invoke_on_client_loop(
                    client,
                    __function,
                    *args,
                    **kwargs,
                )
        else:
            def sync_bridge(*args, __function=function, **kwargs):
                return _invoke_async_generator_on_client_loop(
                    client,
                    __function,
                    *args,
                    **kwargs,
                )

        sync_bridge = functools.wraps(function)(sync_bridge)
        setattr(client, name, sync_bridge)
        installed += 1

    setattr(client, _LOOP_BRIDGE_ATTR, True)
    logger.info(
        "✅ Telegram客户端同步API已绑定到客户端事件循环（%s 个方法）",
        installed,
    )
    return client


def initialize_clients():
    """
    初始化Telegram客户端

    Returns:
        tuple: (bot_client, user_client)
            - bot_client: Bot客户端实例
            - user_client: User客户端实例（如果配置了session string），否则为None
    """
    logger.info(f"Telegram 客户端库版本: Pyrogram {pyrogram.__version__}")

    # 加载配置
    DATA = load_config()

    # 获取配置值
    bot_token = (getenv("TOKEN", DATA) or "").strip()
    api_hash = (getenv("HASH", DATA) or "").strip()
    api_id_raw = (getenv("ID", DATA) or "").strip()

    try:
        api_id = int(api_id_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("API ID 必须是纯数字") from exc

    # 创建Bot客户端
    logger.info("🤖 正在初始化Bot客户端...")
    # 使用data目录以便持久化保存
    os.makedirs("data", exist_ok=True)
    update_options = _update_client_options()
    bot = Client(
        "data/mybot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        **update_options,
    )
    logger.info("✅ Bot客户端初始化完成")

    # 创建User客户端（如果配置了session string）
    ss = getenv("STRING", DATA)
    if ss is not None:
        logger.info("👤 正在初始化User客户端...")

        if DATA.get("STRING"):
            logger.info("✅ 使用 config.json 中的 session string")
        else:
            logger.info("✅ 使用环境变量 STRING 中的 session string")

        # 先尝试使用已有的 session 文件（包含 Peer 缓存）
        # 使用data目录以便持久化保存
        session_dir = "data"
        os.makedirs(session_dir, exist_ok=True)
        session_file = os.path.join(session_dir, "myacc")

        if os.path.exists(f"{session_file}.session"):
            logger.info("📂 发现已有 Session 文件，将保留 Peer 缓存")
            acc = Client(
                session_file,
                api_id=api_id,
                api_hash=api_hash,
                max_concurrent_transmissions=USER_MAX_CONCURRENT_TRANSMISSIONS,
                **update_options,
            )
        else:
            logger.info("📝 首次启动，使用 Session String 创建 Session 文件")
            # 使用in_memory=False确保Session被保存到文件
            acc = Client(
                session_file,
                api_id=api_id,
                api_hash=api_hash,
                session_string=ss,
                in_memory=False,
                max_concurrent_transmissions=USER_MAX_CONCURRENT_TRANSMISSIONS,
                **update_options,
            )

        # User Client 与 Bot 是独立客户端；User Client 启动失败不能阻止 Bot。
        try:
            acc.start()
        except Exception as exc:
            logger.exception(
                "User客户端启动失败，Bot将继续独立运行: %s",
                exc,
            )
            try:
                acc.stop()
            except Exception:
                pass
            acc = None

        # Pyrogram always uses MemoryStorage when a session_string is supplied,
        # so no .session file is expected here. The client still caches resolved
        # peers for the lifetime of the process.
        if not os.path.exists(f"{session_file}.session"):
            logger.info("ℹ️ Session String 模式使用内存会话；Peer 缓存将在本次运行期间保留")
        else:
            logger.info("✅ Session文件已存在")

        logger.info("✅ User客户端初始化完成")
    else:
        logger.warning("⚠️ 未找到 session string，User客户端未初始化")
        logger.warning("   部分功能（如自动转发）将不可用")
        acc = None

    return bot, acc
