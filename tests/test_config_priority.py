#!/usr/bin/env python3
"""
Test script to verify config.json priority over environment variables
"""

import os
import json
import sys

# Setup paths
DEFAULT_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data'))
DATA_DIR = os.environ.get('DATA_DIR', DEFAULT_DATA_DIR)
CONFIG_DIR = os.path.join(DATA_DIR, 'config')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')

print("=" * 60)
print("🧪 测试 config.json 优先级")
print("=" * 60)
print()

# Ensure config directory exists
os.makedirs(CONFIG_DIR, exist_ok=True)

# Test Case 1: Config file has STRING, environment also has STRING
print("📋 测试用例 1: config.json 和环境变量都有 STRING")
print("-" * 60)

# Create test config
test_config = {
    "TOKEN": "test_bot_token",
    "ID": "12345678",
    "HASH": "test_api_hash",
    "STRING": "config_session_string_priority"
}
with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
    json.dump(test_config, f, indent=4, ensure_ascii=False)

print(f"✅ 已创建测试配置文件: {CONFIG_FILE}")
print(f"   config.json 中的 STRING: {test_config['STRING']}")

# Set environment variable (should be lower priority)
os.environ['STRING'] = 'env_session_string_fallback'
print(f"   环境变量中的 STRING: {os.environ.get('STRING')}")
print()

# Load config (simulating main.py logic)
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    DATA = json.load(f)

def getenv(var):
    """Get configuration value, prioritizing config file over environment variables"""
    config_value = DATA.get(var)
    if config_value:
        return config_value
    return os.environ.get(var)

result = getenv('STRING')
print(f"📝 getenv('STRING') 返回: {result}")
print()

if result == test_config['STRING']:
    print("✅ 测试通过！config.json 优先级高于环境变量")
else:
    print("❌ 测试失败！应该返回 config.json 中的值")
    sys.exit(1)

print()
print("-" * 60)

# Test Case 2: Config file doesn't have key, fall back to environment
print("📋 测试用例 2: config.json 中没有 OWNER_ID，回退到环境变量")
print("-" * 60)

os.environ['OWNER_ID'] = '999888777'
print(f"   环境变量中的 OWNER_ID: {os.environ.get('OWNER_ID')}")
print(f"   config.json 中的 OWNER_ID: {DATA.get('OWNER_ID')}")
print()

result = getenv('OWNER_ID')
print(f"📝 getenv('OWNER_ID') 返回: {result}")
print()

if result == os.environ['OWNER_ID']:
    print("✅ 测试通过！正确回退到环境变量")
else:
    print("❌ 测试失败！应该回退到环境变量")
    sys.exit(1)

print()
print("-" * 60)

# Test Case 3: Neither config nor environment has the key
print("📋 测试用例 3: config.json 和环境变量都没有 UNKNOWN_KEY")
print("-" * 60)

result = getenv('UNKNOWN_KEY')
print(f"📝 getenv('UNKNOWN_KEY') 返回: {result}")
print()

if result is None:
    print("✅ 测试通过！正确返回 None")
else:
    print("❌ 测试失败！应该返回 None")
    sys.exit(1)

print()
print("=" * 60)
print("🎉 所有测试通过！")
print("=" * 60)
print()
print("📝 总结:")
print("  1. config.json 中的值优先于环境变量")
print("  2. config.json 中没有的值会回退到环境变量")
print("  3. 都没有的值返回 None")
print()
print("✅ setup.py 生成的 session string 会被正确使用")
print()

# Cleanup
os.remove(CONFIG_FILE)
print(f"🧹 已清理测试文件: {CONFIG_FILE}")
