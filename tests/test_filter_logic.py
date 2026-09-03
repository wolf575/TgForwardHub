#!/usr/bin/env python3
"""
Test script to verify filter logic priority
Tests the blacklist-first priority implementation
"""

import re

def test_filter_logic(message_text, whitelist=None, blacklist=None, 
                      whitelist_regex=None, blacklist_regex=None):
    """
    Test version of filter logic with blacklist priority
    Returns: "skip" if filtered, "pass" if allowed
    """
    
    message_text = message_text or ""
    
    # Step 1: Check blacklists first (higher priority)
    
    # Check keyword blacklist
    if blacklist:
        for keyword in blacklist:
            if keyword.lower() in message_text.lower():
                print(f"   ⏭️ 过滤：匹配到关键词黑名单 '{keyword}'")
                return "skip"
    
    # Check regex blacklist
    if blacklist_regex:
        for pattern in blacklist_regex:
            try:
                if re.search(pattern, message_text):
                    print(f"   ⏭️ 过滤：匹配到正则黑名单 '{pattern}'")
                    return "skip"
            except re.error as e:
                print(f"   ⚠️ 正则黑名单表达式错误 '{pattern}': {e}")
    
    # Step 2: Check whitelists
    
    # Check keyword whitelist
    if whitelist:
        matched = False
        for keyword in whitelist:
            if keyword.lower() in message_text.lower():
                matched = True
                break
        
        if not matched:
            print(f"   ⏭️ 过滤：未匹配关键词白名单 {whitelist}")
            return "skip"
    
    # Check regex whitelist
    if whitelist_regex:
        matched = False
        for pattern in whitelist_regex:
            try:
                if re.search(pattern, message_text):
                    matched = True
                    break
            except re.error as e:
                print(f"   ⚠️ 正则白名单表达式错误 '{pattern}': {e}")
        
        if not matched:
            print(f"   ⏭️ 过滤：未匹配正则白名单 {whitelist_regex}")
            return "skip"
    
    print(f"   ✅ 通过所有过滤规则")
    return "pass"

# Test cases
print("=" * 60)
print("测试过滤逻辑 - 黑名单优先级")
print("=" * 60)

# Test 1: Blacklist takes priority over whitelist
print("\n【测试1】黑名单优先于白名单")
print("配置：whitelist=['重要'], blacklist=['广告']")
print("-" * 60)

print("\n消息1: '重要通知'")
result = test_filter_logic("重要通知", whitelist=["重要"], blacklist=["广告"])
assert result == "pass", f"❌ 失败：期望 'pass'，得到 '{result}'"
print(f"✅ 结果正确: {result}")

print("\n消息2: '重要广告'")
result = test_filter_logic("重要广告", whitelist=["重要"], blacklist=["广告"])
assert result == "skip", f"❌ 失败：期望 'skip'，得到 '{result}'"
print(f"✅ 结果正确: {result} (黑名单优先)")

print("\n消息3: '广告'")
result = test_filter_logic("广告", whitelist=["重要"], blacklist=["广告"])
assert result == "skip", f"❌ 失败：期望 'skip'，得到 '{result}'"
print(f"✅ 结果正确: {result}")

print("\n消息4: '普通消息'")
result = test_filter_logic("普通消息", whitelist=["重要"], blacklist=["广告"])
assert result == "skip", f"❌ 失败：期望 'skip'，得到 '{result}'"
print(f"✅ 结果正确: {result} (未匹配白名单)")

# Test 2: Regex blacklist priority
print("\n" + "=" * 60)
print("【测试2】正则黑名单优先于正则白名单")
print("配置：whitelist_regex=['重要.*'], blacklist_regex=['.*广告.*']")
print("-" * 60)

print("\n消息1: '重要通知'")
result = test_filter_logic("重要通知", whitelist_regex=["重要.*"], blacklist_regex=[".*广告.*"])
assert result == "pass", f"❌ 失败：期望 'pass'，得到 '{result}'"
print(f"✅ 结果正确: {result}")

print("\n消息2: '重要广告信息'")
result = test_filter_logic("重要广告信息", whitelist_regex=["重要.*"], blacklist_regex=[".*广告.*"])
assert result == "skip", f"❌ 失败：期望 'skip'，得到 '{result}'"
print(f"✅ 结果正确: {result} (正则黑名单优先)")

# Test 3: Mixed filters
print("\n" + "=" * 60)
print("【测试3】混合过滤器")
print("配置：whitelist=['重要'], blacklist=['spam'], blacklist_regex=['.*垃圾.*']")
print("-" * 60)

print("\n消息1: '重要通知'")
result = test_filter_logic("重要通知", 
                          whitelist=["重要"], 
                          blacklist=["spam"], 
                          blacklist_regex=[".*垃圾.*"])
assert result == "pass", f"❌ 失败：期望 'pass'，得到 '{result}'"
print(f"✅ 结果正确: {result}")

print("\n消息2: '重要spam'")
result = test_filter_logic("重要spam", 
                          whitelist=["重要"], 
                          blacklist=["spam"], 
                          blacklist_regex=[".*垃圾.*"])
assert result == "skip", f"❌ 失败：期望 'skip'，得到 '{result}'"
print(f"✅ 结果正确: {result} (关键词黑名单优先)")

print("\n消息3: '重要垃圾信息'")
result = test_filter_logic("重要垃圾信息", 
                          whitelist=["重要"], 
                          blacklist=["spam"], 
                          blacklist_regex=[".*垃圾.*"])
assert result == "skip", f"❌ 失败：期望 'skip'，得到 '{result}'"
print(f"✅ 结果正确: {result} (正则黑名单优先)")

# Test 4: No filters
print("\n" + "=" * 60)
print("【测试4】无过滤器")
print("配置：无")
print("-" * 60)

print("\n消息1: '任意消息'")
result = test_filter_logic("任意消息")
assert result == "pass", f"❌ 失败：期望 'pass'，得到 '{result}'"
print(f"✅ 结果正确: {result} (无过滤器，全部通过)")

# Test 5: Only whitelist
print("\n" + "=" * 60)
print("【测试5】仅白名单")
print("配置：whitelist=['允许']")
print("-" * 60)

print("\n消息1: '允许访问'")
result = test_filter_logic("允许访问", whitelist=["允许"])
assert result == "pass", f"❌ 失败：期望 'pass'，得到 '{result}'"
print(f"✅ 结果正确: {result}")

print("\n消息2: '拒绝访问'")
result = test_filter_logic("拒绝访问", whitelist=["允许"])
assert result == "skip", f"❌ 失败：期望 'skip'，得到 '{result}'"
print(f"✅ 结果正确: {result} (未匹配白名单)")

# Test 6: Only blacklist
print("\n" + "=" * 60)
print("【测试6】仅黑名单")
print("配置：blacklist=['拒绝']")
print("-" * 60)

print("\n消息1: '拒绝访问'")
result = test_filter_logic("拒绝访问", blacklist=["拒绝"])
assert result == "skip", f"❌ 失败：期望 'skip'，得到 '{result}'"
print(f"✅ 结果正确: {result}")

print("\n消息2: '允许访问'")
result = test_filter_logic("允许访问", blacklist=["拒绝"])
assert result == "pass", f"❌ 失败：期望 'pass'，得到 '{result}'"
print(f"✅ 结果正确: {result} (未匹配黑名单)")

print("\n" + "=" * 60)
print("✅ 所有测试通过！")
print("=" * 60)
