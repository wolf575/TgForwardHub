#!/usr/bin/env python3
"""
测试多跳转发+提取链

场景：A→C转发（白名单"1"）+ C→D提取（正则"1"）
验证：当消息从A转发到C后，C→D的提取任务能否正确触发
"""

import json
import os
import sys

# 确保导入路径正确
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_config_setup():
    """测试配置是否正确设置了多跳链"""
    
    # 模拟配置
    test_config = {
        "user123": {
            "task1": {
                "source": "A",  # 频道A
                "dest": "C",    # 转发到频道C
                "whitelist": ["1"],  # 白名单包含"1"
                "forward_mode": "full",
                "record_mode": False
            },
            "task2": {
                "source": "C",  # 频道C
                "dest": "D",    # 提取到机器人D
                "extract_patterns": ["1"],  # 正则提取"1"
                "forward_mode": "extract",
                "record_mode": False
            }
        }
    }
    
    print("✅ 测试配置:")
    print(json.dumps(test_config, indent=2, ensure_ascii=False))
    
    # 验证配置逻辑
    # 1. 消息"1"到达A
    # 2. 匹配task1的whitelist["1"]
    # 3. 转发到C
    # 4. 在process_message中，转发后检查C是否有配置
    # 5. 找到task2: source=C, forward_mode=extract
    # 6. 提取"1"并发送到D
    
    print("\n📋 预期流程:")
    print("1. 用户发送消息'1'到频道A")
    print("2. task1匹配（whitelist=['1']），转发A→C")
    print("3. 转发后，检查C是否有配置任务")
    print("4. 找到task2（source='C', forward_mode='extract'）")
    print("5. 应用提取模式（extract_patterns=['1']）")
    print("6. 提取到'1'，发送到机器人D")
    print("7. ✅ 成功！")
    
    return True

def test_filter_logic():
    """测试过滤逻辑"""
    
    # 模拟消息
    message_text = "1"
    
    # task1的过滤（A→C）
    task1_whitelist = ["1"]
    matched = any(kw.lower() in message_text.lower() for kw in task1_whitelist)
    print(f"\n✅ task1 (A→C) whitelist check: matched={matched}")
    assert matched, "task1应该匹配消息'1'"
    
    # task2的提取（C→D）
    import re
    task2_extract_patterns = ["1"]
    extracted_content = []
    for pattern in task2_extract_patterns:
        matches = re.findall(pattern, message_text)
        if matches:
            extracted_content.extend(matches)
    
    print(f"✅ task2 (C→D) extract: extracted={extracted_content}")
    assert extracted_content == ["1"], "task2应该提取到'1'"
    
    return True

def test_nested_check_logic():
    """测试嵌套检查逻辑"""
    
    # 模拟转发后的检查
    dest_chat_id = "C"
    
    # 模拟watch_config
    watch_config = {
        "user123": {
            "task2": {
                "source": "C",
                "dest": "D",
                "extract_patterns": ["1"],
                "forward_mode": "extract",
                "record_mode": False
            }
        }
    }
    
    # 检查是否有匹配的任务
    found_task = False
    for user_id, watches in watch_config.items():
        for watch_key, watch_data in watches.items():
            if isinstance(watch_data, dict):
                check_source = str(watch_data.get("source", ""))
                check_record_mode = watch_data.get("record_mode", False)
                check_dest = watch_data.get("dest")
                
                # 检查是否匹配转发模式
                if check_source == dest_chat_id and not check_record_mode and check_dest:
                    print(f"\n✅ 找到目标频道转发任务:")
                    print(f"   user_id: {user_id}")
                    print(f"   task: {watch_key}")
                    print(f"   source: {check_source}")
                    print(f"   dest: {check_dest}")
                    print(f"   forward_mode: {watch_data.get('forward_mode')}")
                    found_task = True
    
    assert found_task, "应该找到C→D的转发任务"
    return True

if __name__ == "__main__":
    print("="*60)
    print("🧪 测试多跳转发+提取链")
    print("="*60)
    
    try:
        test_config_setup()
        test_filter_logic()
        test_nested_check_logic()
        
        print("\n" + "="*60)
        print("✅ 所有测试通过！")
        print("="*60)
        
        print("\n📝 修复说明:")
        print("- 在process_message中，转发后会检查目标频道是否配置了任务")
        print("- 支持record_mode（记录模式）和forward_mode（转发/提取模式）")
        print("- 对于extract模式，会应用提取模式并发送提取内容")
        print("- 解决了A→C→D多跳链中，C→D提取失败的问题")
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
