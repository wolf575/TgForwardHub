#!/usr/bin/env python3
"""验证所有新功能是否正确实现"""

import sys
import os

def check_file_exists(filepath, description):
    """检查文件是否存在"""
    exists = os.path.exists(filepath)
    status = "✅" if exists else "❌"
    print(f"{status} {description}: {filepath}")
    return exists

def check_code_content(filepath, search_text, description):
    """检查代码中是否包含特定内容"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            found = search_text in content
            status = "✅" if found else "❌"
            print(f"{status} {description}")
            return found
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return False

def main():
    print("="*60)
    print("🔍 验证所有新功能实现")
    print("="*60)
    
    all_passed = True
    
    print("\n1️⃣ 检查文件存在性...")
    all_passed &= check_file_exists("main.py", "机器人主文件")
    all_passed &= check_file_exists("app.py", "Web应用文件")
    all_passed &= check_file_exists("templates/notes.html", "笔记模板文件")
    all_passed &= check_file_exists("NEW_FEATURES.md", "新功能说明")
    all_passed &= check_file_exists("UPDATE_v2.0.md", "更新文档")
    
    print("\n2️⃣ 检查'me'监控功能...")
    all_passed &= check_code_content(
        "main.py",
        'if text.lower() == "me":',
        "handle_add_source函数包含'me'处理"
    )
    all_passed &= check_code_content(
        "main.py",
        "filters.channel | filters.group | filters.private",
        "消息过滤器包含私聊"
    )
    all_passed &= check_code_content(
        "main.py",
        "输入 `me` 监控自己的收藏夹",
        "添加监控说明包含'me'"
    )
    
    print("\n3️⃣ 检查搜索高亮功能...")
    all_passed &= check_code_content(
        "app.py",
        "@app.template_filter('highlight')",
        "Flask包含高亮过滤器"
    )
    all_passed &= check_code_content(
        "app.py",
        "from markupsafe import Markup, escape",
        "导入markupsafe库"
    )
    all_passed &= check_code_content(
        "templates/notes.html",
        ".highlight",
        "模板包含高亮CSS类"
    )
    all_passed &= check_code_content(
        "templates/notes.html",
        "| highlight(search_query) | safe",
        "模板使用高亮过滤器"
    )
    
    print("\n4️⃣ 检查UI简化功能...")
    all_passed &= check_code_content(
        "templates/notes.html",
        "class=\"menu-toggle\"",
        "包含汉堡菜单按钮"
    )
    all_passed &= check_code_content(
        "templates/notes.html",
        "class=\"menu-dropdown\"",
        "包含下拉菜单"
    )
    all_passed &= check_code_content(
        "templates/notes.html",
        "function toggleMenu()",
        "包含菜单切换JavaScript"
    )
    all_passed &= check_code_content(
        "templates/notes.html",
        "grid-template-columns: repeat(auto-fill, minmax(300px",
        "卡片网格使用300px最小宽度"
    )
    
    print("\n5️⃣ 检查启动配置显示...")
    all_passed &= check_code_content(
        "main.py",
        "def print_startup_config():",
        "包含启动配置函数"
    )
    all_passed &= check_code_content(
        "main.py",
        "print_startup_config()",
        "调用启动配置函数"
    )
    all_passed &= check_code_content(
        "main.py",
        "🤖 Telegram Save-Restricted Bot 启动成功",
        "包含启动成功消息"
    )
    
    print("\n" + "="*60)
    if all_passed:
        print("✅ 所有功能验证通过！")
        print("="*60)
        return 0
    else:
        print("❌ 部分功能验证失败，请检查上述错误")
        print("="*60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
