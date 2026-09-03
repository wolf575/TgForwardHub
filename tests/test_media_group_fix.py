#!/usr/bin/env python3
"""
Test to verify media group handling fix.

This test verifies that Pyrogram Client methods are called directly
without _run_async_with_timeout() wrapper, which was causing
"Expected coroutine or awaitable, got List" errors.
"""

import sys
import inspect


def test_no_async_wrapping_in_media_handling():
    """Verify that acc methods are called directly in media handling code"""
    
    with open('main.py', 'r') as f:
        content = f.read()
    
    # Check that media group handling doesn't use _run_async_with_timeout
    issues = []
    
    # Look for problematic patterns
    if 'self._run_async_with_timeout(\n                            acc.get_media_group' in content:
        issues.append("Found wrapped acc.get_media_group() call")
    
    if 'self._run_async_with_timeout(\n                                acc.download_media' in content:
        issues.append("Found wrapped acc.download_media() call")
    
    if 'self._run_async_with_timeout(\n                                                acc.download_media' in content:
        issues.append("Found wrapped acc.download_media() call in forward+record mode")
    
    if 'self._run_async_with_timeout(\n                                                acc.get_media_group' in content:
        issues.append("Found wrapped acc.get_media_group() call in forward+record mode")
    
    # Look for correct patterns (direct calls with comments)
    correct_patterns = [
        "# Call get_media_group directly - Pyrogram handles async/sync bridging",
        "# Call download_media directly - Pyrogram handles async/sync bridging",
        "# Call get_chat directly - Pyrogram handles async/sync bridging"
    ]
    
    found_correct = []
    for pattern in correct_patterns:
        if pattern in content:
            found_correct.append(pattern)
    
    if issues:
        print("❌ FAILED: Found problematic async wrapping:")
        for issue in issues:
            print(f"   - {issue}")
        return False
    
    if len(found_correct) < len(correct_patterns):
        print(f"⚠️  WARNING: Only found {len(found_correct)}/{len(correct_patterns)} correct patterns")
        for pattern in correct_patterns:
            if pattern in content:
                print(f"   ✅ Found: {pattern[:50]}...")
            else:
                print(f"   ❌ Missing: {pattern[:50]}...")
    else:
        print(f"✅ PASSED: All {len(correct_patterns)} correct patterns found")
    
    print("\n✅ PASSED: No problematic async wrapping found in media handling")
    return True


def test_direct_acc_calls():
    """Verify that acc methods are called directly without wrapping"""
    
    with open('main.py', 'r') as f:
        lines = f.readlines()
    
    direct_calls = []
    wrapped_calls = []
    
    for i, line in enumerate(lines):
        line_num = i + 1
        
        # Check for direct acc calls (good)
        if 'acc.get_media_group(' in line and 'self._run_async_with_timeout' not in lines[max(0, i-2):i+3]:
            direct_calls.append((line_num, 'get_media_group'))
        
        if 'acc.download_media(' in line and 'self._run_async_with_timeout' not in lines[max(0, i-2):i+3]:
            direct_calls.append((line_num, 'download_media'))
        
        if 'acc.get_chat(' in line and 'self._run_async_with_timeout' not in lines[max(0, i-2):i+3]:
            direct_calls.append((line_num, 'get_chat'))
        
        # Check for wrapped acc calls (bad)
        if i < len(lines) - 3:
            next_lines = ''.join(lines[i:i+4])
            if 'self._run_async_with_timeout' in line and 'acc.' in next_lines:
                for method in ['get_media_group', 'download_media', 'get_chat', 'forward_messages', 'copy_message']:
                    if f'acc.{method}' in next_lines:
                        wrapped_calls.append((line_num, method))
    
    print(f"\n📊 Statistics:")
    print(f"   Direct acc calls (good): {len(direct_calls)}")
    for line_num, method in direct_calls[:5]:  # Show first 5
        print(f"      Line {line_num}: acc.{method}()")
    if len(direct_calls) > 5:
        print(f"      ... and {len(direct_calls) - 5} more")
    
    print(f"\n   Wrapped acc calls (bad): {len(wrapped_calls)}")
    if wrapped_calls:
        for line_num, method in wrapped_calls:
            print(f"      ❌ Line {line_num}: acc.{method}() wrapped with _run_async_with_timeout")
        return False
    else:
        print(f"      ✅ None found!")
    
    return True


if __name__ == '__main__':
    print("="*60)
    print("Testing Media Group Fix")
    print("="*60)
    
    test1_passed = test_no_async_wrapping_in_media_handling()
    test2_passed = test_direct_acc_calls()
    
    print("\n" + "="*60)
    if test1_passed and test2_passed:
        print("✅ ALL TESTS PASSED")
        print("="*60)
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        print("="*60)
        sys.exit(1)
