#!/usr/bin/env python3
"""
Test main.py syntax and imports without actually starting the bot
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test all imports"""
    print("="*70)
    print("测试 main.py 导入和语法")
    print("="*70)
    print()
    
    errors = []
    
    # Test constants
    print("📦 测试 constants.py 导入...")
    try:
        import constants
        print("   ✅ constants 导入成功")
        print(f"   - MAX_RETRIES: {constants.MAX_RETRIES}")
        print(f"   - MAX_MEDIA_GROUP_CACHE: {constants.MAX_MEDIA_GROUP_CACHE}")
    except Exception as e:
        errors.append(f"constants 导入失败: {e}")
        print(f"   ❌ 失败: {e}")
    
    # Test config
    print("\n📦 测试 config.py 导入...")
    try:
        from config import load_config, getenv, DATA_DIR, CONFIG_DIR, MEDIA_DIR
        print("   ✅ config 导入成功")
        print(f"   - DATA_DIR: {DATA_DIR}")
    except Exception as e:
        errors.append(f"config 导入失败: {e}")
        print(f"   ❌ 失败: {e}")
    
    # Test database
    print("\n📦 测试 database.py 导入...")
    try:
        from database import get_db_connection, add_note
        print("   ✅ database 导入成功")
        print("   - get_db_connection: 可用")
        print("   - add_note: 可用")
    except Exception as e:
        errors.append(f"database 导入失败: {e}")
        print(f"   ❌ 失败: {e}")
    
    # Test bot.utils.dedup
    print("\n📦 测试 bot/utils/dedup.py 导入...")
    try:
        from bot.utils.dedup import (
            is_message_processed, mark_message_processed,
            is_media_group_processed, register_processed_media_group
        )
        print("   ✅ bot.utils.dedup 导入成功")
    except Exception as e:
        errors.append(f"bot.utils.dedup 导入失败: {e}")
        print(f"   ❌ 失败: {e}")
    
    # Test bot.workers
    print("\n📦 测试 bot/workers/message_worker.py 导入...")
    try:
        from bot.workers import MessageWorker, Message
        print("   ✅ bot.workers 导入成功")
        print("   - MessageWorker: 可用")
        print("   - Message: 可用")
    except Exception as e:
        errors.append(f"bot.workers 导入失败: {e}")
        print(f"   ❌ 失败: {e}")
    
    # Test bot.handlers
    print("\n📦 测试 bot/handlers 导入...")
    try:
        from bot.handlers import set_bot_instance, set_acc_instance
        print("   ✅ bot.handlers 导入成功")
    except Exception as e:
        errors.append(f"bot.handlers 导入失败: {e}")
        print(f"   ❌ 失败: {e}")
    
    # Test bot.filters
    print("\n📦 测试 bot/filters 导入...")
    try:
        from bot.filters import (
            check_whitelist, check_blacklist,
            check_whitelist_regex, check_blacklist_regex,
            extract_content
        )
        print("   ✅ bot.filters 导入成功")
    except Exception as e:
        errors.append(f"bot.filters 导入失败: {e}")
        print(f"   ❌ 失败: {e}")
    
    # Test main syntax (without running)
    print("\n📦 测试 main.py 语法...")
    try:
        import py_compile
        py_compile.compile('main.py', doraise=True)
        print("   ✅ main.py 语法检查通过")
    except Exception as e:
        errors.append(f"main.py 语法错误: {e}")
        print(f"   ❌ 失败: {e}")
    
    # Summary
    print("\n" + "="*70)
    print("测试总结")
    print("="*70)
    
    if not errors:
        print("✅ 所有导入和语法检查通过！")
        print("\n✨ 优化后的代码可以正常运行")
        return 0
    else:
        print(f"❌ 发现 {len(errors)} 个错误:")
        for error in errors:
            print(f"   - {error}")
        return 1


if __name__ == "__main__":
    sys.exit(test_imports())
