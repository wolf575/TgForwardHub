#!/usr/bin/env python3
"""
验证所有变更是否正确实现
Verify all changes are correctly implemented
"""

import re
import sys

def check_file_content(filepath, patterns, description):
    """检查文件中是否包含特定模式"""
    print(f"\n检查 {description}...")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        all_found = True
        for pattern_desc, pattern in patterns:
            if re.search(pattern, content):
                print(f"  ✅ {pattern_desc}")
            else:
                print(f"  ❌ {pattern_desc}")
                all_found = False
        
        return all_found
    except FileNotFoundError:
        print(f"  ❌ 文件不存在: {filepath}")
        return False

def main():
    print("=" * 60)
    print("功能变更验证 - Feature Changes Verification")
    print("=" * 60)
    
    all_checks_passed = True
    
    # 检查 main.py 中的关键变更
    main_py_checks = [
        ("preserve_forward_source 配置字段", r'preserve_forward_source'),
        ("preserve_source 参数解析", r"arg\.startswith\('preserve_source:'\)"),
        ("forward_messages 方法调用", r'forward_messages\('),
        ("copy_message 方法调用", r'copy_message\('),
        ("help 命令包含 preserve_source", r'preserve_source:true/false'),
        ("watch list 显示 preserve_forward_source", r'preserve_forward_source'),
        ("移除了关键词信息生成", r'keyword_info|匹配关键词'),  # 应该不存在
    ]
    
    with open('main.py', 'r', encoding='utf-8') as f:
        main_content = f.read()
    
    print("\n检查 main.py 核心功能...")
    
    # 检查应该存在的内容
    if 'preserve_forward_source' in main_content:
        print("  ✅ preserve_forward_source 字段已添加")
    else:
        print("  ❌ preserve_forward_source 字段缺失")
        all_checks_passed = False
    
    if "arg.startswith('preserve_source:')" in main_content:
        print("  ✅ preserve_source 参数解析已实现")
    else:
        print("  ❌ preserve_source 参数解析缺失")
        all_checks_passed = False
    
    if 'forward_messages(' in main_content:
        print("  ✅ forward_messages 方法已使用")
    else:
        print("  ❌ forward_messages 方法未使用")
        all_checks_passed = False
    
    if 'copy_message(' in main_content:
        print("  ✅ copy_message 方法已使用")
    else:
        print("  ❌ copy_message 方法未使用")
        all_checks_passed = False
    
    # 检查应该不存在的内容（关键词信息显示）
    if '🔍 匹配关键词' in main_content or 'keyword_info = f"' in main_content:
        print("  ❌ 关键词信息显示代码仍然存在（应该已移除）")
        all_checks_passed = False
    else:
        print("  ✅ 关键词信息显示代码已正确移除")
    
    # 检查 watch add 命令的帮助信息
    if 'preserve_source:true/false' in main_content:
        print("  ✅ help 命令包含 preserve_source 参数说明")
    else:
        print("  ❌ help 命令缺少 preserve_source 参数说明")
        all_checks_passed = False
    
    # 检查 watch list 命令显示
    if '保留转发来源' in main_content or 'preserve_forward_source' in main_content:
        print("  ✅ watch list 显示 preserve_forward_source 选项")
    else:
        print("  ❌ watch list 未显示 preserve_forward_source 选项")
        all_checks_passed = False
    
    # 检查测试文件
    print("\n检查 test_changes.py...")
    with open('test_changes.py', 'r', encoding='utf-8') as f:
        test_content = f.read()
    
    if 'test_preserve_forward_source' in test_content:
        print("  ✅ preserve_forward_source 测试函数已添加")
    else:
        print("  ❌ preserve_forward_source 测试函数缺失")
        all_checks_passed = False
    
    if 'preserve_forward_source' in test_content:
        print("  ✅ 测试包含 preserve_forward_source 验证")
    else:
        print("  ❌ 测试缺少 preserve_forward_source 验证")
        all_checks_passed = False
    
    # 检查文档更新
    print("\n检查文档更新...")
    doc_files = [
        ('CHANGES.md', 'preserve_forward_source'),
        ('IMPLEMENTATION_NOTES.md', 'preserve_forward_source'),
        ('FEATURE_UPDATE.md', 'preserve_forward_source'),
        ('FEATURE_CHANGES_SUMMARY.md', 'preserve_forward_source'),
    ]
    
    for doc_file, keyword in doc_files:
        try:
            with open(doc_file, 'r', encoding='utf-8') as f:
                if keyword in f.read():
                    print(f"  ✅ {doc_file} 已更新")
                else:
                    print(f"  ⚠️  {doc_file} 可能未完整更新")
        except FileNotFoundError:
            print(f"  ⚠️  {doc_file} 不存在")
    
    # 总结
    print("\n" + "=" * 60)
    if all_checks_passed:
        print("✅ 所有核心检查通过！")
        print("=" * 60)
        return 0
    else:
        print("❌ 部分检查未通过，请检查上述错误")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
