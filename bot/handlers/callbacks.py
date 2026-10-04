"""
Callback query handlers
"""
import pyrogram
from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import ChannelPrivate, UsernameInvalid
import re

from bot.handlers.instances import get_bot_instance, get_acc_instance
from bot.handlers.watch_setup import (
    show_filter_options, show_filter_options_single,
    show_preserve_source_options, show_forward_mode_options,
    show_dn_append_options,
    complete_watch_setup, complete_watch_setup_single
)
from bot.utils.status import user_states
from config import load_watch_config, save_watch_config


def callback_handler(client: pyrogram.client.Client, callback_query: CallbackQuery):
    """Handle all callback queries"""
    bot = get_bot_instance()
    acc = get_acc_instance()
    
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.id
    user_id = str(callback_query.from_user.id)
    
    try:
        if data == "menu_main":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 监控管理", callback_data="menu_watch")],
                [InlineKeyboardButton("❓ 帮助说明", callback_data="menu_help")],
                [InlineKeyboardButton("🌐 源代码", url="https://github.com/bipinkrish/Save-Restricted-Bot")]
            ])
            
            welcome_text = f"👋 你好 **{callback_query.from_user.mention}**！\n\n"
            welcome_text += "我是受限内容保存机器人，可以帮你：\n\n"
            welcome_text += "📥 **转发消息** - 直接发送 Telegram 链接\n"
            welcome_text += "👁 **监控频道/群组** - 自动转发新消息\n"
            welcome_text += "🔍 **智能过滤** - 关键词、正则表达式过滤\n"
            welcome_text += "🎯 **提取模式** - 提取特定内容转发\n\n"
            welcome_text += "点击下方按钮开始使用 👇"
            
            bot.edit_message_text(chat_id, message_id, welcome_text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "menu_help":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 监控管理", callback_data="menu_watch")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_main")]
            ])
            
            help_text = """**📖 使用帮助**

**📥 转发消息**
直接发送 Telegram 消息链接即可转发内容

**📋 监控功能**
• 点击"监控管理"按钮设置自动转发或记录
• 支持监控频道、群组和收藏夹
• 输入 `me` 可监控自己的收藏夹
• 支持关键词过滤（白名单/黑名单）
• 支持正则表达式过滤
• 支持提取模式（正则提取特定内容）
• 可选择是否保留转发来源
• 📝 支持记录模式（保存到网页笔记）
• 可随时编辑监控设置

**📝 记录模式**
• 将监控内容保存到网页而非转发
• 记录文字、图片和视频封面
• 包含时间戳信息
• 过滤规则和提取模式仍然生效
• 通过 Web 界面查看记录（端口 5000）
• 默认登录账号：admin/admin
• 搜索功能支持高亮显示

**🔗 链接格式**

公开频道/群组：
`https://t.me/username/123`

私有频道/群组（需要先加入）：
`https://t.me/c/123456789/123`

批量转发（范围，`-` 或空格连接均可）：
`https://t.me/username/100-120`
`https://t.me/username/100 120`
`https://t.me/username/100-https://t.me/username/120`
`https://t.me/username/100 https://t.me/username/120`

机器人消息：
`https://t.me/b/botusername/123`

**💡 提示**
• 私有频道需要配置 String Session
• 可以使用 `me` 监控收藏夹或作为目标
• 关键词过滤不区分大小写
• 正则表达式支持完整的 Python re 语法
• 提取模式会将匹配的内容单独发送
• 所有操作都可通过按钮完成，无需记忆复杂命令
• 机器人重启后会自动加载所有配置
"""
            bot.edit_message_text(chat_id, message_id, help_text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "menu_watch":
            if acc is None:
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_main")]])
                bot.edit_message_text(chat_id, message_id, "**❌ 需要配置 String Session 才能使用监控功能**", reply_markup=keyboard)
                callback_query.answer("❌ 需要配置 String Session", show_alert=True)
                return
            
            watch_config = load_watch_config()
            watch_count = len(watch_config.get(user_id, {}))
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ 添加监控", callback_data="watch_add_start")],
                [InlineKeyboardButton(f"📋 查看列表 ({watch_count})", callback_data="watch_list")],
                [InlineKeyboardButton("🗑 删除监控", callback_data="watch_remove_start")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_main")]
            ])
            
            text = "**📋 监控管理**\n\n"
            text += "选择操作：\n\n"
            text += "➕ **添加监控** - 设置新的自动转发任务\n"
            text += "📋 **查看列表** - 查看所有监控任务\n"
            text += "🗑 **删除监控** - 移除现有监控任务\n\n"
            text += f"当前监控任务数：**{watch_count}** 个"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "watch_add_start":
            user_states[user_id] = {"action": "add_source"}
            
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]])
            
            text = "**➕ 添加监控任务**\n\n"
            text += "**步骤 1/2：** 请发送来源频道/群组\n\n"
            text += "可以发送：\n"
            text += "• 输入 `me` 监控自己的收藏夹\n"
            text += "• 频道/群组用户名（如 `@channel_name`）\n"
            text += "• 频道/群组ID（如 `-1001234567890`）\n"
            text += "• 转发一条来自该频道/群组的消息\n\n"
            text += "💡 机器人需要能够访问该频道/群组"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "watch_list":
            watch_config = load_watch_config()
            
            if user_id not in watch_config or not watch_config[user_id]:
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="menu_watch")]])
                bot.edit_message_text(chat_id, message_id, "**📋 监控列表**\n\n暂无监控任务\n\n点击\"添加监控\"开始设置", reply_markup=keyboard)
                callback_query.answer("暂无监控任务")
                return
            
            buttons = []
            for idx, (watch_key, watch_data) in enumerate(watch_config[user_id].items(), 1):
                if isinstance(watch_data, dict):
                    # New format with source|dest key
                    source = watch_data.get("source", watch_key.split("|")[0] if "|" in watch_key else watch_key)
                    dest = watch_data.get("dest", watch_key.split("|")[1] if "|" in watch_key else "unknown")
                    record_mode = watch_data.get("record_mode", False)
                else:
                    # Old format compatibility
                    source = watch_key
                    dest = watch_data
                    record_mode = False

                # Handle None values
                if source is None:
                    source = "未知来源"
                if dest is None or record_mode:
                    dest = "网页笔记"

                # Truncate source and dest for button display
                source_display = source if len(source) <= 15 else source[:12] + "..."
                dest_display = dest if len(dest) <= 15 else dest[:12] + "..."

                buttons.append([InlineKeyboardButton(f"{idx}. {source_display} ➡️ {dest_display}", callback_data=f"watch_view_{idx}")])
            
            buttons.append([InlineKeyboardButton("🔙 返回", callback_data="menu_watch")])
            keyboard = InlineKeyboardMarkup(buttons)
            
            text = "**📋 监控任务列表**\n\n"
            text += f"共 **{len(watch_config[user_id])}** 个监控任务\n\n"
            text += "点击任务查看详情和编辑 👇"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "watch_remove_start":
            watch_config = load_watch_config()
            
            if user_id not in watch_config or not watch_config[user_id]:
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="menu_watch")]])
                bot.edit_message_text(chat_id, message_id, "**🗑 删除监控**\n\n暂无监控任务可删除", reply_markup=keyboard)
                callback_query.answer("暂无监控任务")
                return
            
            buttons = []
            for idx, (watch_key, watch_data) in enumerate(watch_config[user_id].items(), 1):
                if isinstance(watch_data, dict):
                    # New format with source|dest key
                    source = watch_data.get("source", watch_key.split("|")[0] if "|" in watch_key else watch_key)
                    dest = watch_data.get("dest", watch_key.split("|")[1] if "|" in watch_key else "unknown")
                    record_mode = watch_data.get("record_mode", False)
                else:
                    # Old format compatibility
                    source = watch_key
                    dest = watch_data
                    record_mode = False

                # Handle None values
                if source is None:
                    source = "未知来源"
                if dest is None or record_mode:
                    dest = "网页笔记"

                buttons.append([InlineKeyboardButton(f"🗑 {idx}. {source} ➡️ {dest}", callback_data=f"watch_remove_{idx}")])
            
            buttons.append([InlineKeyboardButton("❌ 取消", callback_data="menu_watch")])
            keyboard = InlineKeyboardMarkup(buttons)
            
            text = "**🗑 删除监控**\n\n"
            text += "选择要删除的监控任务："
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data.startswith("watch_view_"):
            task_id = int(data.split("_")[2])
            watch_config = load_watch_config()
            
            if user_id not in watch_config or not watch_config[user_id]:
                callback_query.answer("❌ 监控任务不存在", show_alert=True)
                return
            
            if task_id < 1 or task_id > len(watch_config[user_id]):
                callback_query.answer("❌ 任务编号无效", show_alert=True)
                return
            
            watch_key = list(watch_config[user_id].keys())[task_id - 1]
            watch_data = watch_config[user_id][watch_key]
            
            if isinstance(watch_data, dict):
                # New format with source|dest key
                source_id = watch_data.get("source", watch_key.split("|")[0] if "|" in watch_key else watch_key)
                dest = watch_data.get("dest", watch_key.split("|")[1] if "|" in watch_key else "unknown")
                whitelist = watch_data.get("whitelist", [])
                blacklist = watch_data.get("blacklist", [])
                whitelist_regex = watch_data.get("whitelist_regex", [])
                blacklist_regex = watch_data.get("blacklist_regex", [])
                preserve_source = watch_data.get("preserve_forward_source", False)
                forward_mode = watch_data.get("forward_mode", "full")
                extract_patterns = watch_data.get("extract_patterns", [])
                record_mode = watch_data.get("record_mode", False)
            else:
                # Old format compatibility
                source_id = watch_key
                dest = watch_data
                whitelist = []
                blacklist = []
                whitelist_regex = []
                blacklist_regex = []
                preserve_source = False
                forward_mode = "full"
                extract_patterns = []
                record_mode = False
            
            # Handle None values
            if source_id is None:
                source_id = "未知来源"
            if dest is None:
                dest = "未知目标"
            
            text = f"**📋 监控任务详情**\n\n"
            text += f"**来源：** `{source_id}`\n"
            
            if record_mode:
                text += f"**模式：** 📝 记录模式（保存到网页）\n\n"
            else:
                text += f"**目标：** `{dest}`\n\n"
                text += f"**转发模式：** {'🎯 提取模式' if forward_mode == 'extract' else '📦 完整转发'}\n"
                if preserve_source:
                    text += f"**保留来源：** ✅ 是\n"
                else:
                    text += f"**保留来源：** ❌ 否\n"
            
            text += "\n**过滤规则：**\n"
            if whitelist:
                text += f"🟢 关键词白名单: `{', '.join(whitelist)}`\n"
            if blacklist:
                text += f"🔴 关键词黑名单: `{', '.join(blacklist)}`\n"
            if whitelist_regex:
                text += f"🟢 正则白名单: `{', '.join(whitelist_regex)}`\n"
            if blacklist_regex:
                text += f"🔴 正则黑名单: `{', '.join(blacklist_regex)}`\n"
            if not (whitelist or blacklist or whitelist_regex or blacklist_regex):
                text += "⏭ 无过滤（转发所有消息）\n"
            
            if forward_mode == "extract" and extract_patterns:
                text += f"\n**提取规则：**\n"
                for pattern in extract_patterns:
                    text += f"• `{pattern}`\n"
            
            buttons = [[InlineKeyboardButton("✏️ 编辑过滤规则", callback_data=f"edit_filter_{task_id}")]]

            if not record_mode:
                buttons.append([InlineKeyboardButton("📤 切换保留来源", callback_data=f"edit_preserve_{task_id}")])

            buttons.append([InlineKeyboardButton("🗑 删除此监控", callback_data=f"watch_remove_{task_id}")])
            buttons.append([InlineKeyboardButton("🔙 返回列表", callback_data="watch_list")])
            
            keyboard = InlineKeyboardMarkup(buttons)
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data.startswith("watch_remove_"):
            task_id = int(data.split("_")[2])
            watch_config = load_watch_config()
            
            if user_id not in watch_config or not watch_config[user_id]:
                callback_query.answer("❌ 监控任务不存在", show_alert=True)
                return
            
            if task_id < 1 or task_id > len(watch_config[user_id]):
                callback_query.answer("❌ 任务编号无效", show_alert=True)
                return
            
            watch_key = list(watch_config[user_id].keys())[task_id - 1]
            watch_data = watch_config[user_id][watch_key]

            if isinstance(watch_data, dict):
                # New format with source|dest key
                source_id = watch_data.get("source", watch_key.split("|")[0] if "|" in watch_key else watch_key)
                dest_id = watch_data.get("dest", watch_key.split("|")[1] if "|" in watch_key else "unknown")
                record_mode = watch_data.get("record_mode", False)
            else:
                # Old format compatibility
                source_id = watch_key
                dest_id = watch_data
                record_mode = False

            # Handle None values
            if source_id is None:
                source_id = "未知来源"
            if dest_id is None or record_mode:
                dest_id = "网页笔记"

            del watch_config[user_id][watch_key]
            
            if not watch_config[user_id]:
                del watch_config[user_id]
            
            save_watch_config(watch_config)
            
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回监控管理", callback_data="menu_watch")]])
            text = f"**✅ 监控任务已删除**\n\n来源：`{source_id}`\n目标：`{dest_id}`"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer("✅ 删除成功")
        
        elif data.startswith("set_dest_"):
            dest_choice = data.split("_")[2]
            
            if user_id not in user_states or "source_id" not in user_states[user_id]:
                callback_query.answer("❌ 会话已过期，请重新开始", show_alert=True)
                return
            
            if dest_choice == "me":
                user_states[user_id]["dest_id"] = "me"
                user_states[user_id]["dest_name"] = "个人收藏"
            
            show_filter_options(chat_id, message_id, user_id)
            callback_query.answer()
        
        elif data == "mode_single":
            if user_id not in user_states or "source_id" not in user_states[user_id]:
                callback_query.answer("❌ 会话已过期，请重新开始", show_alert=True)
                return
            
            user_states[user_id]["dest_id"] = None
            user_states[user_id]["dest_name"] = "记录模式"
            user_states[user_id]["record_mode"] = True
            
            show_filter_options_single(chat_id, message_id, user_id)
            callback_query.answer()
        
        elif data == "mode_forward":
            if user_id not in user_states or "source_id" not in user_states[user_id]:
                callback_query.answer("❌ 会话已过期，请重新开始", show_alert=True)
                return
            
            user_states[user_id]["action"] = "choose_dest"
            user_states[user_id]["record_mode"] = False
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💾 保存到收藏夹", callback_data="set_dest_me")],
                [InlineKeyboardButton("📤 自定义目标", callback_data="dest_custom")],
                [InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]
            ])
            
            source_name = user_states[user_id].get("source_name", "未知")
            
            text = "**➕ 添加监控任务**\n\n"
            text += f"✅ 来源已设置：`{source_name}`\n\n"
            text += "**步骤 3：** 选择转发目标\n\n"
            text += "💾 **保存到收藏夹** - 转发到你的个人收藏\n"
            text += "📤 **自定义目标** - 转发到其他频道/群组"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "dest_custom":
            user_states[user_id]["action"] = "add_dest"
            
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]])
            
            text = "**➕ 添加监控任务**\n\n"
            text += "**步骤 3：** 请发送目标频道/群组\n\n"
            text += "可以发送：\n"
            text += "• 频道/群组用户名（如 `@channel_name`）\n"
            text += "• 频道/群组ID（如 `-1001234567890`）\n"
            text += "• 转发一条来自该频道/群组的消息\n\n"
            text += "💡 机器人需要有发送消息的权限"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "filter_none":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return
            
            user_states[user_id]["whitelist"] = []
            user_states[user_id]["blacklist"] = []
            user_states[user_id]["whitelist_regex"] = []
            user_states[user_id]["blacklist_regex"] = []
            show_preserve_source_options(chat_id, message_id, user_id)
            callback_query.answer()
        
        elif data == "filter_none_single":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return
            
            user_states[user_id]["whitelist"] = []
            user_states[user_id]["blacklist"] = []
            user_states[user_id]["whitelist_regex"] = []
            user_states[user_id]["blacklist_regex"] = []
            
            msg = bot.send_message(chat_id, "⏳ 正在完成设置...")
            bot.delete_messages(chat_id, [message_id])
            complete_watch_setup_single(msg.chat.id, msg.id, user_id, [], [], [], [])
            callback_query.answer()
        
        elif data == "filter_done":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return
            
            # Continue to next step (preserve source options)
            show_preserve_source_options(chat_id, message_id, user_id)
            callback_query.answer("✅ 过滤规则已保存")
        
        elif data == "filter_done_single":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return
            
            whitelist = user_states[user_id].get("whitelist", [])
            blacklist = user_states[user_id].get("blacklist", [])
            whitelist_regex = user_states[user_id].get("whitelist_regex", [])
            blacklist_regex = user_states[user_id].get("blacklist_regex", [])
            
            msg = bot.send_message(chat_id, "⏳ 正在完成设置...")
            bot.delete_messages(chat_id, [message_id])
            complete_watch_setup_single(msg.chat.id, msg.id, user_id, whitelist, blacklist, whitelist_regex, blacklist_regex)
            callback_query.answer("✅ 过滤规则已保存")
        
        elif data == "clear_filters":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return
            
            # Clear all filter rules
            user_states[user_id]["whitelist"] = []
            user_states[user_id]["blacklist"] = []
            user_states[user_id]["whitelist_regex"] = []
            user_states[user_id]["blacklist_regex"] = []
            
            # Refresh the menu to show cleared filters
            show_filter_options(chat_id, message_id, user_id)
            callback_query.answer("✅ 已清空所有过滤规则")
        
        elif data == "clear_filters_single":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return
            
            # Clear all filter rules
            user_states[user_id]["whitelist"] = []
            user_states[user_id]["blacklist"] = []
            user_states[user_id]["whitelist_regex"] = []
            user_states[user_id]["blacklist_regex"] = []
            
            # Refresh the menu to show cleared filters
            show_filter_options_single(chat_id, message_id, user_id)
            callback_query.answer("✅ 已清空所有过滤规则")
        
        elif data == "filter_regex_whitelist":
            user_states[user_id]["action"] = "add_regex_whitelist"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ 跳过", callback_data="skip_regex_whitelist")],
                [InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]
            ])
            
            text = "**➕ 添加监控任务**\n\n"
            text += "**步骤 3：设置正则白名单**\n\n"
            text += "请发送正则表达式，用逗号分隔\n\n"
            text += "示例：`https?://[^\\s]+,\\d{6,}`\n\n"
            text += "💡 只有匹配这些正则的消息才会被转发"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "filter_regex_blacklist":
            user_states[user_id]["action"] = "add_regex_blacklist"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ 跳过", callback_data="skip_regex_blacklist")],
                [InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]
            ])
            
            text = "**➕ 添加监控任务**\n\n"
            text += "**步骤 3：设置正则黑名单**\n\n"
            text += "请发送正则表达式，用逗号分隔\n\n"
            text += "示例：`广告|推广|垃圾`\n\n"
            text += "💡 匹配这些正则的消息不会被转发"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "skip_regex_whitelist":
            if user_id in user_states:
                user_states[user_id]["whitelist_regex"] = []
                msg = bot.send_message(chat_id, "⏳ 继续设置...")
                if user_states[user_id].get("record_mode"):
                    show_filter_options_single(chat_id, msg.id, user_id)
                else:
                    show_filter_options(chat_id, msg.id, user_id)
                bot.delete_messages(chat_id, [message_id])
                callback_query.answer("已跳过正则白名单")
        
        elif data == "skip_regex_blacklist":
            if user_id in user_states:
                user_states[user_id]["blacklist_regex"] = []
                msg = bot.send_message(chat_id, "⏳ 继续设置...")
                if user_states[user_id].get("record_mode"):
                    show_filter_options_single(chat_id, msg.id, user_id)
                else:
                    show_filter_options(chat_id, msg.id, user_id)
                bot.delete_messages(chat_id, [message_id])
                callback_query.answer("已跳过正则黑名单")
        
        elif data == "filter_whitelist":
            user_states[user_id]["action"] = "add_whitelist"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ 跳过", callback_data="skip_whitelist")],
                [InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]
            ])
            
            text = "**➕ 添加监控任务**\n\n"
            text += "**步骤 3：设置白名单**\n\n"
            text += "请发送白名单关键词，用逗号分隔\n\n"
            text += "示例：`重要,紧急,通知`\n\n"
            text += "💡 只有包含这些关键词的消息才会被转发"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "filter_blacklist":
            user_states[user_id]["action"] = "add_blacklist"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ 跳过", callback_data="skip_blacklist")],
                [InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]
            ])
            
            text = "**➕ 添加监控任务**\n\n"
            text += "**步骤 3：设置黑名单**\n\n"
            text += "请发送黑名单关键词，用逗号分隔\n\n"
            text += "示例：`广告,推广,垃圾`\n\n"
            text += "💡 包含这些关键词的消息不会被转发"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data == "skip_whitelist":
            if user_id in user_states:
                user_states[user_id]["whitelist"] = []
                msg = bot.send_message(chat_id, "⏳ 继续设置...")
                if user_states[user_id].get("record_mode"):
                    show_filter_options_single(chat_id, msg.id, user_id)
                else:
                    show_filter_options(chat_id, msg.id, user_id)
                bot.delete_messages(chat_id, [message_id])
                callback_query.answer("已跳过关键词白名单")
        
        elif data == "skip_blacklist":
            if user_id in user_states:
                user_states[user_id]["blacklist"] = []
                msg = bot.send_message(chat_id, "⏳ 继续设置...")
                if user_states[user_id].get("record_mode"):
                    show_filter_options_single(chat_id, msg.id, user_id)
                else:
                    show_filter_options(chat_id, msg.id, user_id)
                bot.delete_messages(chat_id, [message_id])
                callback_query.answer("已跳过关键词黑名单")
        
        elif data.startswith("preserve_"):
            preserve = data.split("_")[1] == "yes"
            
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return
            
            whitelist = user_states[user_id].get("whitelist", [])
            blacklist = user_states[user_id].get("blacklist", [])
            whitelist_regex = user_states[user_id].get("whitelist_regex", [])
            blacklist_regex = user_states[user_id].get("blacklist_regex", [])
            
            # Show forward mode selection
            show_forward_mode_options(chat_id, message_id, user_id, whitelist, blacklist, whitelist_regex, blacklist_regex, preserve)
            callback_query.answer()
        
        elif data.startswith("edit_preserve_"):
            task_id = int(data.split("_")[2])
            watch_config = load_watch_config()
            
            if user_id not in watch_config or not watch_config[user_id]:
                callback_query.answer("❌ 监控任务不存在", show_alert=True)
                return
            
            if task_id < 1 or task_id > len(watch_config[user_id]):
                callback_query.answer("❌ 任务编号无效", show_alert=True)
                return
            
            watch_key = list(watch_config[user_id].keys())[task_id - 1]
            
            if isinstance(watch_config[user_id][watch_key], dict):
                current_preserve = watch_config[user_id][watch_key].get("preserve_forward_source", False)
                watch_config[user_id][watch_key]["preserve_forward_source"] = not current_preserve
            else:
                # Old format compatibility - convert to new format
                old_dest = watch_config[user_id][watch_key]
                source_id = watch_key
                watch_config[user_id][watch_key] = {
                    "source": source_id,
                    "dest": old_dest,
                    "whitelist": [],
                    "blacklist": [],
                    "preserve_forward_source": True
                }
            
            save_watch_config(watch_config)
            
            # Refresh the view
            callback_query.data = f"watch_view_{task_id}"
            callback_handler(client, callback_query)
            return
        
        elif data.startswith("edit_filter_"):
            task_id = int(data.split("_")[2])
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🟢 修改关键词白名单", callback_data=f"editf_kw_white_{task_id}")],
                [InlineKeyboardButton("🔴 修改关键词黑名单", callback_data=f"editf_kw_black_{task_id}")],
                [InlineKeyboardButton("🟢 修改正则白名单", callback_data=f"editf_re_white_{task_id}")],
                [InlineKeyboardButton("🔴 修改正则黑名单", callback_data=f"editf_re_black_{task_id}")],
                [InlineKeyboardButton("🎯 修改提取规则", callback_data=f"editf_extract_{task_id}")],
                [InlineKeyboardButton("🔙 返回", callback_data=f"watch_view_{task_id}")]
            ])
            
            text = "**✏️ 编辑过滤规则**\n\n"
            text += "选择要修改的规则：\n\n"
            text += "🟢 **关键词白名单** - 包含关键词才转发\n"
            text += "🔴 **关键词黑名单** - 包含关键词不转发\n"
            text += "🟢 **正则白名单** - 匹配正则才转发\n"
            text += "🔴 **正则黑名单** - 匹配正则不转发\n"
            text += "🎯 **提取规则** - 提取模式的正则表达式"
            
            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()
        
        elif data.startswith("editf_"):
            parts = data.split("_")
            filter_type = parts[1]

            # Handle different callback formats
            if filter_type == "extract":
                # Format: editf_extract_{task_id}
                color = None
                task_id = int(parts[2])
            else:
                # Format: editf_kw_white_{task_id} or editf_re_black_{task_id}
                color = parts[2]
                task_id = int(parts[3])

            user_states[user_id] = {
                "action": f"edit_filter_{filter_type}_{color}" if color else f"edit_filter_{filter_type}",
                "task_id": task_id
            }

            watch_config = load_watch_config()
            watch_key = list(watch_config[user_id].keys())[task_id - 1]
            user_states[user_id]["watch_key"] = watch_key

            # Build keyboard based on filter type
            if filter_type == "extract":
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 清空", callback_data=f"clear_filter_extract_{task_id}")],
                    [InlineKeyboardButton("❌ 取消", callback_data=f"watch_view_{task_id}")]
                ])
            else:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 清空", callback_data=f"clear_filter_{filter_type}_{color}_{task_id}")],
                    [InlineKeyboardButton("❌ 取消", callback_data=f"watch_view_{task_id}")]
                ])

            if filter_type == "kw":
                filter_name = "关键词白名单" if color == "white" else "关键词黑名单"
                example = "重要,紧急,通知" if color == "white" else "广告,推广,垃圾"
            elif filter_type == "re":
                filter_name = "正则白名单" if color == "white" else "正则黑名单"
                example = "https?://[^\\s]+,\\d{6,}" if color == "white" else "广告|推广"
            else:  # extract
                filter_name = "提取规则"
                example = "https?://[^\\s]+,\\d{6,}"

            text = f"**✏️ 修改{filter_name}**\n\n"
            text += f"请发送新的规则，用逗号分隔\n\n"
            text += f"示例：`{example}`\n\n"
            text += "💡 发送新规则将覆盖原有规则\n"
            text += "💡 点击\"清空\"可删除所有规则"

            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer("请输入新规则")
        
        elif data.startswith("clear_filter_"):
            parts = data.split("_")

            # Handle different callback formats
            if parts[2] == "extract":
                # Format: clear_filter_extract_{task_id}
                filter_type = "extract"
                color = None
                task_id = int(parts[3])
            else:
                # Format: clear_filter_kw_white_{task_id} or clear_filter_re_black_{task_id}
                filter_type = parts[2]
                color = parts[3]
                task_id = int(parts[4])

            watch_config = load_watch_config()

            if user_id not in watch_config or not watch_config[user_id]:
                callback_query.answer("❌ 监控任务不存在", show_alert=True)
                return

            if task_id < 1 or task_id > len(watch_config[user_id]):
                callback_query.answer("❌ 任务编号无效", show_alert=True)
                return

            watch_key = list(watch_config[user_id].keys())[task_id - 1]

            if isinstance(watch_config[user_id][watch_key], dict):
                if filter_type == "kw":
                    key = "whitelist" if color == "white" else "blacklist"
                elif filter_type == "re":
                    key = "whitelist_regex" if color == "white" else "blacklist_regex"
                else:  # extract
                    key = "extract_patterns"

                watch_config[user_id][watch_key][key] = []
                save_watch_config(watch_config)

                callback_query.answer("✅ 已清空")
            
            # Refresh the view
            callback_query.data = f"watch_view_{task_id}"
            callback_handler(client, callback_query)
            return
        
        elif data == "watch_mode_record":
            # 选择记录模式
            if user_id not in user_states or "source_id" not in user_states[user_id]:
                callback_query.answer("❌ 会话已过期，请重新开始", show_alert=True)
                return

            user_states[user_id]["dest_id"] = None
            user_states[user_id]["dest_name"] = "网页笔记"
            user_states[user_id]["record_mode"] = True

            show_filter_options_single(chat_id, message_id, user_id)
            callback_query.answer()

        elif data == "watch_mode_forward":
            # 选择转发模式
            if user_id not in user_states or "source_id" not in user_states[user_id]:
                callback_query.answer("❌ 会话已过期，请重新开始", show_alert=True)
                return

            user_states[user_id]["action"] = "add_dest"
            user_states[user_id]["record_mode"] = False

            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]])

            source_name = user_states[user_id].get("source_name", "未知")

            text = "**➕ 添加监控任务**\n\n"
            text += f"✅ 来源已设置：`{source_name}`\n\n"
            text += "**步骤 3：** 请输入转发目标\n\n"
            text += "可以输入：\n"
            text += "• `me` - 转发到你的收藏夹\n"
            text += "• 频道/群组用户名（如 `@channel_name`）\n"
            text += "• 频道/群组ID（如 `-1001234567890`）\n"
            text += "• 转发一条来自目标频道/群组的消息\n\n"
            text += "💡 输入 `me` 表示转发到收藏夹"

            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer()

        elif data.startswith("fwdmode_"):
            mode = data.split("_")[1]

            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return

            if mode == "extract":
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📝 自定义提取", callback_data="extract_custom")],
                    [InlineKeyboardButton("🧲 磁力链接提取", callback_data="extract_magnet")],
                    [InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]
                ])

                text = "**➕ 添加监控任务**\n\n"
                text += "**选择提取类型：**\n\n"
                text += "📝 **自定义提取** - 使用正则表达式提取\n"
                text += "🧲 **磁力链接提取** - 自动提取磁力链接并补全 dn 参数"

                bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
                callback_query.answer()
            else:
                # 完整转发模式，显示DN补全选项
                show_dn_append_options(chat_id, message_id, user_id, "full")
                callback_query.answer()

        elif data == "extract_custom":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return

            user_states[user_id]["action"] = "add_extract_patterns"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ 取消", callback_data="menu_watch")]
            ])

            text = "**➕ 添加监控任务**\n\n"
            text += "**设置提取规则**\n\n"
            text += "请发送提取用的正则表达式，用逗号分隔\n\n"
            text += "示例：`https?://[^\\s]+,\\d{6,}`\n\n"
            text += "💡 消息匹配过滤规则后，将使用这些正则提取内容并转发"

            bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
            callback_query.answer("请输入提取规则")

        elif data == "extract_magnet":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return

            whitelist = user_states[user_id].get("whitelist", [])
            blacklist = user_states[user_id].get("blacklist", [])
            whitelist_regex = user_states[user_id].get("whitelist_regex", [])
            blacklist_regex = user_states[user_id].get("blacklist_regex", [])
            preserve_source = user_states[user_id].get("preserve_source", False)

            magnet_pattern = r'magnet:\?xt=urn:btih:[a-zA-Z0-9]+(?:[&?][^\n\r|]*)?'
            complete_watch_setup(chat_id, message_id, user_id, whitelist, blacklist, whitelist_regex, blacklist_regex, preserve_source, "extract", [magnet_pattern])
            callback_query.answer("✅ 监控已添加")

        elif data == "dn_append_yes":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return

            whitelist = user_states[user_id].get("whitelist", [])
            blacklist = user_states[user_id].get("blacklist", [])
            whitelist_regex = user_states[user_id].get("whitelist_regex", [])
            blacklist_regex = user_states[user_id].get("blacklist_regex", [])
            preserve_source = user_states[user_id].get("preserve_source", False)
            forward_mode = user_states[user_id].get("forward_mode", "full")

            complete_watch_setup(chat_id, message_id, user_id, whitelist, blacklist, whitelist_regex, blacklist_regex, preserve_source, forward_mode, [], append_dn=True)
            callback_query.answer("✅ 监控已添加")

        elif data == "dn_append_no":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return

            whitelist = user_states[user_id].get("whitelist", [])
            blacklist = user_states[user_id].get("blacklist", [])
            whitelist_regex = user_states[user_id].get("whitelist_regex", [])
            blacklist_regex = user_states[user_id].get("blacklist_regex", [])
            preserve_source = user_states[user_id].get("preserve_source", False)
            forward_mode = user_states[user_id].get("forward_mode", "full")

            complete_watch_setup(chat_id, message_id, user_id, whitelist, blacklist, whitelist_regex, blacklist_regex, preserve_source, forward_mode, [], append_dn=False)
            callback_query.answer("✅ 监控已添加")

        elif data == "back_to_forward_mode":
            if user_id not in user_states:
                callback_query.answer("❌ 会话已过期", show_alert=True)
                return

            whitelist = user_states[user_id].get("whitelist", [])
            blacklist = user_states[user_id].get("blacklist", [])
            whitelist_regex = user_states[user_id].get("whitelist_regex", [])
            blacklist_regex = user_states[user_id].get("blacklist_regex", [])
            preserve_source = user_states[user_id].get("preserve_source", False)

            # 使用已导入的函数，不需要重复导入
            show_forward_mode_options(chat_id, message_id, user_id, whitelist, blacklist, whitelist_regex, blacklist_regex, preserve_source)
            callback_query.answer()
        
    except Exception as e:
        print(f"Callback error: {e}")
        callback_query.answer(f"❌ 错误: {str(e)}", show_alert=True)

