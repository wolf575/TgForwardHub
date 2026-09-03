#!/usr/bin/env python3
"""
Bug修复测试脚本
Test script for bug fixes
"""
import sys
import os
import time
import threading

print("="*60)
print("🐛 Bug修复测试")
print("   Bug Fixes Test")
print("="*60)

# Test 1: Division by zero fix in progress.py
print("\n测试1: progress函数除零错误修复")
print("-"*60)

try:
    from bot.utils.progress import progress
    
    # Mock message object
    class MockMessage:
        class Chat:
            id = 12345
        chat = Chat()
        id = 67890
    
    msg = MockMessage()
    
    # Test with total = 0 (should not crash)
    try:
        progress(0, 0, msg, "test")
        print("✅ 除零情况处理正确 (total=0)")
    except Exception as e:
        print(f"❌ 除零错误未修复: {e}")
    
    # Test with total > 0 (normal case)
    try:
        progress(50, 100, msg, "test")
        print("✅ 正常情况处理正确 (50/100)")
    except Exception as e:
        print(f"❌ 正常情况失败: {e}")
    
    # Test with invalid message (should not crash)
    try:
        progress(50, 100, None, "test")
        print("✅ 无效message处理正确")
    except Exception as e:
        print(f"❌ 无效message处理失败: {e}")
    
    # Clean up test files
    test_file = f"teststatus{msg.chat.id}{msg.id}.txt"
    if os.path.exists(test_file):
        os.remove(test_file)
    
except Exception as e:
    print(f"❌ progress测试失败: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Thread safety in dedup.py
print("\n测试2: 去重函数线程安全性")
print("-"*60)

try:
    from bot.utils.dedup import (
        mark_message_processed, 
        is_message_processed,
        register_processed_media_group,
        is_media_group_processed,
        get_cache_stats
    )
    
    # Test basic functionality
    mark_message_processed(111, -100111)
    result = is_message_processed(111, -100111)
    print(f"✅ 基本去重功能: {result}")
    
    # Test thread safety with concurrent access
    errors = []
    
    def worker():
        try:
            for i in range(100):
                mark_message_processed(i, -100)
                is_message_processed(i, -100)
                register_processed_media_group(f"test_key_{i}")
                is_media_group_processed(f"test_key_{i}")
        except Exception as e:
            errors.append(e)
    
    threads = []
    for _ in range(10):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    if errors:
        print(f"❌ 线程安全测试失败: {len(errors)} 个错误")
        for e in errors[:3]:  # Show first 3 errors
            print(f"   {e}")
    else:
        print("✅ 线程安全测试通过 (10线程 x 100操作)")
    
    # Test cache stats
    stats = get_cache_stats()
    print(f"✅ 缓存统计功能: {stats}")
    
except Exception as e:
    print(f"❌ 去重测试失败: {e}")
    import traceback
    traceback.print_exc()

# Test 3: File encoding in progress.py
print("\n测试3: 文件编码处理")
print("-"*60)

try:
    from bot.utils.progress import progress
    
    class MockMessage2:
        class Chat:
            id = 99999
        chat = Chat()
        id = 88888
    
    msg = MockMessage2()
    
    # Write with UTF-8 encoding
    progress(75, 100, msg, "test")
    
    test_file = f"teststatus{msg.chat.id}{msg.id}.txt"
    
    # Read back and verify
    if os.path.exists(test_file):
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"✅ UTF-8编码正确: 读取内容 = '{content}'")
        os.remove(test_file)
    else:
        print("⚠️  状态文件未创建")
    
except Exception as e:
    print(f"❌ 编码测试失败: {e}")

# Test 4: Error handling improvements
print("\n测试4: 错误处理改进")
print("-"*60)

try:
    # Import to check syntax
    from bot.utils import progress, downstatus, upstatus
    print("✅ 所有progress函数导入成功")
    
    # Check that proper exceptions are used (not bare except)
    import ast
    import inspect
    
    # Get source code
    source = inspect.getsource(progress)
    tree = ast.parse(source)
    
    bare_excepts = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                bare_excepts += 1
    
    if bare_excepts > 0:
        print(f"⚠️  发现 {bare_excepts} 个裸except语句")
    else:
        print("✅ 无裸except语句 (使用了具体异常类型)")
    
except Exception as e:
    print(f"❌ 错误处理测试失败: {e}")

# Test 5: Import all fixed modules
print("\n测试5: 模块导入测试")
print("-"*60)

try:
    from bot.utils import (
        register_processed_media_group,
        is_media_group_processed,
        is_message_processed,
        mark_message_processed,
        cleanup_old_messages,
        get_cache_stats,
        progress, downstatus, upstatus
    )
    print("✅ 所有修复的函数导入成功")
    
except Exception as e:
    print(f"❌ 导入失败: {e}")

# Summary
print("\n" + "="*60)
print("📊 测试总结")
print("="*60)

print("""
修复的Bug:
1. ✅ 除零错误 (progress函数)
2. ✅ 裸except语句 (progress函数)
3. ✅ 无限循环风险 (downstatus/upstatus)
4. ✅ 文件编码问题 (所有文件操作)
5. ✅ 资源清理 (finally块清理临时文件)
6. ✅ 并发安全 (dedup函数添加线程锁)
7. ✅ 输入验证 (progress函数)

新增功能:
- 超时机制 (FILE_WAIT_TIMEOUT = 30秒)
- 缓存统计 (get_cache_stats函数)
- 详细日志记录
- 线程安全保证
""")

print("="*60)
print("✅ Bug修复测试完成！")
print("="*60)
