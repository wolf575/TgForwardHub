#!/usr/bin/env python3
"""
性能测试脚本 - Performance Testing Script
测试重构后代码的性能指标
"""
import time
import sys
import os
import queue
import threading
import gc
import resource
from typing import List, Callable, Any

# Helper function to get memory usage
def get_memory_mb():
    """Get current memory usage in MB"""
    try:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KB to MB on Linux
    except:
        return 0


def measure_time(func: Callable, *args, **kwargs) -> tuple:
    """测量函数执行时间
    
    Returns:
        (result, execution_time_ms)
    """
    start = time.perf_counter()
    result = func(*args, **kwargs)
    end = time.perf_counter()
    return result, (end - start) * 1000  # Convert to milliseconds


def measure_memory(func: Callable, *args, **kwargs) -> tuple:
    """测量函数内存使用
    
    Returns:
        (result, memory_delta_mb)
    """
    gc.collect()
    mem_before = get_memory_mb()
    result = func(*args, **kwargs)
    gc.collect()
    mem_after = get_memory_mb()
    return result, max(0, mem_after - mem_before)  # Ensure non-negative


def run_benchmark(name: str, func: Callable, iterations: int = 1000, warmup: int = 10):
    """运行性能基准测试
    
    Args:
        name: 测试名称
        func: 要测试的函数
        iterations: 迭代次数
        warmup: 预热次数
    """
    print(f"\n{'='*60}")
    print(f"🔥 {name}")
    print(f"{'='*60}")
    
    # Warmup
    for _ in range(warmup):
        func()
    
    # Benchmark
    times = []
    for _ in range(iterations):
        _, exec_time = measure_time(func)
        times.append(exec_time)
    
    # Statistics
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    
    print(f"迭代次数: {iterations}")
    print(f"平均时间: {avg_time:.4f} ms")
    print(f"最小时间: {min_time:.4f} ms")
    print(f"最大时间: {max_time:.4f} ms")
    print(f"吞吐量:   {1000/avg_time:.2f} ops/sec")
    
    return {
        'name': name,
        'iterations': iterations,
        'avg_ms': avg_time,
        'min_ms': min_time,
        'max_ms': max_time,
        'throughput': 1000/avg_time
    }


def test_module_imports():
    """测试模块导入性能"""
    print("\n" + "="*60)
    print("📦 模块导入性能测试")
    print("="*60)
    
    modules = [
        ('config', 'import config'),
        ('bot.filters', 'from bot.filters import check_whitelist, check_blacklist'),
        ('bot.utils', 'from bot.utils import is_message_processed, mark_message_processed'),
        ('bot.workers', 'from bot.workers import Message, MessageWorker'),
    ]
    
    results = []
    for name, import_stmt in modules:
        _, exec_time = measure_time(exec, import_stmt)
        results.append({
            'module': name,
            'time_ms': exec_time
        })
        print(f"✅ {name:20s} {exec_time:8.4f} ms")
    
    total_time = sum(r['time_ms'] for r in results)
    print(f"\n总导入时间: {total_time:.4f} ms")
    
    return results


def test_filter_performance():
    """测试过滤器性能"""
    from bot.filters import check_whitelist, check_blacklist, check_whitelist_regex, check_blacklist_regex, extract_content
    
    test_text = "Hello world, this is a test message with price 100 USD and email test@example.com"
    whitelist = ["hello", "test", "message"]
    blacklist = ["spam", "bad", "forbidden"]
    whitelist_regex = [r"\d+\s+USD", r"test"]
    blacklist_regex = [r"spam", r"forbidden"]
    extract_patterns = [r"\d+", r"\w+@\w+\.\w+"]
    
    results = []
    
    # Test keyword filters
    result = run_benchmark(
        "关键词白名单过滤 (Keyword Whitelist)",
        lambda: check_whitelist(test_text, whitelist),
        iterations=10000
    )
    results.append(result)
    
    result = run_benchmark(
        "关键词黑名单过滤 (Keyword Blacklist)",
        lambda: check_blacklist(test_text, blacklist),
        iterations=10000
    )
    results.append(result)
    
    # Test regex filters
    result = run_benchmark(
        "正则白名单过滤 (Regex Whitelist)",
        lambda: check_whitelist_regex(test_text, whitelist_regex),
        iterations=5000
    )
    results.append(result)
    
    result = run_benchmark(
        "正则黑名单过滤 (Regex Blacklist)",
        lambda: check_blacklist_regex(test_text, blacklist_regex),
        iterations=5000
    )
    results.append(result)
    
    # Test content extraction
    result = run_benchmark(
        "内容提取 (Content Extraction)",
        lambda: extract_content(test_text, extract_patterns),
        iterations=5000
    )
    results.append(result)
    
    return results


def test_deduplication_performance():
    """测试去重性能"""
    from bot.utils.dedup import mark_message_processed, is_message_processed, register_processed_media_group, is_media_group_processed
    
    results = []
    
    # Test message deduplication
    result = run_benchmark(
        "标记消息已处理 (Mark Message Processed)",
        lambda: mark_message_processed(123456, -100123456789),
        iterations=10000
    )
    results.append(result)
    
    # Prepare for lookup test
    for i in range(1000):
        mark_message_processed(i, -100123456789)
    
    result = run_benchmark(
        "检查消息是否已处理 (Check Message Processed)",
        lambda: is_message_processed(500, -100123456789),
        iterations=10000
    )
    results.append(result)
    
    # Test media group deduplication
    result = run_benchmark(
        "注册媒体组 (Register Media Group)",
        lambda: register_processed_media_group(f"user_key_dest_forward_{time.time()}"),
        iterations=5000
    )
    results.append(result)
    
    return results


def test_config_performance():
    """测试配置管理性能"""
    from config import load_config, load_watch_config, build_monitored_sources
    
    results = []
    
    result = run_benchmark(
        "加载主配置 (Load Config)",
        lambda: load_config(),
        iterations=1000
    )
    results.append(result)
    
    result = run_benchmark(
        "加载监控配置 (Load Watch Config)",
        lambda: load_watch_config(),
        iterations=1000
    )
    results.append(result)
    
    result = run_benchmark(
        "构建监控源集合 (Build Monitored Sources)",
        lambda: build_monitored_sources(),
        iterations=1000
    )
    results.append(result)
    
    return results


def test_state_management_performance():
    """测试状态管理性能"""
    from bot.utils.status import set_user_state, get_user_state, update_user_state, clear_user_state
    
    results = []
    
    result = run_benchmark(
        "设置用户状态 (Set User State)",
        lambda: set_user_state("user123", {"step": "test", "data": "value"}),
        iterations=10000
    )
    results.append(result)
    
    # Prepare data for get test
    set_user_state("user123", {"step": "test"})
    
    result = run_benchmark(
        "获取用户状态 (Get User State)",
        lambda: get_user_state("user123"),
        iterations=10000
    )
    results.append(result)
    
    result = run_benchmark(
        "更新用户状态 (Update User State)",
        lambda: update_user_state("user123", new_field="value"),
        iterations=10000
    )
    results.append(result)
    
    return results


def test_queue_performance():
    """测试队列性能"""
    print("\n" + "="*60)
    print("📬 队列性能测试")
    print("="*60)
    
    # Test queue operations
    q = queue.Queue()
    
    # Test enqueue
    _, enqueue_time = measure_time(lambda: [q.put(i) for i in range(1000)])
    print(f"入队1000条消息: {enqueue_time:.4f} ms ({1000000/enqueue_time:.0f} ops/sec)")
    
    # Test dequeue
    _, dequeue_time = measure_time(lambda: [q.get() for _ in range(1000)])
    print(f"出队1000条消息: {dequeue_time:.4f} ms ({1000000/dequeue_time:.0f} ops/sec)")
    
    return {
        'enqueue_ms': enqueue_time,
        'dequeue_ms': dequeue_time,
        'enqueue_ops': 1000000/enqueue_time,
        'dequeue_ops': 1000000/dequeue_time
    }


def test_message_worker_creation():
    """测试消息工作线程创建性能"""
    from bot.workers import Message
    
    print("\n" + "="*60)
    print("👷 Worker 对象创建性能测试")
    print("="*60)
    
    class MockMsg:
        id = 123
        text = "test"
        chat = type('obj', (object,), {'id': -100})()
        media_group_id = None
    
    def create_message():
        return Message(
            user_id="123",
            watch_key="key",
            message=MockMsg(),
            watch_data={},
            source_chat_id="-100",
            dest_chat_id="me",
            message_text="test"
        )
    
    _, single_time = measure_time(create_message)
    print(f"单个Message对象创建: {single_time:.4f} ms")
    
    # Batch creation
    _, batch_time = measure_time(lambda: [create_message() for _ in range(1000)])
    print(f"创建1000个Message对象: {batch_time:.4f} ms ({1000000/batch_time:.0f} ops/sec)")
    
    # Memory test
    _, mem_delta = measure_memory(lambda: [create_message() for _ in range(1000)])
    print(f"1000个Message对象内存使用: {mem_delta:.2f} MB")
    
    return {
        'single_ms': single_time,
        'batch_ms': batch_time,
        'memory_mb': mem_delta
    }


def test_concurrent_processing():
    """测试并发处理性能"""
    print("\n" + "="*60)
    print("🔀 并发处理性能测试")
    print("="*60)
    
    from bot.utils.dedup import mark_message_processed, is_message_processed
    
    def worker_func(worker_id: int, iterations: int):
        """Worker thread function"""
        for i in range(iterations):
            mark_message_processed(worker_id * 10000 + i, -100123456789)
            is_message_processed(worker_id * 10000 + i, -100123456789)
    
    # Test with different thread counts
    thread_counts = [1, 2, 4, 8]
    results = []
    
    for num_threads in thread_counts:
        iterations = 1000
        threads = []
        
        start = time.perf_counter()
        
        for i in range(num_threads):
            t = threading.Thread(target=worker_func, args=(i, iterations))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        end = time.perf_counter()
        total_time = (end - start) * 1000  # ms
        total_ops = num_threads * iterations * 2  # mark + check
        
        result = {
            'threads': num_threads,
            'time_ms': total_time,
            'ops': total_ops,
            'throughput': total_ops / (total_time / 1000)
        }
        results.append(result)
        
        print(f"{num_threads} 线程: {total_time:.2f} ms, {result['throughput']:.0f} ops/sec")
    
    return results


def test_memory_usage():
    """测试内存使用情况"""
    print("\n" + "="*60)
    print("💾 内存使用测试")
    print("="*60)
    
    # Get initial memory
    gc.collect()
    initial_mem = get_memory_mb()
    print(f"初始内存: {initial_mem:.2f} MB")
    
    # Import all modules
    from config import load_config, load_watch_config
    from bot.filters import check_whitelist, check_blacklist
    from bot.utils import mark_message_processed
    from bot.workers import Message
    
    gc.collect()
    after_import_mem = get_memory_mb()
    import_delta = max(0, after_import_mem - initial_mem)
    print(f"导入模块后: {after_import_mem:.2f} MB (+{import_delta:.2f} MB)")
    
    # Create test data
    messages = []
    for i in range(1000):
        class MockMsg:
            id = i
            text = f"test message {i}"
            chat = type('obj', (object,), {'id': -100})()
            media_group_id = None
        
        msg = Message(
            user_id=str(i),
            watch_key="key",
            message=MockMsg(),
            watch_data={},
            source_chat_id="-100",
            dest_chat_id="me",
            message_text=f"test {i}"
        )
        messages.append(msg)
    
    gc.collect()
    after_data_mem = get_memory_mb()
    data_delta = max(0, after_data_mem - after_import_mem)
    print(f"创建1000个Message对象后: {after_data_mem:.2f} MB (+{data_delta:.2f} MB)")
    
    # Clean up
    messages.clear()
    gc.collect()
    final_mem = get_memory_mb()
    print(f"清理后: {final_mem:.2f} MB")
    
    return {
        'initial_mb': initial_mem,
        'after_import_mb': after_import_mem,
        'after_data_mb': after_data_mem,
        'final_mb': final_mem,
        'import_overhead_mb': import_delta,
        'data_overhead_mb': data_delta
    }


def generate_report(results: dict):
    """生成性能测试报告"""
    print("\n" + "="*60)
    print("📊 性能测试总结报告")
    print("="*60)
    
    # Summary
    print("\n🎯 关键性能指标 (Key Performance Indicators)")
    print("-" * 60)
    
    # Filter performance
    if 'filters' in results:
        print("\n🔍 过滤器性能:")
        for r in results['filters']:
            print(f"  {r['name']:40s} {r['avg_ms']:8.4f} ms/op")
    
    # Deduplication performance  
    if 'dedup' in results:
        print("\n🔄 去重性能:")
        for r in results['dedup']:
            print(f"  {r['name']:40s} {r['avg_ms']:8.4f} ms/op")
    
    # Config performance
    if 'config' in results:
        print("\n⚙️  配置管理性能:")
        for r in results['config']:
            print(f"  {r['name']:40s} {r['avg_ms']:8.4f} ms/op")
    
    # State management
    if 'state' in results:
        print("\n📝 状态管理性能:")
        for r in results['state']:
            print(f"  {r['name']:40s} {r['avg_ms']:8.4f} ms/op")
    
    # Queue performance
    if 'queue' in results:
        print(f"\n📬 队列性能:")
        print(f"  入队吞吐量: {results['queue']['enqueue_ops']:.0f} ops/sec")
        print(f"  出队吞吐量: {results['queue']['dequeue_ops']:.0f} ops/sec")
    
    # Worker performance
    if 'worker' in results:
        print(f"\n👷 Worker性能:")
        print(f"  单个对象创建: {results['worker']['single_ms']:.4f} ms")
        print(f"  批量创建吞吐量: {1000/results['worker']['batch_ms']*1000:.0f} ops/sec")
        print(f"  1000个对象内存: {results['worker']['memory_mb']:.2f} MB")
    
    # Concurrent performance
    if 'concurrent' in results:
        print(f"\n🔀 并发性能:")
        for r in results['concurrent']:
            print(f"  {r['threads']} 线程: {r['throughput']:.0f} ops/sec")
    
    # Memory usage
    if 'memory' in results:
        print(f"\n💾 内存使用:")
        print(f"  模块导入开销: {results['memory']['import_overhead_mb']:.2f} MB")
        print(f"  1000对象内存: {results['memory']['data_overhead_mb']:.2f} MB")
    
    print("\n" + "="*60)
    print("✅ 性能测试完成！")
    print("="*60)


def main():
    """运行所有性能测试"""
    print("\n" + "="*60)
    print("🚀 Save-Restricted-Bot 性能测试套件")
    print("   Performance Testing Suite")
    print("="*60)
    
    results = {}
    
    try:
        # Module import performance
        results['imports'] = test_module_imports()
        
        # Filter performance
        results['filters'] = test_filter_performance()
        
        # Deduplication performance
        results['dedup'] = test_deduplication_performance()
        
        # Config performance
        results['config'] = test_config_performance()
        
        # State management performance
        results['state'] = test_state_management_performance()
        
        # Queue performance
        results['queue'] = test_queue_performance()
        
        # Worker performance
        results['worker'] = test_message_worker_creation()
        
        # Concurrent performance
        results['concurrent'] = test_concurrent_processing()
        
        # Memory usage
        results['memory'] = test_memory_usage()
        
        # Generate report
        generate_report(results)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
