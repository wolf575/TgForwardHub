"""
客户端初始化模块
职责：初始化Bot客户端和User客户端
"""
import os
import inspect
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
