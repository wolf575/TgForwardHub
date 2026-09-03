"""
Command handlers for /start, /help, /watch commands
"""
import pyrogram
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging

from config import load_watch_config

logger = logging.getLogger(__name__)


def register_command_handlers(bot, acc):
    """Register all command handlers"""
    
    @bot.on_message(filters.command(["start"]))
    def send_start(client: pyrogram.client.Client, message: pyrogram.types.messages_and_media.message.Message):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 监控管理", callback_data="menu_watch")],
            [InlineKeyboardButton("❓ 帮助说明", callback_data="menu_help")],
            [InlineKeyboardButton("🌐 源代码", url="https://github.com/bipinkrish/Save-Restricted-Bot")]
        ])
        
        welcome_text = f"👋 你好 **{message.from_user.mention}**！\n\n"
        welcome_text += "我是受限内容保存机器人，可以帮你：\n\n"
        welcome_text += "📥 **转发消息** - 直接发送 Telegram 链接\n"
        welcome_text += "👁 **监控频道/群组** - 自动转发新消息\n"
        welcome_text += "🔍 **智能过滤** - 关键词、正则表达式过滤\n"
        welcome_text += "🎯 **提取模式** - 提取特定内容转发\n\n"
        welcome_text += "点击下方按钮开始使用 👇"
        
        bot.send_message(message.chat.id, welcome_text, reply_markup=keyboard, reply_to_message_id=message.id)
    
    @bot.on_message(filters.command(["help"]))
    def send_help(client: pyrogram.client.Client, message: pyrogram.types.messages_and_media.message.Message):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 监控管理", callback_data="menu_watch")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_main")]
        ])
        
        help_text = """**📖 使用帮助**

**📥 转发消息**
直接发送 Telegram 消息链接即可转发内容

**📋 监控功能**
• 点击"监控管理"按钮设置自动转发
• 支持监控频道和群组
• 支持关键词过滤（白名单/黑名单）
• 支持正则表达式过滤
• 支持提取模式（正则提取特定内容）
• 可选择是否保留转发来源
• 可随时编辑监控设置

**🔗 链接格式**

公开频道/群组：
`https://t.me/username/123`

私有频道/群组（需要先加入）：
`https://t.me/c/123456789/123`

批量下载（范围）：
`https://t.me/username/100-120`

机器人消息：
`https://t.me/b/botusername/123`

**💡 提示**
• 私有频道需要配置 String Session
• 可以使用"me"作为目标保存到收藏夹
• 关键词过滤不区分大小写
• 正则表达式支持完整的 Python re 语法
• 提取模式会将匹配的内容单独发送
• 所有操作都可通过按钮完成，无需记忆复杂命令
"""
        bot.send_message(message.chat.id, help_text, reply_markup=keyboard, reply_to_message_id=message.id)
    
    @bot.on_message(filters.command(["watch"]))
    def watch_command(client: pyrogram.client.Client, message: pyrogram.types.messages_and_media.message.Message):
        if acc is None:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_main")]])
            bot.send_message(message.chat.id, "**❌ 需要配置 String Session 才能使用监控功能**", reply_markup=keyboard, reply_to_message_id=message.id)
            return
        
        show_watch_menu(message.chat.id, message.id)


def show_watch_menu(chat_id, reply_to_message_id=None):
    """Show watch menu"""
    from bot.handlers import get_bot_instance
    bot = get_bot_instance()
    
    watch_config = load_watch_config()
    user_id = str(chat_id)
    
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
    
    bot.send_message(chat_id, text, reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
