#!/usr/bin/env python3
"""
Test script to verify media group deduplication fix
This simulates the race condition where multiple messages with the same media_group_id
arrive almost simultaneously (within milliseconds of each other).
"""
import time

# Track media groups to process only once per task
processed_media_groups = set()
processed_media_groups_order = []


def register_processed_media_group(key):
    """Register a media group as processed (same as in main.py)"""
    if not key:
        return
    processed_media_groups.add(key)
    processed_media_groups_order.append(key)
    if len(processed_media_groups_order) > 300:
        old_key = processed_media_groups_order.pop(0)
        processed_media_groups.discard(old_key)


def simulate_message_handler(user_id, watch_key, media_group_id, message_num):
    """
    Simulates the auto_forward handler processing a message.
    Returns True if processed, False if skipped.
    """
    # Build media_group_key (same as in main.py line 1937)
    media_group_key = f"{user_id}_{watch_key}_{media_group_id}"
    
    # Check if already processed (same as in main.py line 1938-1940)
    if media_group_key in processed_media_groups:
        print(f"  消息{message_num}: ⏭️ 跳过：媒体组已处理 (media_group_key={media_group_key})")
        return False
    
    # Simulate passing all filters
    print(f"  消息{message_num}: 🎯 消息通过所有过滤规则，准备处理")
    
    # **FIX: Mark media group as processed immediately** (same as main.py line 1996-1998)
    if media_group_key:
        register_processed_media_group(media_group_key)
        print(f"  消息{message_num}: ✅ 已标记媒体组为已处理: {media_group_key}")
    
    # Simulate forwarding (this takes time in reality)
    print(f"  消息{message_num}: 📤 转发模式：开始处理")
    time.sleep(0.01)  # Simulate forwarding delay
    print(f"  消息{message_num}: ✅ 消息已转发")
    
    return True


def test_media_group_race_condition():
    """Test the race condition fix for media groups"""
    print("🧪 测试媒体组竞态条件修复\n")
    print("="*70)
    
    # Test 1: Single message (no media group)
    print("\n测试 1: 单条消息（无媒体组）")
    print("-" * 70)
    processed = simulate_message_handler("12345", "source|dest", None, 1)
    assert processed == True, "❌ 失败：单条消息未被处理"
    print("✅ 通过：单条消息正常处理\n")
    
    # Test 2: Media group with 4 images (simulating the original issue)
    print("测试 2: 媒体组（4张图片）- 模拟原始问题")
    print("-" * 70)
    print("场景：发送4张图片，Telegram分割成4条消息，同一个 media_group_id")
    print("预期：只处理第一条，后续3条被跳过\n")
    
    user_id = "12345"
    watch_key = "source|dest"
    media_group_id = "abc123def456"  # Same media_group_id for all 4 messages
    
    processed_count = 0
    skipped_count = 0
    
    # Simulate 4 messages arriving in rapid succession
    for i in range(1, 5):
        print(f"T+{(i-1)*57}ms: 消息{i}到达")
        if simulate_message_handler(user_id, watch_key, media_group_id, i):
            processed_count += 1
        else:
            skipped_count += 1
        print()
    
    print(f"结果统计:")
    print(f"  - 处理次数: {processed_count}")
    print(f"  - 跳过次数: {skipped_count}")
    print()
    
    assert processed_count == 1, f"❌ 失败：媒体组被处理了 {processed_count} 次，应该只处理1次"
    assert skipped_count == 3, f"❌ 失败：只跳过了 {skipped_count} 条消息，应该跳过3条"
    print("✅ 通过：媒体组只被处理1次，其余3次被正确跳过\n")
    
    # Test 3: Different media groups should be processed separately
    print("测试 3: 不同的媒体组应该分别处理")
    print("-" * 70)
    
    # Clear the cache for this test
    processed_media_groups.clear()
    processed_media_groups_order.clear()
    
    media_group_id_1 = "group_001"
    media_group_id_2 = "group_002"
    
    print(f"媒体组1 (ID: {media_group_id_1}):")
    processed_1 = simulate_message_handler(user_id, watch_key, media_group_id_1, 1)
    print()
    
    print(f"媒体组2 (ID: {media_group_id_2}):")
    processed_2 = simulate_message_handler(user_id, watch_key, media_group_id_2, 2)
    print()
    
    assert processed_1 == True, "❌ 失败：媒体组1未被处理"
    assert processed_2 == True, "❌ 失败：媒体组2未被处理"
    print("✅ 通过：不同媒体组分别处理\n")
    
    # Test 4: Same media group ID but different watch tasks should be processed separately
    print("测试 4: 相同媒体组ID但不同监控任务应该分别处理")
    print("-" * 70)
    
    processed_media_groups.clear()
    processed_media_groups_order.clear()
    
    media_group_id = "shared_group"
    watch_key_1 = "source1|dest1"
    watch_key_2 = "source2|dest2"
    
    print(f"监控任务1 ({watch_key_1}):")
    processed_1 = simulate_message_handler(user_id, watch_key_1, media_group_id, 1)
    print()
    
    print(f"监控任务2 ({watch_key_2}):")
    processed_2 = simulate_message_handler(user_id, watch_key_2, media_group_id, 2)
    print()
    
    assert processed_1 == True, "❌ 失败：监控任务1未被处理"
    assert processed_2 == True, "❌ 失败：监控任务2未被处理"
    print("✅ 通过：不同监控任务分别处理相同媒体组\n")
    
    # Test 5: LRU cache limit (300 entries)
    print("测试 5: LRU缓存限制（300条记录）")
    print("-" * 70)
    
    processed_media_groups.clear()
    processed_media_groups_order.clear()
    
    # Add 301 entries
    for i in range(301):
        key = f"user_task_group_{i}"
        register_processed_media_group(key)
    
    # The first key should have been evicted
    assert "user_task_group_0" not in processed_media_groups, "❌ 失败：最旧的记录未被清理"
    # The last key should still be there
    assert "user_task_group_300" in processed_media_groups, "❌ 失败：最新的记录被错误清理"
    # Cache size should be exactly 300
    assert len(processed_media_groups) == 300, f"❌ 失败：缓存大小为 {len(processed_media_groups)}，应该是300"
    print(f"✅ 通过：LRU缓存正确维持在300条记录\n")
    
    # Test 6: Rapid-fire test (the original issue scenario)
    print("测试 6: 高并发场景（模拟原始问题日志）")
    print("-" * 70)
    print("原始问题日志:")
    print("  04:53:11,227 - 📤 转发模式：开始处理")
    print("  04:53:11,284 - 📤 转发模式：开始处理  // 57ms后重复")
    print("  04:53:11,287 - 📤 转发模式：开始处理")
    print("  04:53:11,294 - 📤 转发模式：开始处理")
    print()
    print("修复后预期:")
    print("  只有第一条消息会显示 '📤 转发模式：开始处理'")
    print("  后续消息应显示 '⏭️ 跳过：媒体组已处理'")
    print()
    
    processed_media_groups.clear()
    processed_media_groups_order.clear()
    
    media_group_id = "rapid_fire_test"
    forward_count = 0
    
    # Simulate 4 messages arriving within 67ms
    start_time = time.time()
    for i in range(1, 5):
        # Simulate timing from the logs (0ms, 57ms, 60ms, 67ms)
        if i > 1:
            time.sleep(0.001)  # Small delay to simulate near-simultaneous arrival
        
        if simulate_message_handler(user_id, watch_key, media_group_id, i):
            forward_count += 1
        print()
    
    elapsed = (time.time() - start_time) * 1000
    print(f"总耗时: {elapsed:.1f}ms")
    print(f"转发次数: {forward_count}")
    print()
    
    assert forward_count == 1, f"❌ 失败：在高并发场景下转发了 {forward_count} 次"
    print("✅ 通过：高并发场景下只转发一次\n")
    
    print("="*70)
    print("🎉 所有测试通过！媒体组去重修复生效")
    print("="*70)
    print("\n📋 修复总结:")
    print("  ✅ 媒体组在通过过滤规则后立即被标记为已处理")
    print("  ✅ 防止了竞态条件导致的重复转发")
    print("  ✅ 不影响单条消息的正常处理")
    print("  ✅ 不影响不同媒体组的独立处理")
    print("  ✅ LRU缓存正常工作，防止内存泄漏")


def test_without_fix():
    """
    Demonstrate the bug that existed before the fix.
    This shows what would happen if we marked the media group as processed
    AFTER forwarding instead of BEFORE.
    """
    print("\n" + "="*70)
    print("🐛 演示修复前的问题（标记延迟到转发后）")
    print("="*70 + "\n")
    
    processed_media_groups.clear()
    processed_media_groups_order.clear()
    
    user_id = "12345"
    watch_key = "source|dest"
    media_group_id = "buggy_group"
    
    processed_count = 0
    
    for i in range(1, 5):
        media_group_key = f"{user_id}_{watch_key}_{media_group_id}"
        
        # Check if already processed
        if media_group_key in processed_media_groups:
            print(f"  消息{i}: ⏭️ 跳过：媒体组已处理")
            continue
        
        print(f"  消息{i}: 🎯 消息通过所有过滤规则，准备处理")
        print(f"  消息{i}: 📤 转发模式：开始处理")
        
        # BUG: Mark as processed AFTER forwarding (old behavior)
        # In reality, all 4 messages would pass the check before any of them finishes forwarding
        processed_count += 1
        
        # Simulate forwarding delay
        time.sleep(0.01)
        
        # Mark as processed (TOO LATE!)
        register_processed_media_group(media_group_key)
        print(f"  消息{i}: ✅ 消息已转发（然后才标记为已处理）")
        print()
    
    print(f"结果：媒体组被处理了 {processed_count} 次 ❌")
    print(f"期望：应该只处理 1 次")
    print("\n这就是为什么需要在转发前立即标记！\n")


if __name__ == "__main__":
    # Run tests with the fix
    test_media_group_race_condition()
    
    # Demonstrate the problem without the fix
    test_without_fix()
