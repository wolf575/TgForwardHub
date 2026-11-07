"""
Message and callback handlers for the bot
"""
import asyncio
from pyrogram import filters
from bot.utils.logger import get_logger
from .commands import register_command_handlers
from .callbacks import callback_handler
from .messages import save
from .auto_forward import create_auto_forward_handler
from .instances import (
    set_bot_instance, set_acc_instance,
    get_bot_instance, get_acc_instance, record_bot_command,
    record_bot_update
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
    async def handle_callback(client, callback_query):
        await asyncio.to_thread(
            callback_handler,
            client,
            callback_query,
        )

    logger.info("✅ 回调处理器已注册")

    # 记录原始 update 到达时间，供 /__health 判断 Bot 是否真的在收消息。
    @bot.on_raw_update(group=-1)
    def record_update(client, update, users, chats):
        record_bot_update()

    logger.info("✅ Bot update 诊断处理器已注册")

    # 注册私聊消息处理器
    @bot.on_message(filters.text & filters.private & ~filters.command(["start", "help", "watch"]))
    async def handle_save(client, message):
        try:
            await asyncio.to_thread(save, client, message)
        except Exception as exc:
            record_bot_command(
                "text",
                exc,
                chat_id=message.chat.id,
            )
            logger.exception("处理 Bot 文本消息失败")
            raise
        record_bot_command(
            "text",
            chat_id=message.chat.id,
        )

    logger.info("✅ 私聊消息处理器已注册")

    @bot.on_message(
        filters.private & filters.text & filters.regex(r"^/"),
        group=1,
    )
    async def handle_unknown_command(client, message):
        command = (message.text or "").strip().split(None, 1)[0]
        command = command.split("@", 1)[0].lower()
        if command in {"/start", "/help", "/watch"}:
            return
        try:
            reply = await client.send_message(
                message.chat.id,
                "未知命令。请使用 /start、/help 或 /watch。",
                reply_to_message_id=message.id,
            )
        except Exception as exc:
            record_bot_command(
                "unknown",
                exc,
                chat_id=message.chat.id,
            )
            logger.exception("发送未知命令回复失败")
            raise
        record_bot_command(
            "unknown",
            chat_id=message.chat.id,
            reply_message_id=getattr(reply, "id", None),
        )

    logger.info("✅ 未知命令处理器已注册")

    # 注册自动转发处理器（如果acc可用）
    if acc is not None and message_queue is not None:
        create_auto_forward_handler(acc, message_queue)
        logger.info("✅ 自动转发处理器已注册")
    else:
        logger.warning("⚠️ 自动转发处理器未注册（User客户端或消息队列不可用）")

    logger.info("🎉 所有处理器注册完成！")
