# 时区修复说明 (Timezone Fix)

## 问题描述

之前版本的 Save-Restricted-Bot 使用 UTC 时间（世界标准时间）来记录笔记的时间戳，导致中国用户看到的时间比实际时间早 8 小时。

**示例问题：**
- 实际时间：2024年1月15日 下午 3:00 (北京时间)
- 显示时间：2024年1月15日 上午 7:00 (早了8小时)

## 修复内容

现在系统已经修复，默认使用中国时区（Asia/Shanghai，UTC+8）来记录和显示时间。

### 1. 代码层面修复

#### 修改的文件：
- `main.py` - 所有时间戳生成使用中国时区
- `database.py` - 数据库存储时间使用中国时区
- `clean_duplicates.py` - 备份文件名使用中国时区

#### 实现方式：
使用 Python 的 `zoneinfo` 模块：
```python
from zoneinfo import ZoneInfo
CHINA_TZ = ZoneInfo("Asia/Shanghai")

# 生成时间戳时使用
datetime.now(CHINA_TZ).strftime('%Y%m%d_%H%M%S')
```

### 2. 环境配置

#### Docker Compose 部署
在 `docker-compose.yml` 中添加了 `TZ=Asia/Shanghai` 环境变量：
```yaml
environment:
  - TZ=Asia/Shanghai
```

#### 本地运行
在 `.env` 文件中添加：
```env
TZ=Asia/Shanghai
```

或在启动前设置环境变量：
```bash
# Linux/macOS
export TZ=Asia/Shanghai
python main.py

# Windows (PowerShell)
$env:TZ = "Asia/Shanghai"
python main.py

# Windows (CMD)
set TZ=Asia/Shanghai
python main.py
```

### 3. 数据库时间戳

新记录的笔记将使用中国时区时间：
- 数据库存储格式：`YYYY-MM-DD HH:MM:SS` (中国时区)
- 网页显示：直接显示数据库中的时间（已经是正确的中国时间）
- 日志时间：所有日志也使用中国时区

## 使用说明

### 新部署用户

如果你是第一次部署，不需要任何额外操作：
1. 按照 README.md 的指引正常部署
2. 系统会自动使用中国时区

### 已有部署的用户

如果你已经部署了旧版本：

#### 更新代码
```bash
cd Save-Restricted-Content-Bot-Repo
git pull
```

#### Docker Compose 用户
1. 更新代码后，重启容器：
```bash
docker-compose down
docker-compose up -d
```

2. 查看日志确认时区正确：
```bash
docker-compose logs -f
```

#### 本地运行用户
1. 在 `.env` 文件中添加 `TZ=Asia/Shanghai`
2. 重启 Bot：
```bash
# 停止当前运行的 Bot (Ctrl+C)
# 然后重新启动
python main.py
```

### 历史数据

**重要说明：**
- 旧的笔记记录（升级前创建的）时间戳可能仍显示为 UTC 时间
- 新的笔记记录（升级后创建的）将正确显示中国时间
- 如果需要，可以手动修改历史数据的时间戳（不推荐，除非必要）

## 自定义时区

如果你不在中国，可以修改为其他时区：

### 常用时区列表
- 中国：`Asia/Shanghai` (UTC+8)
- 日本：`Asia/Tokyo` (UTC+9)
- 韩国：`Asia/Seoul` (UTC+9)
- 新加坡：`Asia/Singapore` (UTC+8)
- 泰国：`Asia/Bangkok` (UTC+7)
- 印度：`Asia/Kolkata` (UTC+5:30)
- 迪拜：`Asia/Dubai` (UTC+4)
- 莫斯科：`Europe/Moscow` (UTC+3)
- 英国：`Europe/London` (UTC+0)
- 纽约：`America/New_York` (UTC-5)
- 洛杉矶：`America/Los_Angeles` (UTC-8)

### 修改方法

#### Docker Compose
编辑 `docker-compose.yml`：
```yaml
environment:
  - TZ=Asia/Tokyo  # 修改为你的时区
```

#### 本地运行
编辑 `.env` 文件：
```env
TZ=Asia/Tokyo  # 修改为你的时区
```

## 验证时区设置

### 查看 Bot 日志
启动 Bot 后，日志中的时间应该是你当地的正确时间：
```
2024-01-15 15:30:45 - __main__ - INFO - Bot started
```

### 创建测试笔记
1. 设置一个监控任务（开启记录模式）
2. 发送一条测试消息
3. 在网页界面查看笔记的时间戳
4. 确认时间与当前时间一致

## 技术细节

### 为什么选择 zoneinfo？
- Python 3.9+ 标准库，无需额外依赖
- 支持完整的 IANA 时区数据库
- 自动处理夏令时转换
- 性能优秀，线程安全

### 时区处理策略
1. **文件命名**：使用本地时区（便于识别）
2. **数据库存储**：存储本地时区的字符串格式
3. **日志记录**：Python logging 自动使用系统时区
4. **网页显示**：直接显示数据库中的时间（已经是正确时区）

## 常见问题

### Q1: 更新后旧笔记时间还是错的？
A: 旧笔记是用 UTC 时间存储的，显示会早 8 小时。新笔记会正确显示。如果需要修正旧数据，可以手动调整数据库（高级操作，不建议新手尝试）。

### Q2: Docker 容器内时区不生效？
A: 确保 `docker-compose.yml` 中正确设置了 `TZ` 环境变量，并且已经重启容器：
```bash
docker-compose down
docker-compose up -d
```

### Q3: 如何验证容器内的时区？
A: 进入容器查看：
```bash
docker-compose exec telegram-bot date
```
应该显示正确的本地时间。

### Q4: Python 提示找不到 zoneinfo 模块？
A: `zoneinfo` 是 Python 3.9+ 的标准库。如果你使用 Python 3.8 或更早版本，需要升级 Python：
```bash
# 检查 Python 版本
python --version

# 建议升级到 Python 3.11 或更高版本
```

## 相关文件

修改涉及的文件列表：
- `main.py` - 添加时区导入和使用
- `database.py` - 添加时区导入和时间戳生成
- `clean_duplicates.py` - 添加时区导入和文件命名
- `docker-compose.yml` - 添加 TZ 环境变量
- `.env.example` - 添加 TZ 配置示例
- `TIMEZONE_FIX.md` - 本文档

## 更新日志

- **2024年版本**: 修复时区问题，默认使用 Asia/Shanghai (UTC+8)
- 所有新记录的笔记使用正确的中国时间
- 日志时间正确显示
- 文件命名使用正确的时间戳

---

**如有问题，请提交 Issue 或查看项目文档。**
