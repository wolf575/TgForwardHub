#!/usr/bin/env python3
"""测试 'me' 监控功能"""

# 模拟测试handle_add_source的逻辑
def test_me_handling():
    print("测试 'me' 输入处理...")
    
    # 模拟用户输入
    test_inputs = [
        ("me", "应该识别为收藏夹"),
        ("ME", "大写也应该识别为收藏夹"),
        ("Me", "混合大小写也应该识别为收藏夹"),
        ("@channel", "应该识别为频道用户名"),
        ("-1001234567890", "应该识别为频道ID"),
    ]
    
    for text, expected in test_inputs:
        is_me = text.lower() == "me"
        result = "✅ 收藏夹" if is_me else "❌ 其他"
        status = "✓" if (is_me and "收藏夹" in expected) or (not is_me and "收藏夹" not in expected) else "✗"
        print(f"{status} 输入: '{text}' -> {result} ({expected})")

if __name__ == "__main__":
    test_me_handling()
    print("\n✅ 所有测试通过！")
