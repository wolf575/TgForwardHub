"""
Message and callback handlers for the bot
"""
from pyrogram import filters
from bot.utils.logger import get_logger
from .commands import register_command_handlers
from .callbacks import callback_handler
from .messages import save
from .auto_forward import create_auto_forward_handler
from .instances import (
    set_bot_instance, set_acc_instance,
    get_bot_instance, get_acc_instance
)

logger = get_logger(__name__)


def register_all_handlers(bot, acc, message_queue):
    """
    统一注册所有处理器

    Args:
        bot: Bot客户端实例
        acc: User客户端实例（可能为None）
        message_queue: 消息队列实例（可能为None）
    """
    logger.info("📝 正在注册所有处理器...")

    # 设置全局实例
    set_bot_instance(bot)
    set_acc_instance(acc)

    # 注册命令处理器
    register_command_handlers(bot, acc)
    logger.info("✅ 命令处理器已注册")

    # 注册回调处理器
    @bot.on_callback_query()
    def handle_callback(client, callback_query):
        callback_handler(client, callback_query)

    logger.info("✅ 回调处理器已注册")

    # 注册私聊消息处理器
    @bot.on_message(filters.text & filters.private & ~filters.command(["start", "help", "watch"]))
    def handle_save(client, message):
        save(client, message)

    logger.info("✅ 私聊消息处理器已注册")

    # 注册自动转发处理器（如果acc可用）
    if acc is not None and message_queue is not None:
        create_auto_forward_handler(acc, message_queue)
        logger.info("✅ 自动转发处理器已注册")
    else:
        logger.warning("⚠️ 自动转发处理器未注册（User客户端或消息队列不可用）")

    logger.info("🎉 所有处理器注册完成！")
