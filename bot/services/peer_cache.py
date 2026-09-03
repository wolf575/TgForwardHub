"""
Peer缓存管理模块
职责：管理Telegram Peer缓存，避免"Peer id invalid"错误
"""
import time
from pyrogram.errors import FloodWait
from bot.utils.logger import get_logger
from bot.utils.peer import mark_dest_cached, mark_peer_failed, is_dest_cached
from config import load_watch_config

logger = get_logger(__name__)


def cache_peer_if_needed(acc, peer_id, peer_type="频道"):
    """
    智能Peer缓存：利用Session文件的原生缓存机制

    策略：
    1. 直接尝试get_chat()，Session文件中有缓存就会成功
    2. 如果失败，说明Session中没有，需要重新缓存
    3. 对于Bot用户，尝试发送/start命令建立连接
    4. 使用内存标记避免频繁重试失败的Peer

    Args:
        acc: User客户端实例
        peer_id: Peer ID（字符串或整数）
        peer_type: Peer类型描述（用于日志）

    Returns:
        bool: 缓存成功返回True，失败返回False
    """
    peer_id_str = str(peer_id)
    peer_id_int = int(peer_id)

    # 检查是否在冷却期（避免频繁重试失败的Peer）
    from bot.utils.peer import should_retry_peer, mark_peer_failed, failed_peers
    if not should_retry_peer(peer_id_str):
        elapsed = time.time() - failed_peers.get(peer_id_str, 0)
        remaining = 60 - elapsed
        logger.debug(f"⏳ {peer_type} {peer_id} 在冷却期，还需 {remaining:.0f}秒")
        return False

    # 直接尝试获取chat信息（利用Session缓存）
    try:
        chat = acc.get_chat(peer_id_int)

        # 提取聊天名称
        if hasattr(chat, 'title') and chat.title:
            chat_name = chat.title
        elif hasattr(chat, 'first_name') and chat.first_name:
            chat_name = chat.first_name
        elif hasattr(chat, 'username') and chat.username:
            chat_name = f"@{chat.username}"
        else:
            chat_name = "Unknown"

        is_bot = " 🤖" if hasattr(chat, 'is_bot') and chat.is_bot else ""

        logger.info(f"✅ {peer_type}缓存成功: {peer_id} ({chat_name}{is_bot})")
        mark_dest_cached(peer_id_str)
        return True

    except FloodWait as e:
        logger.warning(f"⚠️ 限流: {peer_type} {peer_id}，等待 {e.value} 秒")
        mark_peer_failed(peer_id_str)
        return False

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ 延迟加载{peer_type}失败: {peer_id} - {error_msg}")

        # 如果是PEER_ID_INVALID或Peer id invalid错误，尝试通过对话列表建立连接
        if "PEER_ID_INVALID" in error_msg or "Peer id invalid" in error_msg:
            # 对于正数ID（用户/Bot），先尝试特殊处理
            if peer_id_int > 0:
                logger.info(f"🤖 检测到用户/Bot ID: {peer_id}，尝试建立连接...")

                # 方法1：尝试通过resolve_peer
                try:
                    logger.debug(f"   方法1: 尝试resolve_peer...")
                    from pyrogram import raw
                    resolved = acc.resolve_peer(peer_id_int)
                    logger.info(f"✅ resolve_peer成功: {peer_id}")

                    # 再次尝试get_chat
                    chat = acc.get_chat(peer_id_int)
                    chat_name = chat.first_name or chat.username or "Unknown"
                    is_bot = " 🤖" if hasattr(chat, 'is_bot') and chat.is_bot else ""
                    logger.info(f"✅ Peer连接已建立: {peer_id} ({chat_name}{is_bot})")
                    mark_dest_cached(peer_id_str)
                    return True
                except Exception as e1:
                    logger.debug(f"   方法1失败: {e1}")

                # 方法2：尝试发送/start命令（仅对Bot有效）
                try:
                    logger.debug(f"   方法2: 尝试发送/start命令...")
                    acc.send_message(peer_id_int, "/start")
                    logger.info(f"✅ 已向Bot发送/start命令: {peer_id}")

                    # 等待一下让Telegram处理
                    time.sleep(0.5)

                    # 再次尝试get_chat
                    chat = acc.get_chat(peer_id_int)
                    chat_name = chat.first_name or chat.username or "Unknown"
                    is_bot = " 🤖" if hasattr(chat, 'is_bot') and chat.is_bot else ""
                    logger.info(f"✅ Bot Peer连接已建立: {peer_id} ({chat_name}{is_bot})")
                    mark_dest_cached(peer_id_str)
                    return True
                except Exception as e2:
                    logger.debug(f"   方法2失败: {e2}")

            # 方法3：通过对话列表查找（适用于所有类型）
            logger.info(f"🔄 尝试通过对话列表建立Peer连接: {peer_id}")
            try:
                # 优化：大幅降低搜索范围以减少内存占用
                found = False
                search_limit = 100 if peer_type in ["下一级目标", "目标频道"] else 30
                logger.debug(f"   方法3: 搜索对话列表（前 {search_limit} 个）...")

                for dialog in acc.get_dialogs(limit=search_limit):
                    if dialog.chat.id == peer_id_int:
                        chat_name = dialog.chat.title or dialog.chat.first_name or dialog.chat.username or 'Unknown'
                        logger.info(f"✅ 在对话列表中找到Peer: {peer_id} ({chat_name})")
                        found = True
                        # 尝试获取chat信息来建立Peer缓存
                        try:
                            chat = acc.get_chat(peer_id_int)
                            logger.info(f"✅ Peer连接已建立")
                            mark_dest_cached(peer_id_str)
                            return True
                        except Exception as e3:
                            logger.warning(f"⚠️ 获取chat信息失败: {e3}")
                        break

                if not found:
                    logger.warning(f"⚠️ 在对话列表中未找到Peer: {peer_id}")
                    if peer_id_int > 0:
                        logger.warning(f"💡 对于Bot用户，请确保Bot已启动且可访问")
                        logger.warning(f"💡 或者手动向Bot发送一条消息后重启")
                    elif peer_type in ["下一级目标", "目标频道"]:
                        logger.warning(f"💡 对于私聊用户，请确保该用户已与账号建立过对话")
                    else:
                        logger.warning(f"💡 请确保账号已加入该频道/群组")
            except Exception as e2:
                logger.error(f"❌ 通过对话列表建立连接失败: {e2}")

        mark_peer_failed(peer_id_str)
        return False


def initialize_peer_cache_on_startup_with_retry(acc, max_retries=3):
    """
    带重试的Peer缓存初始化

    确保acc完全连接后再初始化缓存，如果失败自动重试

    Args:
        acc: User客户端实例
        max_retries: 最大重试次数（默认: 3）

    Returns:
        bool: 全部缓存成功返回True，否则返回False
    """
    try:
        watch_config = load_watch_config()
        all_peers = set()
        user_peers = set()  # 私聊用户ID

        # 第一步：收集所有源和目标频道ID
        for user_id, watches in watch_config.items():
            for watch_key, watch_data in watches.items():
                if isinstance(watch_data, dict):
                    source_id = watch_data.get("source")
                    dest_id = watch_data.get("dest")

                    if source_id:
                        try:
                            peer_id = int(source_id)
                            all_peers.add(peer_id)
                            # 正数ID通常是用户
                            if peer_id > 0:
                                user_peers.add(peer_id)
                        except (ValueError, TypeError):
                            pass

                    if dest_id and dest_id != "me":
                        try:
                            peer_id = int(dest_id)
                            all_peers.add(peer_id)
                            # 正数ID通常是用户
                            if peer_id > 0:
                                user_peers.add(peer_id)
                        except (ValueError, TypeError):
                            pass

        if not all_peers:
            logger.info("📭 没有配置的Peer需要初始化")
            return True

        if user_peers:
            logger.info(f"💡 检测到 {len(user_peers)} 个私聊用户配置")
            logger.info(f"   私聊用户ID: {sorted(user_peers)}")

        # 尝试初始化，最多重试 max_retries 次
        for attempt in range(max_retries):
            try:
                logger.info("=" * 60)
                logger.info(f"⚡ 第 {attempt+1}/{max_retries} 次初始化 {len(all_peers)} 个Peer缓存...")
                logger.info("=" * 60)

                success_count = 0
                failed_peers = []

                for peer_id in sorted(all_peers):
                    try:
                        # 关键：get_chat() 会初始化Peer缓存
                        chat = acc.get_chat(peer_id)
                        success_count += 1

                        # 提取聊天名称
                        if hasattr(chat, 'title') and chat.title:
                            chat_name = chat.title
                        elif hasattr(chat, 'first_name') and chat.first_name:
                            chat_name = chat.first_name
                        elif hasattr(chat, 'username') and chat.username:
                            chat_name = f"@{chat.username}"
                        else:
                            chat_name = "Unknown"

                        # 检查是否是Bot
                        is_bot = " 🤖" if hasattr(chat, 'is_bot') and chat.is_bot else ""

                        logger.info(f"   ✅ {peer_id}: {chat_name}{is_bot}")

                        # 标记为已缓存
                        mark_dest_cached(str(peer_id))

                    except Exception as e:
                        error_msg = str(e)

                        # 如果是Peer ID无效错误，尝试通过对话列表查找
                        if "PEER_ID_INVALID" in error_msg or "Peer id invalid" in error_msg:
                            logger.info(f"   🔍 尝试通过对话列表查找: {peer_id}")

                            try:
                                found = False
                                # 搜索对话列表（不限制数量，直到找到为止）
                                for dialog in acc.get_dialogs():
                                    if dialog.chat.id == peer_id:
                                        chat_name = dialog.chat.title or dialog.chat.first_name or dialog.chat.username or 'Unknown'
                                        is_bot = " 🤖" if hasattr(dialog.chat, 'is_bot') and dialog.chat.is_bot else ""
                                        logger.info(f"   ✅ {peer_id}: {chat_name}{is_bot} (通过对话列表)")
                                        mark_dest_cached(str(peer_id))
                                        success_count += 1
                                        found = True
                                        break

                                if found:
                                    continue

                                # 对于Bot用户，尝试发送/start命令
                                if peer_id > 0:
                                    logger.info(f"   🤖 尝试自动建立Bot连接: {peer_id}")
                                    try:
                                        acc.send_message(peer_id, "/start")
                                        time.sleep(0.5)
                                        chat = acc.get_chat(peer_id)
                                        chat_name = chat.first_name or chat.username or "Unknown"
                                        is_bot = " 🤖" if hasattr(chat, 'is_bot') and chat.is_bot else ""
                                        logger.info(f"   ✅ {peer_id}: {chat_name}{is_bot} (自动建立)")
                                        mark_dest_cached(str(peer_id))
                                        success_count += 1
                                        continue
                                    except Exception as e_bot:
                                        logger.debug(f"   自动建立失败: {e_bot}")

                            except Exception as e_dialog:
                                logger.debug(f"   对话列表查找失败: {e_dialog}")

                        error_msg_short = error_msg[:60]
                        failed_peers.append((peer_id, error_msg_short))
                        logger.warning(f"   ⚠️ {peer_id}: {error_msg_short}")

                logger.info("=" * 60)
                logger.info(f"✅ Peer缓存初始化完成: {success_count}/{len(all_peers)} 成功")

                # 如果全部成功，返回
                if success_count == len(all_peers):
                    logger.info("=" * 60)
                    logger.info("")
                    return True

                # 如果部分失败，显示诊断信息
                if failed_peers:
                    logger.warning(f"⚠️ 失败的Peer (共{len(failed_peers)}个):")
                    failed_users = []
                    failed_channels = []

                    for peer_id, error in failed_peers:
                        logger.warning(f"   - {peer_id}: {error}")
                        mark_peer_failed(str(peer_id))

                        # 分类失败的Peer
                        if peer_id > 0:
                            failed_users.append(peer_id)
                        else:
                            failed_channels.append(peer_id)

                    # 对私聊用户提供特殊提示
                    if failed_users:
                        logger.warning(f"")
                        logger.warning(f"💡 私聊用户缓存失败 ({len(failed_users)}个):")
                        logger.warning(f"   用户ID: {failed_users}")
                        logger.warning(f"   解决方法：")
                        logger.warning(f"   1. 让这些用户向账号发送一条消息")
                        logger.warning(f"   2. 或者账号主动向这些用户发送一条消息")
                        logger.warning(f"   3. 然后重启Bot")

                # 如果还有重试机会，等待后重试
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.info(f"⏳ 等待 {wait_time} 秒后重试（还有 {max_retries - attempt - 1} 次机会）...")
                    logger.info("=" * 60)
                    logger.info("")
                    time.sleep(wait_time)
                else:
                    logger.info(f"💡 失败的Peer将在接收到第一条消息时自动重试延迟加载")
                    logger.info("=" * 60)
                    logger.info("")

            except Exception as e:
                logger.error(f"❌ 初始化异常: {e}", exc_info=True)

                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.info(f"⏳ 异常后等待 {wait_time} 秒再试...")
                    logger.info("=" * 60)
                    logger.info("")
                    time.sleep(wait_time)

        logger.warning(f"⚠️ 达到最大重试次数 ({max_retries})，Peer缓存初始化未能完全完成")
        logger.info("")
        return False

    except Exception as e:
        logger.error(f"❌ Peer缓存初始化失败: {e}", exc_info=True)
        return False
