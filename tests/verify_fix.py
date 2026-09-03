#!/usr/bin/env python3
"""
Verification script for async execution validation fix.

This script demonstrates that the fix prevents TypeError: An asyncio.Future, 
a coroutine or an awaitable is required by validating inputs early.
"""

import sys
import subprocess
import os

def run_test(test_file):
    """Run a test file and check if it passes"""
    print(f"\n{'='*80}")
    print(f"Running: {test_file}")
    print('='*80)
    
    result = subprocess.run(
        [sys.executable, test_file],
        cwd=os.path.dirname(__file__) or '.',
        capture_output=True,
        text=True
    )
    
    output = result.stdout + result.stderr
    
    # Check for success indicators
    if result.returncode == 0:
        if "PASSED" in output or "ALL TESTS PASSED" in output:
            print(f"✅ {test_file} - PASSED")
            return True
        else:
            print(f"⚠️ {test_file} - Exit code 0 but no PASSED message")
            print("Output:", output[-500:])  # Last 500 chars
            return False
    else:
        print(f"❌ {test_file} - FAILED (exit code: {result.returncode})")
        print("Error output:", output[-500:])  # Last 500 chars
        return False

def main():
    """Run all verification tests"""
    print("="*80)
    print("修复验证：异步执行错误导致记录模式全部失败")
    print("="*80)
    print("\n修复内容：")
    print("  1. ✅ 添加 coroutine/awaitable 类型验证")
    print("  2. ✅ 添加事件循环状态检查")
    print("  3. ✅ 增强 TypeError 错误处理")
    print("  4. ✅ 清晰的错误信息")
    
    tests = [
        'test_async_fix.py',
        'test_async_validation.py'
    ]
    
    results = []
    for test in tests:
        if os.path.exists(test):
            results.append(run_test(test))
        else:
            print(f"⚠️ Test file not found: {test}")
            results.append(False)
    
    print("\n" + "="*80)
    print("验证结果总结")
    print("="*80)
    print(f"总测试文件: {len(tests)}")
    print(f"通过: {sum(results)}")
    print(f"失败: {len(results) - sum(results)}")
    print("="*80)
    
    if all(results):
        print("\n✅ 所有测试通过！修复已验证成功。")
        print("\n预期效果：")
        print("  ✅ 记录模式消息正常处理")
        print("  ✅ 无 TypeError: An asyncio.Future... 错误")
        print("  ✅ 笔记正常保存到数据库")
        print("  ✅ 网页正常显示笔记")
        print("  ✅ 无效输入快速识别并跳过")
        return 0
    else:
        print("\n❌ 部分测试失败，请检查日志。")
        return 1

if __name__ == "__main__":
    exit(main())
