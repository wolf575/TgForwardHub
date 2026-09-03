#!/usr/bin/env python3
"""
Functional testing for migrated handlers
"""
import sys
import os
from unittest.mock import Mock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🧪 功能测试 - 迁移后的处理器")
print("=" * 70)
print()

# Test 1: Test get_message_type function
print("📝 测试 1: get_message_type 函数")
from bot.utils.helpers import get_message_type

# Create mock messages
msg_text = Mock()
msg_text.text = "Hello"
# Use property that raises AttributeError when accessed
del msg_text.document
del msg_text.video
del msg_text.animation
del msg_text.sticker
del msg_text.voice
del msg_text.audio
del msg_text.photo

result = get_message_type(msg_text)
if result == "Text":
    print("✅ get_message_type 正确识别文本消息")
else:
    print(f"❌ get_message_type 失败: 期望 'Text', 得到 '{result}'")
    sys.exit(1)

# Test photo message
msg_photo = Mock()
msg_photo.photo = Mock()
msg_photo.photo.file_id = "test_id"
del msg_photo.document
del msg_photo.video
del msg_photo.animation
del msg_photo.sticker
del msg_photo.voice
del msg_photo.audio

result = get_message_type(msg_photo)
if result == "Photo":
    print("✅ get_message_type 正确识别图片消息")
else:
    print(f"❌ get_message_type 失败: 期望 'Photo', 得到 '{result}'")
    sys.exit(1)

print("✅ PASSED: get_message_type 函数正常工作")
print()

# Test 2: Test callback_handler exists and is callable
print("📝 测试 2: callback_handler 可调用性")
from bot.handlers.callbacks import callback_handler
import inspect

if callable(callback_handler):
    print("✅ callback_handler 是可调用的")
else:
    print("❌ callback_handler 不可调用")
    sys.exit(1)

sig = inspect.signature(callback_handler)
params = list(sig.parameters.keys())
if len(params) >= 2:
    print(f"✅ callback_handler 有正确的参数数量: {len(params)}")
else:
    print(f"❌ callback_handler 参数数量错误: {len(params)}")
    sys.exit(1)

print("✅ PASSED: callback_handler 可调用")
print()

# Test 3: Test save function exists and is callable
print("📝 测试 3: save 函数可调用性")
from bot.handlers.messages import save

if callable(save):
    print("✅ save 是可调用的")
else:
    print("❌ save 不可调用")
    sys.exit(1)

sig = inspect.signature(save)
params = list(sig.parameters.keys())
if len(params) >= 2:
    print(f"✅ save 有正确的参数数量: {len(params)}")
else:
    print(f"❌ save 参数数量错误: {len(params)}")
    sys.exit(1)

print("✅ PASSED: save 函数可调用")
print()

# Test 4: Test watch_setup functions
print("📝 测试 4: watch_setup 模块函数")
from bot.handlers.watch_setup import (
    show_filter_options,
    show_filter_options_single,
    show_preserve_source_options,
    show_forward_mode_options,
    complete_watch_setup,
    complete_watch_setup_single,
    handle_add_source,
    handle_add_dest
)

functions = [
    show_filter_options,
    show_filter_options_single,
    show_preserve_source_options,
    show_forward_mode_options,
    complete_watch_setup,
    complete_watch_setup_single,
    handle_add_source,
    handle_add_dest,
]

all_callable = True
for func in functions:
    if not callable(func):
        print(f"❌ {func.__name__} 不可调用")
        all_callable = False
    else:
        print(f"✅ {func.__name__} 可调用")

if not all_callable:
    sys.exit(1)

print("✅ PASSED: 所有 watch_setup 函数可调用")
print()

# Test 5: Test bot handlers instance management
print("📝 测试 5: bot handlers 实例管理")
from bot.handlers import (
    set_bot_instance,
    set_acc_instance,
    get_bot_instance,
    get_acc_instance
)

# Test with mock instances
mock_bot = Mock()
mock_acc = Mock()

set_bot_instance(mock_bot)
set_acc_instance(mock_acc)

retrieved_bot = get_bot_instance()
retrieved_acc = get_acc_instance()

if retrieved_bot is mock_bot:
    print("✅ bot 实例正确设置和获取")
else:
    print("❌ bot 实例设置/获取失败")
    sys.exit(1)

if retrieved_acc is mock_acc:
    print("✅ acc 实例正确设置和获取")
else:
    print("❌ acc 实例设置/获取失败")
    sys.exit(1)

print("✅ PASSED: 实例管理正常工作")
print()

# Test 6: Test USAGE constant
print("📝 测试 6: USAGE 常量内容")
from constants import USAGE

required_sections = [
    "公开频道/群组",
    "私有频道/群组",
    "机器人聊天",
    "批量下载",
]

all_sections_found = True
for section in required_sections:
    if section in USAGE:
        print(f"✅ 找到章节: {section}")
    else:
        print(f"❌ 缺少章节: {section}")
        all_sections_found = False

if not all_sections_found:
    sys.exit(1)

print("✅ PASSED: USAGE 常量内容完整")
print()

# Test 7: Test user_states accessibility
print("📝 测试 7: user_states 可访问性")
from bot.utils.status import user_states

if isinstance(user_states, dict):
    print("✅ user_states 是字典类型")
else:
    print(f"❌ user_states 类型错误: {type(user_states)}")
    sys.exit(1)

# Test basic operations
user_states["test_user"] = {"action": "test"}
if user_states.get("test_user") == {"action": "test"}:
    print("✅ user_states 读写操作正常")
else:
    print("❌ user_states 读写操作失败")
    sys.exit(1)

# Cleanup
del user_states["test_user"]
print("✅ PASSED: user_states 可访问且工作正常")
print()

# Test 8: Test config functions
print("📝 测试 8: 配置函数可用性")
from config import load_watch_config, save_watch_config

if callable(load_watch_config):
    print("✅ load_watch_config 可调用")
else:
    print("❌ load_watch_config 不可调用")
    sys.exit(1)

if callable(save_watch_config):
    print("✅ save_watch_config 可调用")
else:
    print("❌ save_watch_config 不可调用")
    sys.exit(1)

print("✅ PASSED: 配置函数可用")
print()

# Summary
print("=" * 70)
print("✅ 所有功能测试通过！")
print("=" * 70)
print()
print("📊 测试总结:")
print("  ✅ get_message_type 函数正常工作")
print("  ✅ callback_handler 可调用")
print("  ✅ save 函数可调用")
print("  ✅ watch_setup 所有函数可调用")
print("  ✅ 实例管理正常工作")
print("  ✅ USAGE 常量内容完整")
print("  ✅ user_states 可访问")
print("  ✅ 配置函数可用")
print()
print("🎉 迁移后的代码功能完整！")
