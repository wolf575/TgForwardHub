#!/usr/bin/env python3
"""
综合测试脚本 - 验证重构后的代码功能
Comprehensive test script for the refactored codebase
"""
import sys
import os

def test_imports():
    """Test all module imports"""
    print("=" * 60)
    print("📦 测试模块导入 (Testing Module Imports)")
    print("=" * 60)
    
    tests = [
        ("config", "import config"),
        ("bot", "import bot"),
        ("bot.filters", "from bot.filters import check_whitelist, check_blacklist, check_whitelist_regex, check_blacklist_regex, extract_content"),
        ("bot.utils", "from bot.utils import is_message_processed, mark_message_processed, cleanup_old_messages"),
        ("bot.utils.dedup", "from bot.utils.dedup import is_media_group_processed, register_processed_media_group"),
        ("bot.utils.peer", "from bot.utils.peer import cache_peer, is_dest_cached, mark_dest_cached"),
        ("bot.utils.progress", "from bot.utils.progress import progress, downstatus, upstatus"),
        ("bot.utils.status", "from bot.utils.status import get_user_state, set_user_state, clear_user_state"),
        ("bot.handlers", "from bot.handlers import set_bot_instance, get_bot_instance"),
        ("bot.handlers.commands", "from bot.handlers.commands import register_command_handlers, show_watch_menu"),
        ("bot.workers", "from bot.workers import MessageWorker, Message, UnrecoverableError"),
    ]
    
    passed = 0
    failed = 0
    
    for name, import_stmt in tests:
        try:
            exec(import_stmt)
            print(f"✅ {name}")
            passed += 1
        except Exception as e:
            print(f"❌ {name}: {e}")
            failed += 1
    
    print(f"\n结果: {passed} 通过, {failed} 失败\n")
    return failed == 0


def test_filters():
    """Test filter functions"""
    print("=" * 60)
    print("🔍 测试过滤器 (Testing Filters)")
    print("=" * 60)
    
    from bot.filters import check_whitelist, check_blacklist, check_whitelist_regex, check_blacklist_regex, extract_content
    
    text = "Hello world, price is 100 USD"
    
    tests = [
        ("Whitelist match", lambda: check_whitelist(text, ["hello"]), True),
        ("Whitelist no match", lambda: check_whitelist(text, ["foo"]), False),
        ("Blacklist match", lambda: check_blacklist(text, ["world"]), True),
        ("Blacklist no match", lambda: check_blacklist(text, ["foo"]), False),
        ("Regex whitelist", lambda: check_whitelist_regex(text, [r"\d+\s+USD"]), True),
        ("Regex blacklist", lambda: check_blacklist_regex(text, [r"world"]), True),
        ("Extract content", lambda: len(extract_content(text, [r"\d+"])) > 0, True),
    ]
    
    passed = 0
    failed = 0
    
    for name, func, expected in tests:
        try:
            result = func()
            if result == expected:
                print(f"✅ {name}: {result}")
                passed += 1
            else:
                print(f"❌ {name}: got {result}, expected {expected}")
                failed += 1
        except Exception as e:
            print(f"❌ {name}: {e}")
            failed += 1
    
    print(f"\n结果: {passed} 通过, {failed} 失败\n")
    return failed == 0


def test_utils():
    """Test utility functions"""
    print("=" * 60)
    print("🛠️  测试工具函数 (Testing Utilities)")
    print("=" * 60)
    
    from bot.utils.dedup import is_message_processed, mark_message_processed, is_media_group_processed, register_processed_media_group
    from bot.utils.status import get_user_state, set_user_state, clear_user_state
    from bot.utils.peer import is_dest_cached, mark_dest_cached
    
    tests = []
    
    # Test message deduplication
    mark_message_processed(99999, -100999999999)
    tests.append(("Message dedup - marked", is_message_processed(99999, -100999999999), True))
    tests.append(("Message dedup - not marked", is_message_processed(88888, -100999999999), False))
    
    # Test media group deduplication
    register_processed_media_group("test_group_key")
    tests.append(("Media group dedup - registered", is_media_group_processed("test_group_key"), True))
    tests.append(("Media group dedup - not registered", is_media_group_processed("other_key"), False))
    
    # Test status management
    set_user_state("test_user", {"step": "test"})
    tests.append(("Status - set", get_user_state("test_user").get("step"), "test"))
    clear_user_state("test_user")
    tests.append(("Status - cleared", get_user_state("test_user"), {}))
    
    # Test peer caching
    mark_dest_cached("-100999999999")
    tests.append(("Peer cache - marked", is_dest_cached("-100999999999"), True))
    tests.append(("Peer cache - not marked", is_dest_cached("-100888888888"), False))
    
    passed = 0
    failed = 0
    
    for name, result, expected in tests:
        if result == expected:
            print(f"✅ {name}")
            passed += 1
        else:
            print(f"❌ {name}: got {result}, expected {expected}")
            failed += 1
    
    print(f"\n结果: {passed} 通过, {failed} 失败\n")
    return failed == 0


def test_config():
    """Test configuration management"""
    print("=" * 60)
    print("⚙️  测试配置管理 (Testing Configuration)")
    print("=" * 60)
    
    from config import DATA_DIR, CONFIG_DIR, MEDIA_DIR, load_config, load_watch_config, get_monitored_sources
    
    tests = [
        ("DATA_DIR exists", os.path.exists(DATA_DIR), True),
        ("CONFIG_DIR exists", os.path.exists(CONFIG_DIR), True),
        ("MEDIA_DIR exists", os.path.exists(MEDIA_DIR), True),
        ("load_config returns dict", isinstance(load_config(), dict), True),
        ("load_watch_config returns dict", isinstance(load_watch_config(), dict), True),
        ("get_monitored_sources returns set", isinstance(get_monitored_sources(), set), True),
    ]
    
    passed = 0
    failed = 0
    
    for name, result, expected in tests:
        if result == expected:
            print(f"✅ {name}")
            passed += 1
        else:
            print(f"❌ {name}: got {result}, expected {expected}")
            failed += 1
    
    print(f"\n结果: {passed} 通过, {failed} 失败\n")
    return failed == 0


def test_workers():
    """Test worker module classes"""
    print("=" * 60)
    print("👷 测试工作线程模块 (Testing Workers)")
    print("=" * 60)
    
    from bot.workers import Message, UnrecoverableError
    
    # Create mock message
    class MockMsg:
        id = 123
        text = "test"
        chat = type('obj', (object,), {'id': -100})()
        media_group_id = None
    
    tests = []
    
    # Test Message creation
    try:
        msg = Message(
            user_id="123",
            watch_key="key",
            message=MockMsg(),
            watch_data={},
            source_chat_id="-100",
            dest_chat_id="me",
            message_text="test"
        )
        tests.append(("Message creation", True, True))
        tests.append(("Message user_id", msg.user_id, "123"))
        tests.append(("Message retry_count", msg.retry_count, 0))
    except Exception as e:
        tests.append(("Message creation", False, True))
        print(f"   Error: {e}")
    
    # Test UnrecoverableError
    try:
        raise UnrecoverableError("test error")
    except UnrecoverableError:
        tests.append(("UnrecoverableError", True, True))
    except:
        tests.append(("UnrecoverableError", False, True))
    
    passed = 0
    failed = 0
    
    for name, result, expected in tests:
        if result == expected:
            print(f"✅ {name}")
            passed += 1
        else:
            print(f"❌ {name}: got {result}, expected {expected}")
            failed += 1
    
    print(f"\n结果: {passed} 通过, {failed} 失败\n")
    return failed == 0


def test_file_compilation():
    """Test that main files compile"""
    print("=" * 60)
    print("📝 测试文件编译 (Testing File Compilation)")
    print("=" * 60)
    
    import py_compile
    
    files = ["main.py", "config.py", "database.py", "constants.py"]
    
    passed = 0
    failed = 0
    
    for filename in files:
        try:
            py_compile.compile(filename, doraise=True)
            print(f"✅ {filename}")
            passed += 1
        except Exception as e:
            print(f"❌ {filename}: {e}")
            failed += 1
    
    print(f"\n结果: {passed} 通过, {failed} 失败\n")
    return failed == 0


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("🧪 Save-Restricted-Bot 重构测试套件")
    print("   Refactoring Test Suite")
    print("=" * 60 + "\n")
    
    results = []
    
    # Run all tests
    results.append(("模块导入", test_imports()))
    results.append(("过滤器", test_filters()))
    results.append(("工具函数", test_utils()))
    results.append(("配置管理", test_config()))
    results.append(("工作线程", test_workers()))
    results.append(("文件编译", test_file_compilation()))
    
    # Summary
    print("=" * 60)
    print("📊 测试总结 (Test Summary)")
    print("=" * 60)
    
    total = len(results)
    passed = sum(1 for _, result in results if result)
    failed = total - passed
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")
    
    print("\n" + "=" * 60)
    print(f"总计: {passed}/{total} 通过")
    
    if failed == 0:
        print("\n🎉 所有测试通过！重构成功！")
        print("   All tests passed! Refactoring successful!")
        return 0
    else:
        print(f"\n⚠️  {failed} 个测试失败")
        print(f"   {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
