# Config.json 优先级更新说明

## 📋 问题描述

**之前的行为：**
- `main.py` 中的 `getenv()` 函数优先读取环境变量，然后才回退到 config.json
- `setup.py` 生成的 session string 保存到 `./config.json`（根目录）
- `main.py` 从 `$DATA_DIR/config/config.json` 读取配置
- 导致 setup.py 生成的 session string 无法被使用，需要手动同步到 .env 文件

**旧逻辑：**
```python
def getenv(var):
    return os.environ.get(var) or DATA.get(var)  # ❌ 环境变量优先
```

## ✅ 解决方案

### 1. 修改 `main.py` 中的 `getenv()` 函数

**新逻辑（优先级）：**
1. 优先从 `config.json` 读取（`DATA.get(var)`）
2. 如果 config.json 中没有，再从环境变量读取（`os.environ.get(var)`）

**新代码：**
```python
def getenv(var):
    """Get configuration value, prioritizing config file over environment variables
    
    Priority:
    1. config.json (DATA) - configuration saved by setup.py
    2. Environment variables - fallback if config.json doesn't have the value
    """
    # Prioritize config file (DATA) first
    config_value = DATA.get(var)
    if config_value:
        return config_value
    # Fallback to environment variable
    return os.environ.get(var)
```

### 2. 修改 `setup.py` 保存路径

**之前：** 保存到 `./config.json`（根目录）
**现在：** 保存到 `$DATA_DIR/config/config.json`（与 main.py 一致）

**更新：**
```python
# 添加数据目录配置
DEFAULT_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data'))
DATA_DIR = os.environ.get('DATA_DIR', DEFAULT_DATA_DIR)
CONFIG_DIR = os.path.join(DATA_DIR, 'config')
os.makedirs(CONFIG_DIR, exist_ok=True)

# 修改保存函数
def save_to_config_json(token, api_id, api_hash, session_string):
    config_file = os.path.join(CONFIG_DIR, 'config.json')  # ✅ 使用正确路径
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)
```

### 3. 添加日志记录

在 `main.py` 中添加日志，显示 session string 的来源：

```python
if ss is not None:
    if DATA.get("STRING"):
        logger.info("✅ 使用 config.json 中的 session string")
    else:
        logger.info("✅ 使用环境变量 STRING 中的 session string")
    
    acc = Client("myacc", api_id=api_id, api_hash=api_hash, session_string=ss)
    acc.start()
else: 
    logger.warning("⚠️ 未找到 session string，acc 客户端未初始化")
    acc = None
```

## 🎯 使用流程

### 场景 1: 使用 setup.py 生成新的 session（推荐）

```bash
# 1. 运行 setup.py
python3 setup.py

# 2. 按提示输入信息
#    - Bot Token
#    - API ID 和 API Hash
#    - 手机号（生成 session string）

# 3. setup.py 会保存配置到 data/config/config.json

# 4. 重启容器或重启 main.py
docker-compose restart  # Docker 环境
# 或
python3 main.py  # 本地环境

# 5. 查看日志，确认使用 config.json 中的 session string
# 输出: ✅ 使用 config.json 中的 session string
```

### 场景 2: 使用环境变量（作为备选）

```bash
# 1. 在 .env 文件中设置
STRING=your_session_string_here

# 2. 如果 config.json 中没有 STRING，会自动使用环境变量
# 输出: ✅ 使用环境变量 STRING 中的 session string
```

### 场景 3: 配置优先级验证

```bash
# 1. config.json 中有 STRING: "config_value"
# 2. .env 中也有 STRING: "env_value"

# 结果: 使用 "config_value" (config.json 优先)
# 输出: ✅ 使用 config.json 中的 session string
```

## 📊 优先级规则

| 配置项 | config.json | 环境变量 | 结果 | 日志 |
|--------|-------------|----------|------|------|
| STRING | ✅ 存在 | ✅ 存在 | 使用 config.json | `使用 config.json 中的 session string` |
| STRING | ✅ 存在 | ❌ 不存在 | 使用 config.json | `使用 config.json 中的 session string` |
| STRING | ❌ 不存在 | ✅ 存在 | 使用环境变量 | `使用环境变量 STRING 中的 session string` |
| STRING | ❌ 不存在 | ❌ 不存在 | None | `未找到 session string，acc 客户端未初始化` |

## 🔍 验证方法

### 方法 1: 运行测试脚本

```bash
python3 test_config_priority.py
```

**预期输出：**
```
============================================================
🧪 测试 config.json 优先级
============================================================

📋 测试用例 1: config.json 和环境变量都有 STRING
✅ 测试通过！config.json 优先级高于环境变量

📋 测试用例 2: config.json 中没有 OWNER_ID，回退到环境变量
✅ 测试通过！正确回退到环境变量

📋 测试用例 3: config.json 和环境变量都没有 UNKNOWN_KEY
✅ 测试通过！正确返回 None

============================================================
🎉 所有测试通过！
============================================================
```

### 方法 2: 查看启动日志

```bash
python3 main.py
```

**日志输出示例：**
```
✅ 使用 config.json 中的 session string
🤖 Telegram Save-Restricted Bot 启动成功
```

### 方法 3: 检查配置文件

```bash
# 查看 config.json 内容
cat data/config/config.json
```

**预期内容：**
```json
{
    "TOKEN": "your_bot_token",
    "ID": "your_api_id",
    "HASH": "your_api_hash",
    "STRING": "your_session_string"
}
```

## 🚀 优势

### 1. 简化工作流
- ✅ 无需手动更新 .env 文件
- ✅ setup.py 的输出能被正确使用
- ✅ 一次配置，持久生效

### 2. 数据持久化更清晰
- ✅ 所有配置集中在 `data/config/config.json`
- ✅ Docker 环境中只需挂载 `data` 目录
- ✅ 配置不会因为重启容器而丢失

### 3. 向后兼容
- ✅ 仍然支持环境变量（作为备选）
- ✅ 不影响现有的 .env 配置
- ✅ 旧配置可以平滑迁移

## 🔄 迁移指南

### 从环境变量迁移到 config.json

```bash
# 1. 运行 setup.py，或手动创建 config.json
mkdir -p data/config
cat > data/config/config.json << EOF
{
    "TOKEN": "your_bot_token",
    "ID": "your_api_id",
    "HASH": "your_api_hash",
    "STRING": "your_session_string"
}
EOF

# 2. 重启服务
docker-compose restart  # Docker
# 或
python3 main.py  # 本地

# 3. 验证日志
# 应该看到: ✅ 使用 config.json 中的 session string

# 4. (可选) 从 .env 中移除配置
# 但保留 .env 作为备选不会有问题
```

## 📝 文件变更列表

### 修改的文件

1. **main.py**
   - 修改 `getenv()` 函数逻辑（优先 config.json）
   - 添加 session string 来源日志

2. **setup.py**
   - 添加 DATA_DIR、CONFIG_DIR 配置
   - 修改 `save_to_config_json()` 保存路径
   - 确保目录自动创建

### 新增的文件

1. **test_config_priority.py** - 测试脚本，验证配置优先级
2. **CONFIG_PRIORITY_UPDATE.md** - 本文档

## ❓ 常见问题

### Q1: 为什么要优先使用 config.json？

**A:** 
- setup.py 生成的 session string 直接保存到 config.json
- 避免手动同步到 .env 的额外步骤
- 更符合"配置即代码"的最佳实践

### Q2: 环境变量还有用吗？

**A:** 
- 有用！作为备选方案
- 如果 config.json 中没有配置，会自动使用环境变量
- 适合 CI/CD 环境或容器编排

### Q3: 现有的 .env 配置会受影响吗？

**A:** 
- 不会！完全向后兼容
- 如果 config.json 不存在或为空，仍然使用 .env
- 可以逐步迁移，无需一次性修改

### Q4: Docker 环境下如何使用？

**A:** 
```yaml
# docker-compose.yml
volumes:
  - ./data:/app/data  # 挂载 data 目录，包含 config.json

# 运行 setup.py 时，配置会保存到挂载的 data/config/config.json
# 重启容器后配置自动生效
```

### Q5: 如何确认正在使用哪个配置源？

**A:** 
查看启动日志：
- `✅ 使用 config.json 中的 session string` - 使用 config.json
- `✅ 使用环境变量 STRING 中的 session string` - 使用环境变量
- `⚠️ 未找到 session string，acc 客户端未初始化` - 都没找到

## 🎉 总结

这次更新实现了：
1. ✅ setup.py 生成的 session string 自动被使用
2. ✅ 无需手动同步 .env 文件
3. ✅ 配置优先级清晰：config.json > 环境变量
4. ✅ 完全向后兼容
5. ✅ Docker 环境数据持久化更简单

**现在的工作流：**
```bash
python3 setup.py  # 生成并保存 session string
# ↓
data/config/config.json  # 自动保存
# ↓
python3 main.py  # 自动读取并使用
# ↓
✅ 使用 config.json 中的 session string
```

**不再需要：**
```bash
python3 setup.py
# ↓
手动复制 session string  # ❌ 不需要了！
# ↓
编辑 .env 文件  # ❌ 不需要了！
# ↓
重启服务
```

---

**更新日期：** 2024
**版本：** v2.1
**影响：** main.py, setup.py
