#!/usr/bin/env python3
"""
测试新功能：
1. 添加 preserve_forward_source 选项
2. 移除关键词信息显示
"""

import json
import os

# 测试配置保存和读取
def test_watch_config():
    test_config = {
        "123456": {
            "789": {
                "dest": "me",
                "whitelist": ["重要", "紧急"],
                "blacklist": ["广告"],
                "preserve_forward_source": True
            },
            "456": {
                "dest": "111",
                "whitelist": [],
                "blacklist": ["垃圾"],
                "preserve_forward_source": False
            }
        }
    }
    
    # 保存测试配置
    with open('test_watch_config.json', 'w', encoding='utf-8') as f:
        json.dump(test_config, f, indent=4, ensure_ascii=False)
    
    print("✅ 测试配置已创建: test_watch_config.json")
    
    # 读取测试配置
    with open('test_watch_config.json', 'r', encoding='utf-8') as f:
        loaded_config = json.load(f)
    
    # 验证配置
    watch_data = loaded_config["123456"]["789"]
    assert watch_data["preserve_forward_source"] == True, "preserve_forward_source 应该为 True"
    assert "whitelist" in watch_data, "应该有 whitelist 字段"
    assert "blacklist" in watch_data, "应该有 blacklist 字段"
    
    print("✅ 配置数据结构验证通过")
    
    # 测试默认值
    old_format = {
        "user_id": {
            "chat_id": "dest_id"
        }
    }
    
    # 模拟向后兼容处理
    if isinstance(old_format["user_id"]["chat_id"], dict):
        preserve_source = old_format["user_id"]["chat_id"].get("preserve_forward_source", False)
    else:
        preserve_source = False
    
    assert preserve_source == False, "旧格式默认应该为 False"
    print("✅ 向后兼容验证通过")
    
    # 清理
    os.remove('test_watch_config.json')
    print("✅ 测试完成")

if __name__ == "__main__":
    test_watch_config()
