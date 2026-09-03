#!/usr/bin/env python3
"""
Test script to verify message deduplication mechanism
"""
import time

# Message deduplication cache
processed_messages = {}
MESSAGE_CACHE_TTL = 1


def is_message_processed(message_id, chat_id):
    """Check if message has already been processed"""
    key = f"{chat_id}_{message_id}"
    if key in processed_messages:
        if time.time() - processed_messages[key] < MESSAGE_CACHE_TTL:
            return True
        else:
            del processed_messages[key]
    return False


def mark_message_processed(message_id, chat_id):
    """Mark message as processed"""
    key = f"{chat_id}_{message_id}"
    processed_messages[key] = time.time()


def cleanup_old_messages():
    """Clean up expired message records"""
    current_time = time.time()
    expired_keys = [key for key, timestamp in processed_messages.items() 
                    if current_time - timestamp > MESSAGE_CACHE_TTL]
    for key in expired_keys:
        del processed_messages[key]


def test_deduplication():
    """Test message deduplication mechanism"""
    print("🧪 测试消息去重机制\n")
    
    # Test 1: First message should not be processed
    print("测试 1: 首次消息应该未被处理")
    assert not is_message_processed(123, -1001234567890), "❌ 失败：新消息被标记为已处理"
    print("✅ 通过：新消息未被标记为已处理\n")
    
    # Test 2: Mark message as processed
    print("测试 2: 标记消息为已处理")
    mark_message_processed(123, -1001234567890)
    assert is_message_processed(123, -1001234567890), "❌ 失败：消息未被标记为已处理"
    print("✅ 通过：消息已被标记为已处理\n")
    
    # Test 3: Same message should be detected as duplicate
    print("测试 3: 相同消息应该被检测为重复")
    assert is_message_processed(123, -1001234567890), "❌ 失败：重复消息未被检测"
    print("✅ 通过：重复消息被成功检测\n")
    
    # Test 4: Different message ID should not be detected as duplicate
    print("测试 4: 不同消息ID不应被检测为重复")
    assert not is_message_processed(456, -1001234567890), "❌ 失败：不同消息被错误标记为重复"
    print("✅ 通过：不同消息未被标记为重复\n")
    
    # Test 5: Different chat ID should not be detected as duplicate
    print("测试 5: 不同聊天ID不应被检测为重复")
    assert not is_message_processed(123, -1009876543210), "❌ 失败：不同聊天的消息被错误标记为重复"
    print("✅ 通过：不同聊天的消息未被标记为重复\n")
    
    # Test 6: Test TTL expiration
    print("测试 6: TTL过期测试 (等待2秒...)")
    mark_message_processed(789, -1001234567890)
    time.sleep(2)  # Wait for TTL to expire (TTL is 1 second)
    assert not is_message_processed(789, -1001234567890), "❌ 失败：过期消息仍被标记为已处理"
    print("✅ 通过：过期消息正确清理\n")
    
    # Test 7: Test cleanup function
    print("测试 7: 清理函数测试")
    mark_message_processed(111, -1001234567890)
    mark_message_processed(222, -1001234567890)
    mark_message_processed(333, -1001234567890)
    time.sleep(2)  # Wait for TTL to expire (TTL is 1 second)
    cleanup_old_messages()
    assert len(processed_messages) == 0, f"❌ 失败：清理后仍有 {len(processed_messages)} 条记录"
    print("✅ 通过：清理函数正常工作\n")
    
    # Test 8: Multiple rapid duplicates (simulating the original issue)
    print("测试 8: 模拟原始问题 - 1ms内多次处理相同消息")
    chat_id = -1001234567890
    message_id = 999
    
    processed_count = 0
    for i in range(5):
        if not is_message_processed(message_id, chat_id):
            mark_message_processed(message_id, chat_id)
            processed_count += 1
            print(f"  第 {i+1} 次: 处理消息")
        else:
            print(f"  第 {i+1} 次: ⏭️ 跳过重复消息")
    
    assert processed_count == 1, f"❌ 失败：消息被处理了 {processed_count} 次，应该只处理1次"
    print(f"✅ 通过：消息只被处理1次，其余4次被正确跳过\n")
    
    print("="*60)
    print("🎉 所有测试通过！去重机制工作正常")
    print("="*60)


if __name__ == "__main__":
    test_deduplication()
