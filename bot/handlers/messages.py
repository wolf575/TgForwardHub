"""
Message handlers for the bot
"""
import pyrogram
import re
import os
import shutil
import tempfile
import time
import threading
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)
from pyrogram.errors import (
    ChatForwardsRestricted,
    FileReferenceExpired,
    InviteHashExpired,
    UserAlreadyParticipant,
    UsernameNotOccupied,
)

from bot.handlers.instances import get_bot_instance, get_acc_instance
from bot.handlers.watch_setup import (
    handle_add_source, handle_add_dest, show_filter_options,
    show_filter_options_single, complete_watch_setup
)
from bot.utils.status import user_states
from bot.utils.helpers import get_message_type
from bot.utils.progress import progress, downstatus, upstatus
from bot.utils.logger import get_logger
from config import load_watch_config, save_watch_config
from app_settings import batch_completion_notifications_enabled

logger = get_logger(__name__)


_MESSAGE_LINK_RE = re.compile(r'https://t\.me/((?:c/|b/)?)([^/?#\s]+)/(\d+)')


def _parse_message_range(text):
    """Parse a Telegram message link (or an ID range) into chat info and IDs.

    Returns ``(kind, chat, from_id, to_id)`` where ``kind`` is ``""`` for a
    public username, ``"c/"`` for a private channel, or ``"b/"`` for a bot.
    Accepts both hyphen and whitespace separators, and tolerates a full second
    link instead of just the trailing message ID.
    """
    cleaned = (text or "").replace("?single", "")
    matches = list(_MESSAGE_LINK_RE.finditer(cleaned))
    if not matches:
        return None

    first = matches[0]
    kind = first.group(1)
    chat = first.group(2)
    from_id = int(first.group(3))

    if len(matches) >= 2:
        to_id = int(matches[1].group(3))
    else:
        tail = cleaned[first.end():]
        tail_match = re.match(r'^[\s-]*(\d+)', tail)
        to_id = int(tail_match.group(1)) if tail_match else from_id

    return kind, chat, from_id, to_id


def save(client: pyrogram.client.Client, message: pyrogram.types.messages_and_media.message.Message):
    """Handle user text input during multi-step interactions"""
    bot = get_bot_instance()
    acc = get_acc_instance()
    
    print(message.text)
    user_id = str(message.from_user.id)
    
    if user_id in user_states:
        action = user_states[user_id].get("action")
        
        if action == "add_source":
            handle_add_source(message, user_id)
            return
        
        elif action == "add_dest":
            handle_add_dest(message, user_id)
            return
        
        elif action == "add_whitelist":
            keywords = [kw.strip() for kw in message.text.split(',') if kw.strip()]
            if keywords:
                user_states[user_id]["whitelist"] = keywords
                bot.send_message(message.chat.id, f"✅ 关键词白名单已设置：`{', '.join(keywords)}`")
                msg = bot.send_message(message.chat.id, "⏳ 继续设置...")
                if user_states[user_id].get("record_mode"):
                    show_filter_options_single(message.chat.id, msg.id, user_id)
                else:
                    show_filter_options(message.chat.id, msg.id, user_id)
            else:
                bot.send_message(message.chat.id, "**❌ 请输入至少一个关键词**")
            return
        
        elif action == "add_blacklist":
            keywords = [kw.strip() for kw in message.text.split(',') if kw.strip()]
            if keywords:
                user_states[user_id]["blacklist"] = keywords
                bot.send_message(message.chat.id, f"✅ 关键词黑名单已设置：`{', '.join(keywords)}`")
            else:
                user_states[user_id]["blacklist"] = []
            msg = bot.send_message(message.chat.id, "⏳ 继续设置...")
            if user_states[user_id].get("record_mode"):
                show_filter_options_single(message.chat.id, msg.id, user_id)
            else:
                show_filter_options(message.chat.id, msg.id, user_id)
            return
        
        elif action == "add_regex_whitelist":
            patterns = [p.strip() for p in message.text.split(',') if p.strip()]
            if patterns:
                try:
                    for pattern in patterns:
                        re.compile(pattern)
                    user_states[user_id]["whitelist_regex"] = patterns
                    bot.send_message(message.chat.id, f"✅ 正则白名单已设置：`{', '.join(patterns)}`")
                    msg = bot.send_message(message.chat.id, "⏳ 继续设置...")
                    if user_states[user_id].get("record_mode"):
                        show_filter_options_single(message.chat.id, msg.id, user_id)
                    else:
                        show_filter_options(message.chat.id, msg.id, user_id)
                except re.error as e:
                    bot.send_message(message.chat.id, f"**❌ 正则表达式错误：** `{str(e)}`\n\n请重新输入")
            else:
                bot.send_message(message.chat.id, "**❌ 请输入至少一个正则表达式**")
            return
        
        elif action == "add_regex_blacklist":
            patterns = [p.strip() for p in message.text.split(',') if p.strip()]
            if patterns:
                try:
                    for pattern in patterns:
                        re.compile(pattern)
                    user_states[user_id]["blacklist_regex"] = patterns
                    bot.send_message(message.chat.id, f"✅ 正则黑名单已设置：`{', '.join(patterns)}`")
                    msg = bot.send_message(message.chat.id, "⏳ 继续设置...")
                    if user_states[user_id].get("record_mode"):
                        show_filter_options_single(message.chat.id, msg.id, user_id)
                    else:
                        show_filter_options(message.chat.id, msg.id, user_id)
                except re.error as e:
                    bot.send_message(message.chat.id, f"**❌ 正则表达式错误：** `{str(e)}`\n\n请重新输入")
            else:
                bot.send_message(message.chat.id, "**❌ 请输入至少一个正则表达式**")
            return
        
        elif action == "add_extract_patterns":
            patterns = [p.strip() for p in message.text.split(',') if p.strip()]
            if patterns:
                try:
                    for pattern in patterns:
                        re.compile(pattern)
                    
                    whitelist = user_states[user_id].get("whitelist", [])
                    blacklist = user_states[user_id].get("blacklist", [])
                    whitelist_regex = user_states[user_id].get("whitelist_regex", [])
                    blacklist_regex = user_states[user_id].get("blacklist_regex", [])
                    preserve_source = user_states[user_id].get("preserve_source", False)
                    
                    msg = bot.send_message(message.chat.id, "⏳ 正在完成设置...")
                    complete_watch_setup(message.chat.id, msg.id, user_id, whitelist, blacklist, whitelist_regex, blacklist_regex, preserve_source, "extract", patterns)
                except re.error as e:
                    bot.send_message(message.chat.id, f"**❌ 正则表达式错误：** `{str(e)}`\n\n请重新输入")
            else:
                bot.send_message(message.chat.id, "**❌ 请输入至少一个正则表达式**")
            return
        
        elif action.startswith("edit_filter_"):
            parts = action.split("_")
            filter_type = parts[2]

            # Handle extract filter (no color part)
            if filter_type == "extract":
                color = None
            else:
                color = parts[3] if len(parts) > 3 else None

            task_id = user_states[user_id].get("task_id")
            watch_key = user_states[user_id].get("watch_key")

            watch_config = load_watch_config()
            user_id_str = str(message.from_user.id)

            if filter_type == "kw":
                keywords = [kw.strip() for kw in message.text.split(',') if kw.strip()]
                key = "whitelist" if color == "white" else "blacklist"
                watch_config[user_id_str][watch_key][key] = keywords
            elif filter_type == "re":
                patterns = [p.strip() for p in message.text.split(',') if p.strip()]
                try:
                    for pattern in patterns:
                        re.compile(pattern)
                    key = "whitelist_regex" if color == "white" else "blacklist_regex"
                    watch_config[user_id_str][watch_key][key] = patterns
                except re.error as e:
                    bot.send_message(message.chat.id, f"**❌ 正则表达式错误：** `{str(e)}`\n\n请重新输入")
                    return
            elif filter_type == "extract":
                patterns = [p.strip() for p in message.text.split(',') if p.strip()]
                try:
                    for pattern in patterns:
                        re.compile(pattern)
                    watch_config[user_id_str][watch_key]["extract_patterns"] = patterns
                except re.error as e:
                    bot.send_message(message.chat.id, f"**❌ 正则表达式错误：** `{str(e)}`\n\n请重新输入")
                    return

            save_watch_config(watch_config)

            del user_states[user_id]

            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回详情", callback_data=f"watch_view_{task_id}")]])
            bot.send_message(message.chat.id, "**✅ 规则已更新**", reply_markup=keyboard)
            return
        
        elif action == "edit_extract_patterns":
            patterns = [p.strip() for p in message.text.split(',') if p.strip()]
            task_id = user_states[user_id].get("task_id")
            watch_key = user_states[user_id].get("watch_key")

            if patterns:
                try:
                    for pattern in patterns:
                        re.compile(pattern)

                    watch_config = load_watch_config()
                    user_id_str = str(message.from_user.id)

                    if isinstance(watch_config[user_id_str][watch_key], dict):
                        watch_config[user_id_str][watch_key]["extract_patterns"] = patterns

                    save_watch_config(watch_config)
                    del user_states[user_id]

                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回详情", callback_data=f"watch_view_{task_id}")]])
                    bot.send_message(message.chat.id, "**✅ 提取规则已设置**", reply_markup=keyboard)
                except re.error as e:
                    bot.send_message(message.chat.id, f"**❌ 正则表达式错误：** `{str(e)}`\n\n请重新输入")
            else:
                bot.send_message(message.chat.id, "**❌ 请输入至少一个正则表达式**")
            return

    # joining chats
    if "https://t.me/+" in message.text or "https://t.me/joinchat/" in message.text:

        if acc is None:
            bot.send_message(message.chat.id, f"**❌ 未设置 String Session**", reply_to_message_id=message.id)
            return

        try:
            try:
                acc.join_chat(message.text)
            except Exception as e:
                bot.send_message(message.chat.id, f"**❌ 错误** : __{e}__", reply_to_message_id=message.id)
                return
            bot.send_message(message.chat.id, "**✅ 已加入频道**", reply_to_message_id=message.id)
        except UserAlreadyParticipant:
            bot.send_message(message.chat.id, "**✅ 已经加入该频道**", reply_to_message_id=message.id)
        except InviteHashExpired:
            bot.send_message(message.chat.id, "**❌ 无效链接**", reply_to_message_id=message.id)

    # getting message
    elif "https://t.me/" in message.text:

        parsed = _parse_message_range(message.text)
        if parsed is None:
            bot.send_message(message.chat.id, "**❌ 无效链接**", reply_to_message_id=message.id)
            return
        link_kind, chat_ref, fromID, toID = parsed

        # 统计转发结果
        total_messages = toID - fromID + 1
        success_count = 0
        failed_ids = []
        skipped_count = 0
        public_handled_ids = set()
        public_skipped_ids = set()

        logger.info(f"📤 开始批量转发: 共 {total_messages} 条消息 (ID: {fromID}-{toID})")

        for msgid in range(fromID, toID+1):

            # private
            if link_kind == "c/":
                chatid = int("-100" + chat_ref)

                if acc is None:
                    bot.send_message(message.chat.id, f"**❌ 未设置 String Session**", reply_to_message_id=message.id)
                    return

                try:
                    handle_private(message, chatid, msgid)
                    success_count += 1
                    logger.debug(f"✅ 消息 {msgid} 转发成功 ({success_count}/{total_messages})")
                except Exception as e:
                    failed_ids.append(msgid)
                    logger.warning(f"⚠️ 消息 {msgid} 转发失败: {type(e).__name__}: {e}")

            # bot
            elif link_kind == "b/":
                username = chat_ref

                if acc is None:
                    bot.send_message(message.chat.id, f"**❌ 未设置 String Session**", reply_to_message_id=message.id)
                    return
                try:
                    handle_private(message, username, msgid)
                    success_count += 1
                    logger.debug(f"✅ 消息 {msgid} 转发成功 ({success_count}/{total_messages})")
                except Exception as e:
                    failed_ids.append(msgid)
                    logger.warning(f"⚠️ 消息 {msgid} 转发失败: {type(e).__name__}: {e}")

            # public
            else:
                username = chat_ref

                if msgid in public_handled_ids or msgid in public_skipped_ids:
                    continue

                try:
                    delivered_ids, skipped = _copy_public_message(
                        bot,
                        message.chat.id,
                        username,
                        msgid,
                    )
                except UsernameNotOccupied:
                    bot.send_message(message.chat.id, f"**❌ 该用户名未被占用**", reply_to_message_id=message.id)
                    return
                except Exception as copy_exc:
                    if acc is None:
                        bot.send_message(message.chat.id, f"**❌ 未设置 String Session**", reply_to_message_id=message.id)
                        return
                    try:
                        handle_private(message, username, msgid)
                        public_handled_ids.add(msgid)
                        success_count += 1
                        logger.debug(f"✅ 消息 {msgid} 转发成功 ({success_count}/{total_messages})")
                    except Exception as e:
                        failed_ids.append(msgid)
                        logger.warning(
                            f"⚠️ 消息 {msgid} Bot 复制失败，用户客户端回退也失败: "
                            f"{type(copy_exc).__name__}: {copy_exc}; "
                            f"{type(e).__name__}: {e}"
                        )
                    continue

                if skipped:
                    public_skipped_ids.add(msgid)
                    skipped_count += 1
                    logger.debug(f"⏭️ 消息 {msgid} 为空或已删除，已跳过")
                    continue

                public_handled_ids.update(delivered_ids)
                delivered_in_range = [
                    item_id for item_id in delivered_ids
                    if fromID <= item_id <= toID
                ]
                success_count += len(delivered_in_range)
                if len(delivered_ids) > 1:
                    logger.debug(
                        f"✅ 消息 {msgid} 所在媒体组转发成功，共 {len(delivered_ids)} 项 "
                        f"({success_count}/{total_messages})"
                    )
                else:
                    logger.debug(f"✅ 消息 {msgid} 转发成功 ({success_count}/{total_messages})")

            # 减少等待时间，避免超时
            time.sleep(1)

        # 发送转发结果摘要
        failed_count = len(failed_ids)
        if failed_count > 0:
            failed_ids_str = ", ".join(map(str, failed_ids))
            summary = (
                f"📊 **批量转发完成**\n\n"
                f"✅ 成功: {success_count}/{total_messages}\n"
                f"❌ 失败: {failed_count}\n"
                f"⏭️ 跳过: {skipped_count}\n\n"
                f"失败的消息ID: {failed_ids_str}"
            )
            logger.warning(f"批量转发完成: 成功 {success_count}, 失败 {failed_count}, 失败ID: {failed_ids_str}")
        elif skipped_count > 0:
            summary = (
                f"📊 **批量转发完成**\n\n"
                f"✅ 成功: {success_count}/{total_messages}\n"
                f"⏭️ 跳过: {skipped_count}"
            )
            logger.info(
                f"批量转发完成: 成功 {success_count}/{total_messages}, "
                f"跳过 {skipped_count}"
            )
        else:
            summary = f"✅ **批量转发完成**\n\n成功转发 {success_count}/{total_messages} 条消息"
            logger.info(f"批量转发完成: 全部成功 ({success_count}/{total_messages})")

        if batch_completion_notifications_enabled():
            bot.send_message(
                message.chat.id,
                summary,
                reply_to_message_id=message.id,
            )
        else:
            logger.info("批量转发完成通知已关闭，跳过结果摘要")


def _copy_public_message(bot, destination_chat_id, username, msgid):
    """Copy one public message while preserving its complete media group.

    Returns ``(delivered_ids, skipped)``. Album members are copied once as a
    group; the caller can use the returned IDs to avoid copying them again
    when the link contains an ID range.
    """
    msg = bot.get_messages(username, msgid)
    if msg is None or getattr(msg, "empty", False):
        return [], True

    source_chat_id = getattr(getattr(msg, "chat", None), "id", username)
    if not getattr(msg, "media_group_id", None):
        bot.copy_message(destination_chat_id, source_chat_id, msg.id)
        return [msg.id], False

    try:
        media_group = bot.get_media_group(username, msg.id) or [msg]
    except Exception as exc:
        logger.debug(
            "Bot 客户端无法获取公共媒体组 %s/%s，将按当前消息处理: %s",
            username,
            msg.id,
            exc,
        )
        media_group = [msg]

    by_id = {item.id: item for item in media_group}
    by_id[msg.id] = msg
    group_ids = [item_id for item_id in sorted(by_id)]

    try:
        bot.copy_media_group(destination_chat_id, source_chat_id, msg.id)
        return group_ids, False
    except Exception as exc:
        logger.debug(
            "公共媒体组整体复制失败，回退到锚点消息 %s/%s: %s",
            username,
            msg.id,
            type(exc).__name__,
        )
        bot.copy_message(destination_chat_id, source_chat_id, msg.id)
        return [msg.id], False


def _get_bot_peer_id(bot):
    """Return the user-client peer ID of the bot."""
    me = getattr(bot, "me", None)
    if me is None:
        try:
            me = bot.get_me()
        except AttributeError:
            me = None

    if me is None or getattr(me, "id", None) is None:
        raise RuntimeError("无法获取 Bot 用户 ID")

    return int(me.id)


def _copy_single_private_media(
    acc,
    destination,
    chatid,
    msg,
    caption=None,
    caption_entities=None,
):
    """Copy one private media message with Pyrogram's cached-media path."""
    copy_kwargs = {}
    if caption is not None:
        copy_kwargs["caption"] = caption
    if caption_entities is not None:
        copy_kwargs["caption_entities"] = caption_entities

    try:
        return acc.copy_message(destination, chatid, msg.id, **copy_kwargs)
    except FileReferenceExpired as exc:
        # A newly fetched message normally carries a fresh file reference.
        # Refetching here can repair an expired reference without downloading.
        fresh = acc.get_messages(chatid, msg.id)
        if fresh is None:
            raise RuntimeError(f"无法重新获取消息 {msg.id}") from exc
        return acc.copy_message(destination, chatid, fresh.id, **copy_kwargs)


def _forward_private_media_direct(bot, acc, chatid, msg):
    """Copy a private media message to the bot chat without downloading it.

    The command message lives in the chat between the Telegram account and the
    bot. From the user client's point of view that chat is addressed by the
    bot's user ID, so the command chat ID cannot be reused as the destination.

    ``copy_message`` sends media through ``messages.SendMedia`` using its
    ``file_id``. It deliberately avoids ``messages.ForwardMessages``, which is
    the API restricted by Telegram's "no forwarding" chat setting. This matches
    the public-channel path used by the bot client.
    """
    destination = _get_bot_peer_id(bot)

    if getattr(msg, "media_group_id", None):
        try:
            return acc.copy_media_group(destination, chatid, msg.id)
        except Exception as exc:
            logger.debug(
                "媒体组整体复制失败，改逐条复制 %s/%s: %s",
                chatid,
                msg.id,
                type(exc).__name__,
            )

        media_group = None
        try:
            media_group = acc.get_media_group(chatid, msg.id)
        except Exception as exc:
            logger.debug("无法获取媒体组 %s/%s: %s", chatid, msg.id, exc)

        messages = media_group or [msg]
        errors = []
        for item in messages:
            try:
                _copy_single_private_media(acc, destination, chatid, item)
            except Exception as exc:
                errors.append(f"{item.id}: {type(exc).__name__}: {exc}")

        if not errors:
            return
        raise RuntimeError("; ".join(errors))

    try:
        return _copy_single_private_media(acc, destination, chatid, msg)
    except Exception as exc:
        logger.warning(
            "消息 %s/%s 缓存媒体复制失败: %s: %s",
            chatid,
            msg.id,
            type(exc).__name__,
            exc,
        )
        raise


def _forward_private_media_via_bot(bot, destination_chat_id, chatid, msgid):
    """Try the public-channel Bot-identity path for a private chat.

    The public path succeeds because the Bot client is the sender. A bot can
    only use that same path for a private chat when it can read messages there
    (for example, when it has been added to the group or channel). This helper
    is intentionally non-fatal: if the bot is not a participant, handling falls
    back to the configured user account.
    """
    try:
        msg = bot.get_messages(chatid, msgid)
    except Exception as exc:
        logger.debug(
            "Bot 客户端无法读取私有会话 %s/%s，继续使用用户客户端: %s: %s",
            chatid,
            msgid,
            type(exc).__name__,
            exc,
        )
        return False

    if msg is None:
        return False

    try:
        if getattr(msg, "media_group_id", None):
            bot.copy_media_group(destination_chat_id, chatid, msg.id)
        else:
            _copy_single_private_media(bot, destination_chat_id, chatid, msg)
        return True
    except Exception as exc:
        logger.debug(
            "Bot 客户端无法直接复制私有会话 %s/%s: %s: %s",
            chatid,
            msgid,
            type(exc).__name__,
            exc,
        )
        return False


def _get_private_media_group_messages(acc, chatid, msg):
    """Return the complete private media group, ordered by message ID."""
    if not getattr(msg, "media_group_id", None):
        return [msg]

    try:
        media_group = acc.get_media_group(chatid, msg.id) or []
    except Exception as exc:
        logger.debug(
            "无法获取私有媒体组 %s/%s，将仅处理当前消息: %s",
            chatid,
            msg.id,
            exc,
        )
        media_group = []

    by_id = {item.id: item for item in media_group}
    by_id[msg.id] = msg
    return [by_id[message_id] for message_id in sorted(by_id)]


def _download_private_media_group(
    acc,
    chatid,
    msg,
    progress_callback=None,
    progress_args=None,
    group_messages=None,
):
    """Download a complete media group into a temporary directory.

    Returns ``(group_messages, downloads, work_dir)``. The caller owns
    ``work_dir`` and must remove it after uploading. ``downloads`` is a list of
    ``(message, file_path, thumbnail_path)`` tuples aligned with the returned
    ``group_messages``. Messages without downloadable media are skipped so one
    unsupported item does not abort the rest of the album.
    """
    if group_messages is None:
        group_messages = _get_private_media_group_messages(acc, chatid, msg)
    work_dir = tempfile.mkdtemp(prefix="tg_forward_album_")
    downloads = []
    downloadable_messages = []

    try:
        for index, item in enumerate(group_messages):
            download_kwargs = {
                "file_name": os.path.join(work_dir, ""),
            }
            if progress_callback is not None:
                download_kwargs["progress"] = progress_callback
                download_kwargs["progress_args"] = progress_args

            try:
                file_path = acc.download_media(item, **download_kwargs)
            except ValueError as exc:
                if "doesn't contain any downloadable media" in str(exc):
                    logger.debug("媒体组消息 %s 没有可下载媒体，已跳过", item.id)
                    continue
                raise
            if file_path is None:
                raise RuntimeError(f"媒体组消息 {item.id} 下载失败")

            payload = _get_private_media_payload(item)
            thumb = None
            if get_message_type(item) in (
                "Document",
                "Video",
                "Audio",
                "Animation",
                "VideoNote",
            ):
                thumb = _download_private_media_thumbnail(
                    acc,
                    payload,
                    work_dir,
                    index,
                )
            downloads.append((item, file_path, thumb))
            downloadable_messages.append(item)

        if not downloads:
            raise RuntimeError(
                f"媒体组消息 {group_messages[0].id} 没有可下载的媒体"
            )
        return downloadable_messages, downloads, work_dir
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def _should_forward_private_media_group(message):
    """Mirror the public-link rule for deciding whether to use the album."""
    text = getattr(message, "text", "") or ""
    if "?single" in text:
        return True

    parsed = _parse_message_range(text)
    if parsed is None:
        return False
    return parsed[2] == parsed[3]


def _get_private_media_payload(item):
    """Return the media object attached to a private message, if any."""
    msg_type = get_message_type(item)
    if msg_type == "Text":
        return None
    attribute_name = "video_note" if msg_type == "VideoNote" else msg_type.lower()
    return getattr(item, attribute_name, None)


def _nonempty_file(path):
    """Return True when path points to a non-empty regular file."""
    if not path:
        return False
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _download_private_media_thumbnail(acc, payload, work_dir, index):
    """Download an optional thumbnail without failing the whole media group."""
    thumbs = getattr(payload, "thumbs", None)
    if not thumbs:
        return None

    try:
        thumb_path = acc.download_media(
            thumbs[0].file_id,
            file_name=os.path.join(work_dir, f"thumb_{index}.jpg"),
        )
    except Exception as exc:
        logger.debug("无法下载媒体组第 %s 项缩略图: %s", index + 1, exc)
        return None

    if not _nonempty_file(thumb_path):
        if thumb_path and os.path.isfile(thumb_path):
            try:
                os.remove(thumb_path)
            except OSError as exc:
                logger.debug(
                    "无法删除媒体组第 %s 项空缩略图: %s",
                    index + 1,
                    exc,
                )
        logger.warning("媒体组第 %s 项缩略图为空，上传时已忽略", index + 1)
        return None
    return thumb_path


def _build_private_media_group_inputs(
    group_messages,
    downloads,
    caption_override=None,
    caption_entities_override=None,
):
    """Build Pyrogram InputMedia objects for a downloaded media group."""
    caption_message = next(
        (item for item in group_messages if getattr(item, "caption", None)),
        group_messages[0],
    )
    caption = (
        caption_override
        if caption_override is not None
        else caption_message.caption or ""
    )
    caption_entities = (
        caption_entities_override
        if caption_override is not None
        else caption_message.caption_entities
    )
    media_inputs = []

    for index, (item, file_path, thumb) in enumerate(downloads):
        item_caption = caption if index == 0 else ""
        item_caption_entities = caption_entities if index == 0 else None
        msg_type = get_message_type(item)
        thumb = thumb if _nonempty_file(thumb) else None

        if msg_type == "Photo":
            media_inputs.append(
                InputMediaPhoto(
                    file_path,
                    caption=item_caption,
                    caption_entities=item_caption_entities,
                    has_spoiler=getattr(item, "has_media_spoiler", None),
                )
            )
        elif msg_type == "Video":
            video = item.video
            media_inputs.append(
                InputMediaVideo(
                    file_path,
                    thumb=thumb,
                    caption=item_caption,
                    caption_entities=item_caption_entities,
                    width=video.width or 0,
                    height=video.height or 0,
                    duration=video.duration or 0,
                    supports_streaming=(
                        video.supports_streaming
                        if video.supports_streaming is not None
                        else True
                    ),
                    has_spoiler=getattr(item, "has_media_spoiler", None),
                )
            )
        elif msg_type == "Document":
            media_inputs.append(
                InputMediaDocument(
                    file_path,
                    thumb=thumb,
                    caption=item_caption,
                    caption_entities=item_caption_entities,
                )
            )
        elif msg_type == "Audio":
            audio = item.audio
            media_inputs.append(
                InputMediaAudio(
                    file_path,
                    thumb=thumb,
                    caption=item_caption,
                    caption_entities=item_caption_entities,
                    duration=audio.duration or 0,
                    performer=audio.performer or "",
                    title=audio.title or "",
                )
            )
        elif msg_type in ("Animation", "Sticker", "Voice", "VideoNote"):
            # These are not accepted as native album entries by Telegram. Send
            # them as documents so every item is still delivered together.
            media_inputs.append(
                InputMediaDocument(
                    file_path,
                    thumb=thumb,
                    caption=item_caption,
                    caption_entities=item_caption_entities,
                )
            )
        else:
            raise RuntimeError(f"媒体组包含不支持的消息类型: {msg_type}")

    return media_inputs


def _send_downloaded_private_media_sequentially(
    bot,
    destination_chat_id,
    source_msg,
    file_path,
    thumb=None,
    caption_override=None,
    caption_entities_override=None,
):
    """Upload one downloaded private media item with its original format."""
    msg_type = get_message_type(source_msg)
    caption = (
        caption_override
        if caption_override is not None
        else source_msg.caption
    )
    caption_entities = (
        caption_entities_override
        if caption_override is not None
        else source_msg.caption_entities
    )

    if msg_type == "Document":
        return bot.send_document(
            destination_chat_id,
            file_path,
            thumb=thumb,
            caption=caption,
            caption_entities=caption_entities,
        )
    elif msg_type == "Video":
        video = source_msg.video
        return bot.send_video(
            destination_chat_id,
            file_path,
            duration=video.duration,
            width=video.width,
            height=video.height,
            thumb=thumb,
            caption=caption,
            caption_entities=caption_entities,
        )
    elif msg_type == "Animation":
        return bot.send_animation(
            destination_chat_id,
            file_path,
            caption=caption,
            caption_entities=caption_entities,
        )
    elif msg_type == "VideoNote":
        video_note = source_msg.video_note
        return bot.send_video_note(
            destination_chat_id,
            file_path,
            duration=video_note.duration,
            length=video_note.length,
            thumb=thumb,
        )
    elif msg_type == "Sticker":
        return bot.send_sticker(destination_chat_id, file_path)
    elif msg_type == "Voice":
        return bot.send_voice(
            destination_chat_id,
            file_path,
            caption=caption,
            caption_entities=caption_entities,
        )
    elif msg_type == "Audio":
        return bot.send_audio(
            destination_chat_id,
            file_path,
            caption=caption,
            caption_entities=caption_entities,
        )
    elif msg_type == "Photo":
        return bot.send_photo(
            destination_chat_id,
            file_path,
            caption=caption,
            caption_entities=caption_entities,
        )
    else:
        raise RuntimeError(f"不支持的消息类型: {msg_type}")


def _send_downloaded_private_media_group(
    bot,
    destination_chat_id,
    group_messages,
    downloads,
    caption_override=None,
    caption_entities_override=None,
):
    """Upload a downloaded group as an album, falling back to item uploads."""
    media_inputs = _build_private_media_group_inputs(
        group_messages,
        downloads,
        caption_override=caption_override,
        caption_entities_override=caption_entities_override,
    )

    try:
        result = bot.send_media_group(destination_chat_id, media_inputs)
        return _message_id(result)
    except Exception as exc:
        has_thumb = any(thumb for _item, _file_path, thumb in downloads)
        if has_thumb:
            thumbless_downloads = [
                (item, file_path, None)
                for item, file_path, _thumb in downloads
            ]
            thumbless_inputs = _build_private_media_group_inputs(
                group_messages,
                thumbless_downloads,
                caption_override=caption_override,
                caption_entities_override=caption_entities_override,
            )
            try:
                result = bot.send_media_group(
                    destination_chat_id,
                    thumbless_inputs,
                )
                logger.info(
                    "去除缩略图后媒体组上传成功: %s: %s",
                    type(exc).__name__,
                    exc,
                )
                return _message_id(result)
            except Exception as retry_exc:
                logger.warning(
                    "去除缩略图后媒体组上传仍失败，改为逐条上传: "
                    "%s: %s -> %s: %s",
                    type(exc).__name__,
                    exc,
                    type(retry_exc).__name__,
                    retry_exc,
                )
        else:
            logger.warning(
                "媒体组上传失败，改为逐条上传: %s: %s",
                type(exc).__name__,
                exc,
            )

    forwarded_message_id = None
    for index, (item, file_path, thumb) in enumerate(downloads):
        result = _send_downloaded_private_media_sequentially(
            bot,
            destination_chat_id,
            item,
            file_path,
            thumb=thumb,
            caption_override=caption_override if index == 0 else None,
            caption_entities_override=caption_entities_override if index == 0 else None,
        )
        if index == 0:
            forwarded_message_id = _message_id(result)
    return forwarded_message_id


def _message_id(result):
    """Extract a stable first message ID from a Pyrogram result."""
    if isinstance(result, list):
        if not result:
            return None
        result = result[0]
    if result is None:
        return None
    return getattr(result, "id", result)


def _download_and_reupload_media_fallback(
    acc,
    destination_chat_id,
    chatid,
    msg,
    caption_override=None,
    caption_entities_override=None,
):
    """Download and re-upload restricted media through the user client."""
    group_messages, downloads, work_dir = _download_private_media_group(
        acc,
        chatid,
        msg,
    )
    try:
        if len(group_messages) > 1:
            return _send_downloaded_private_media_group(
                acc,
                destination_chat_id,
                group_messages,
                downloads,
                caption_override=caption_override,
                caption_entities_override=caption_entities_override,
            )

        item, file_path, thumb = downloads[0]
        return _send_downloaded_private_media_sequentially(
            acc,
            destination_chat_id,
            item,
            file_path,
            thumb=thumb,
            caption_override=caption_override,
            caption_entities_override=caption_entities_override,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _forward_private_media_group_by_download(
    message, bot, acc, chatid, msg
):
    """Download and re-upload a complete restricted private media group."""
    down_status_file = f"downstatus{message.chat.id}{message.id}.txt"
    smsg = bot.send_message(
        message.chat.id,
        "__⬇️ 正在下载媒体组__",
        reply_to_message_id=message.id,
    )
    dosta = threading.Thread(
        target=downstatus,
        args=(down_status_file, smsg, bot),
        daemon=True,
    )
    dosta.start()

    try:
        group_messages, downloads, work_dir = _download_private_media_group(
            acc,
            chatid,
            msg,
            progress_callback=progress,
            progress_args=[message, "down"],
        )

        if os.path.exists(down_status_file):
            os.remove(down_status_file)
        bot.edit_message_text(smsg.chat.id, smsg.id, "__⬆️ 正在上传媒体组__")
        _send_downloaded_private_media_group(
            bot,
            message.chat.id,
            group_messages,
            downloads,
        )
    finally:
        if os.path.exists(down_status_file):
            os.remove(down_status_file)
        if "work_dir" in locals():
            shutil.rmtree(work_dir, ignore_errors=True)
        bot.delete_messages(message.chat.id, [smsg.id])


def handle_private(message: pyrogram.types.messages_and_media.message.Message, chatid: int, msgid: int):
    """Forward a private message, preferring a server-side copy."""
    bot = get_bot_instance()
    acc = get_acc_instance()

    msg: pyrogram.types.messages_and_media.message.Message = acc.get_messages(chatid, msgid)
    msg_type = get_message_type(msg)

    if "Text" == msg_type:
        bot.send_message(message.chat.id, msg.text, entities=msg.entities)
        return

    try:
        _forward_private_media_direct(bot, acc, chatid, msg)
        logger.info(
            "✅ 消息 %s 已通过缓存媒体直接从私有会话复制到 Bot 会话（未下载）",
            msgid,
        )
        return
    except Exception as exc:
        if isinstance(exc, ChatForwardsRestricted):
            logger.warning(
                "Telegram 拒绝用户账号在受限聊天 %s 中直接复制消息 %s，"
                "尝试 Bot 身份路径",
                chatid,
                msgid,
            )
        logger.warning(
            "用户客户端无法直接复制消息 %s，尝试 Bot 身份路径: %s: %s",
            msgid,
            type(exc).__name__,
            exc,
        )
        if _forward_private_media_via_bot(bot, message.chat.id, chatid, msgid):
            logger.info(
                "✅ 消息 %s 已由 Bot 客户端直接从私有会话复制（未下载）",
                msgid,
            )
            return
        logger.warning(
            "Bot 客户端也无法直接复制消息 %s，回退到下载后重传",
            msgid,
        )

    group_messages = _get_private_media_group_messages(acc, chatid, msg)
    if (
        len(group_messages) > 1
        and _should_forward_private_media_group(message)
    ):
        logger.info(
            "✅ 检测到受限私有媒体组，共 %s 项，开始整组下载后重传",
            len(group_messages),
        )
        _forward_private_media_group_by_download(
            message,
            bot,
            acc,
            chatid,
            msg,
        )
        return

    down_status_file = f"downstatus{message.chat.id}{message.id}.txt"
    up_status_file = f"upstatus{message.chat.id}{message.id}.txt"
    smsg = bot.send_message(message.chat.id, '__⬇️ 下载中__', reply_to_message_id=message.id)
    dosta = threading.Thread(
        target=downstatus,
        args=(down_status_file, smsg, bot),
        daemon=True,
    )
    dosta.start()
    file = acc.download_media(msg, progress=progress, progress_args=[message, "down"])
    if os.path.exists(down_status_file):
        os.remove(down_status_file)

    upsta = threading.Thread(
        target=upstatus,
        args=(up_status_file, smsg, bot),
        daemon=True,
    )
    upsta.start()

    thumb = None

    if "Document" == msg_type:
        try:
            thumb = acc.download_media(msg.document.thumbs[0].file_id)
        except:
            thumb = None

        bot.send_document(message.chat.id, file, thumb=thumb, caption=msg.caption, caption_entities=msg.caption_entities, progress=progress, progress_args=[message, "up"])
        if thumb != None:
            os.remove(thumb)

    elif "Video" == msg_type:
        try:
            thumb = acc.download_media(msg.video.thumbs[0].file_id)
        except:
            thumb = None

        bot.send_video(message.chat.id, file, duration=msg.video.duration, width=msg.video.width, height=msg.video.height, thumb=thumb, caption=msg.caption, caption_entities=msg.caption_entities, progress=progress, progress_args=[message, "up"])
        if thumb != None:
            os.remove(thumb)

    elif "Animation" == msg_type:
        bot.send_animation(message.chat.id, file)

    elif "Sticker" == msg_type:
        bot.send_sticker(message.chat.id, file)

    elif "Voice" == msg_type:
        bot.send_voice(message.chat.id, file, caption=msg.caption, caption_entities=msg.caption_entities, progress=progress, progress_args=[message, "up"])

    elif "Audio" == msg_type:
        try:
            thumb = acc.download_media(msg.audio.thumbs[0].file_id)
        except:
            thumb = None

        bot.send_audio(message.chat.id, file, caption=msg.caption, caption_entities=msg.caption_entities, progress=progress, progress_args=[message, "up"])   
        if thumb != None:
            os.remove(thumb)

    elif "Photo" == msg_type:
        bot.send_photo(message.chat.id, file, caption=msg.caption, caption_entities=msg.caption_entities)

    os.remove(file)
    if os.path.exists(up_status_file):
        os.remove(up_status_file)
    bot.delete_messages(message.chat.id, [smsg.id])
