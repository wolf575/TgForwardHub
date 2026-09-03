"""
Message handlers for the bot
"""
import pyrogram
import re
import os
import time
import threading
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserAlreadyParticipant, InviteHashExpired, UsernameNotOccupied

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

logger = get_logger(__name__)


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

        datas = message.text.split("/")
        temp = datas[-1].replace("?single", "").split("-")
        fromID = int(temp[0].strip())
        try:
            toID = int(temp[1].strip())
        except:
            toID = fromID

        # 统计转发结果
        total_messages = toID - fromID + 1
        success_count = 0
        failed_count = 0
        failed_ids = []

        logger.info(f"📤 开始批量转发: 共 {total_messages} 条消息 (ID: {fromID}-{toID})")

        for msgid in range(fromID, toID+1):

            # private
            if "https://t.me/c/" in message.text:
                chatid = int("-100" + datas[4])

                if acc is None:
                    bot.send_message(message.chat.id, f"**❌ 未设置 String Session**", reply_to_message_id=message.id)
                    return

                try:
                    handle_private(message, chatid, msgid)
                    success_count += 1
                    logger.debug(f"✅ 消息 {msgid} 转发成功 ({success_count}/{total_messages})")
                except Exception as e:
                    failed_count += 1
                    failed_ids.append(msgid)
                    logger.warning(f"⚠️ 消息 {msgid} 转发失败: {type(e).__name__}: {e}")

            # bot
            elif "https://t.me/b/" in message.text:
                username = datas[4]

                if acc is None:
                    bot.send_message(message.chat.id, f"**❌ 未设置 String Session**", reply_to_message_id=message.id)
                    return
                try:
                    handle_private(message, username, msgid)
                    success_count += 1
                    logger.debug(f"✅ 消息 {msgid} 转发成功 ({success_count}/{total_messages})")
                except Exception as e:
                    failed_count += 1
                    failed_ids.append(msgid)
                    logger.warning(f"⚠️ 消息 {msgid} 转发失败: {type(e).__name__}: {e}")

            # public
            else:
                username = datas[3]

                try:
                    msg = bot.get_messages(username, msgid)
                except UsernameNotOccupied:
                    bot.send_message(message.chat.id, f"**❌ 该用户名未被占用**", reply_to_message_id=message.id)
                    return
                copied = False
                use_media_group = (fromID == toID) or ("?single" in message.text)

                try:
                    if use_media_group:
                        bot.copy_media_group(message.chat.id, msg.chat.id, msg.id)
                    else:
                        bot.copy_message(message.chat.id, msg.chat.id, msg.id)
                    copied = True
                except Exception:
                    if use_media_group:
                        try:
                            bot.copy_message(message.chat.id, msg.chat.id, msg.id)
                            copied = True
                        except Exception:
                            copied = False

                if copied:
                    success_count += 1
                    logger.debug(f"✅ 消息 {msgid} 转发成功 ({success_count}/{total_messages})")
                else:
                    if acc is None:
                        bot.send_message(message.chat.id, f"**❌ 未设置 String Session**", reply_to_message_id=message.id)
                        return
                    try:
                        handle_private(message, username, msgid)
                        success_count += 1
                        logger.debug(f"✅ 消息 {msgid} 转发成功 ({success_count}/{total_messages})")
                    except Exception as e:
                        failed_count += 1
                        failed_ids.append(msgid)
                        logger.warning(f"⚠️ 消息 {msgid} 转发失败: {type(e).__name__}: {e}")

            # 减少等待时间，避免超时
            time.sleep(1)

        # 发送转发结果摘要
        if failed_count > 0:
            failed_ids_str = ", ".join(map(str, failed_ids))
            summary = f"📊 **批量转发完成**\n\n✅ 成功: {success_count}/{total_messages}\n❌ 失败: {failed_count}\n\n失败的消息ID: {failed_ids_str}"
            logger.warning(f"批量转发完成: 成功 {success_count}, 失败 {failed_count}, 失败ID: {failed_ids_str}")
        else:
            summary = f"✅ **批量转发完成**\n\n成功转发 {success_count}/{total_messages} 条消息"
            logger.info(f"批量转发完成: 全部成功 ({success_count}/{total_messages})")

        bot.send_message(message.chat.id, summary, reply_to_message_id=message.id)


def handle_private(message: pyrogram.types.messages_and_media.message.Message, chatid: int, msgid: int):
    """Handle private message download and forward"""
    bot = get_bot_instance()
    acc = get_acc_instance()
    
    msg: pyrogram.types.messages_and_media.message.Message = acc.get_messages(chatid, msgid)
    msg_type = get_message_type(msg)

    if "Text" == msg_type:
        bot.send_message(message.chat.id, msg.text, entities=msg.entities)
        return

    smsg = bot.send_message(message.chat.id, '__⬇️ 下载中__', reply_to_message_id=message.id)
    dosta = threading.Thread(target=lambda: downstatus(f'{message.id}downstatus.txt', smsg), daemon=True)
    dosta.start()
    file = acc.download_media(msg, progress=progress, progress_args=[message, "down"])
    os.remove(f'{message.id}downstatus.txt')

    upsta = threading.Thread(target=lambda: upstatus(f'{message.id}upstatus.txt', smsg), daemon=True)
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
    if os.path.exists(f'{message.id}upstatus.txt'):
        os.remove(f'{message.id}upstatus.txt')
    bot.delete_messages(message.chat.id, [smsg.id])
