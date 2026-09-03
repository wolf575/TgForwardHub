"""
客户端初始化模块
职责：初始化Bot客户端和User客户端
"""
import os
from pyrogram import Client
from bot.utils.logger import get_logger
from config import load_config, getenv

logger = get_logger(__name__)


def initialize_clients():
    """
    初始化Telegram客户端

    Returns:
        tuple: (bot_client, user_client)
            - bot_client: Bot客户端实例
            - user_client: User客户端实例（如果配置了session string），否则为None
    """
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
    bot = Client("data/mybot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)
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
            acc = Client(session_file, api_id=api_id, api_hash=api_hash)
        else:
            logger.info("📝 首次启动，使用 Session String 创建 Session 文件")
            # 使用in_memory=False确保Session被保存到文件
            acc = Client(
                session_file,
                api_id=api_id,
                api_hash=api_hash,
                session_string=ss,
                in_memory=False
            )

        # 启动User客户端
        acc.start()

        # 强制导出并重新加载session，确保文件被正确创建
        if not os.path.exists(f"{session_file}.session"):
            logger.warning("⚠️ Session文件未自动创建，尝试强制导出...")
            try:
                # 导出当前session string
                current_ss = acc.export_session_string()
                # 停止当前客户端
                acc.stop()
                # 使用导出的session string重新创建客户端（这次应该会创建文件）
                acc = Client(
                    session_file,
                    api_id=api_id,
                    api_hash=api_hash,
                    session_string=current_ss,
                    in_memory=False
                )
                # 重新启动
                acc.start()

                if os.path.exists(f"{session_file}.session"):
                    logger.info("✅ Session文件强制创建成功")
                else:
                    logger.error("❌ Session文件仍然无法创建，这可能影响消息接收")
            except Exception as e:
                logger.error(f"❌ 强制创建Session文件失败: {e}")
        else:
            logger.info("✅ Session文件已存在")

        logger.info("✅ User客户端初始化完成")
    else:
        logger.warning("⚠️ 未找到 session string，User客户端未初始化")
        logger.warning("   部分功能（如自动转发）将不可用")
        acc = None

    return bot, acc
