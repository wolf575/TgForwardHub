"""
自动转发处理器模块
职责：处理频道/群组消息的自动转发
"""
import pyrogram
from pyrogram import filters
from bot.utils.logger import get_logger
from bot.utils import is_message_processed, mark_message_processed, cleanup_old_messages
from bot.utils.dedup import is_media_group_processed, register_processed_media_group, processed_messages
from bot.services.peer_cache import cache_peer_if_needed
from bot.workers import Message
from config import load_watch_config, get_monitored_sources
from constants import MESSAGE_CACHE_CLEANUP_THRESHOLD

logger = get_logger(__name__)


def create_auto_forward_handler(acc, message_queue):
    """
    创建自动转发处理器

    Args:
        acc: User客户端实例
        message_queue: 消息队列实例

    Returns:
        function: 自动转发处理器函数
    """

    @acc.on_message((filters.channel | filters.group | filters.private) & (filters.incoming | filters.outgoing))
    def auto_forward(client: pyrogram.client.Client, message: pyrogram.types.messages_and_media.message.Message):
        """处理频道/群组/私聊消息，包括转发的消息"""
        try:
            # 验证消息对象和属性
            if not message or not hasattr(message, 'chat') or not message.chat:
                logger.debug("跳过：消息对象无效或缺少 chat 属性")
                return

            # 验证chat ID
            if not hasattr(message.chat, 'id') or message.chat.id is None:
                logger.debug("跳过：消息缺少有效的 chat ID")
                return

            # 检查重复消息
            if not hasattr(message, 'id') or message.id is None:
                logger.debug("跳过：消息缺少有效的 message ID")
                return

            if is_message_processed(message.id, message.chat.id):
                logger.debug(f"⏭️ 跳过已处理的消息: chat_id={message.chat.id}, message_id={message.id}")
                return

            # 立即标记为已处理，防止重复处理
            mark_message_processed(message.id, message.chat.id)

            # 定期清理旧消息记录
            if len(processed_messages) > MESSAGE_CACHE_CLEANUP_THRESHOLD:
                cleanup_old_messages()

            # 记录消息类型
            if message.outgoing:
                logger.debug(f"📤 outgoing消息（由Bot转发）: chat_id={message.chat.id}, message_id={message.id}")
            else:
                logger.debug(f"📥 incoming消息（外部来源）: chat_id={message.chat.id}, message_id={message.id}")

            # 获取源chat ID
            source_chat_id = str(message.chat.id)

            # 早期过滤：检查此源是否被监控
            monitored_sources = get_monitored_sources()
            if source_chat_id not in monitored_sources:
                # 记录被过滤的消息（调试用）
                logger.debug(f"⏭️ 消息来自非监控源，已跳过: chat_id={source_chat_id}, message_id={message.id}")
                logger.debug(f"   当前监控源列表: {monitored_sources if monitored_sources else '空'}")
                return

            logger.info(f"🔔 监控源消息: chat_id={source_chat_id}, message_id={message.id}")

            # 缓存源Peer（利用Session文件的原生缓存）
            cache_peer_if_needed(acc, source_chat_id, "源频道")

            # 获取消息文本
            message_text = message.text or message.caption or ""

            # 优化：只在必要时加载媒体组（减少内存占用）
            # 如果是媒体组且没有文本，尝试从第一条消息获取caption
            if message.media_group_id and not message_text:
                try:
                    media_group = acc.get_media_group(message.chat.id, message.id)
                    if media_group and len(media_group) > 0:
                        message_text = media_group[0].text or media_group[0].caption or ""
                        logger.debug(f"📸 从媒体组第一条消息获取文本: {len(message_text)} 字符")
                except Exception as e:
                    logger.debug(f"📸 获取媒体组文本失败: {e}")

            # 查找所有匹配的监控配置
            watch_config = load_watch_config()
            enqueued_count = 0

            for user_id, watches in watch_config.items():
                for watch_key, watch_data in watches.items():
                    if isinstance(watch_data, dict):
                        watch_source = str(watch_data.get("source", ""))
                        dest = watch_data.get("dest")
                        record_mode = watch_data.get("record_mode", False)

                        # 匹配源
                        if watch_source != source_chat_id:
                            continue

                        logger.info(f"✅ 匹配到监控任务: user={user_id}, source={source_chat_id}")

                        # 缓存目标Peer（如果是转发模式）
                        dest_chat_id = dest if not record_mode else None

                        if dest_chat_id and dest_chat_id != "me":
                            # 检查目标是否也是监控源
                            if str(dest_chat_id) in monitored_sources:
                                # 目标也是监控源 - 检查是否已经缓存
                                from bot.utils.peer import is_dest_cached
                                if is_dest_cached(str(dest_chat_id)):
                                    logger.debug(f"💡 目标频道 {dest_chat_id} 也是监控源，Peer已缓存")
                                else:
                                    # 尝试缓存（即使是监控源，也需要确保能转发）
                                    logger.info(f"🔄 目标频道 {dest_chat_id} 也是监控源，尝试缓存Peer...")
                                    cache_peer_if_needed(acc, dest_chat_id, "目标频道")
                            else:
                                # 普通目标频道 - 尝试缓存
                                cache_peer_if_needed(acc, dest_chat_id, "目标频道")

                        # 媒体组去重
                        if message.media_group_id:
                            mode_suffix = "record" if record_mode else "forward"
                            media_group_key = f"{user_id}_{watch_key}_{dest_chat_id}_{mode_suffix}_{message.media_group_id}"

                            if is_media_group_processed(media_group_key):
                                logger.debug(f"⏭️ 跳过已处理的媒体组: {media_group_key}")
                                continue

                            # 注册为已处理
                            register_processed_media_group(media_group_key)
                            logger.info(f"📸 首次处理媒体组: {media_group_key}")

                        # 创建消息对象
                        msg_obj = Message(
                            user_id=user_id,
                            watch_key=watch_key,
                            message=message,
                            watch_data=watch_data,
                            source_chat_id=source_chat_id,
                            dest_chat_id=dest_chat_id,
                            message_text=message_text,
                            media_group_key=f"{user_id}_{watch_key}_{message.media_group_id}" if message.media_group_id else None
                        )

                        # 入队消息进行处理
                        message_queue.put(msg_obj)
                        enqueued_count += 1
                        logger.info(f"📬 消息已入队: user={user_id}, source={source_chat_id}, 队列大小={message_queue.qsize()}")

            if enqueued_count > 0:
                logger.info(f"✅ 本次共入队 {enqueued_count} 条消息")

        except (ValueError, KeyError) as e:
            error_msg = str(e)
            if "Peer id invalid" not in error_msg and "ID not found" not in error_msg:
                logger.error(f"⚠️ auto_forward 错误: {type(e).__name__}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"⚠️ auto_forward 意外错误: {type(e).__name__}: {e}", exc_info=True)

    return auto_forward
