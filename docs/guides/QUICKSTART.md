# 快速开始 | Quick Start

[中文](#中文) | [English](#english)

---

## 中文

### 🚀 3分钟快速部署

只需3个简单步骤即可完成部署！

#### 第 1 步：准备凭据

在开始之前，请准备好：
- **Bot Token**：在 Telegram 搜索 [@BotFather](https://t.me/BotFather)，发送 `/newbot` 获取
- **API 凭据**：访问 [my.telegram.org](https://my.telegram.org)，获取 API ID 和 API Hash

#### 第 2 步：克隆并配置

```bash
# 克隆项目
git clone <repository-url>
cd Save-Restricted-Content-Bot-Repo

# 安装依赖
pip install -r requirements.txt

# 运行自动配置（推荐）
python setup.py
```

或者手动创建 `.env` 文件：
```env
TOKEN=your_bot_token_here
ID=your_api_id_here
HASH=your_api_hash_here
STRING=your_session_string_here_or_leave_empty
```

#### 第 3 步：启动机器人

```bash
# 方式 1：直接运行
python main.py

# 方式 2：使用 Docker Compose（推荐生产环境）
docker-compose up -d
```

### ✅ 完成！

现在可以在 Telegram 中向你的机器人发送受限内容链接了！

### 📚 更多信息

- [详细设置指南](SETUP_GUIDE.md)
- [完整文档](README.md)
- [中文详细文档](README.zh-CN.md)

---

## English

### 🚀 3-Minute Quick Deploy

Get your bot running in just 3 simple steps!

#### Step 1: Prepare Credentials

Before starting, prepare:
- **Bot Token**: Search [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot` to get token
- **API Credentials**: Visit [my.telegram.org](https://my.telegram.org) to get API ID and API Hash

#### Step 2: Clone and Configure

```bash
# Clone the repository
git clone <repository-url>
cd Save-Restricted-Content-Bot-Repo

# Install dependencies
pip install -r requirements.txt

# Run auto-configuration (recommended)
python setup.py
```

Or manually create `.env` file:
```env
TOKEN=your_bot_token_here
ID=your_api_id_here
HASH=your_api_hash_here
STRING=your_session_string_here_or_leave_empty
```

#### Step 3: Start the Bot

```bash
# Method 1: Direct run
python main.py

# Method 2: Using Docker Compose (recommended for production)
docker-compose up -d
```

### ✅ Done!

Now you can send restricted content links to your bot on Telegram!

### 📚 More Information

- [Detailed Setup Guide](SETUP_GUIDE.md)
- [Full Documentation](README.md)
- [Chinese Documentation](README.zh-CN.md)

---

## 常见问题 | FAQ

### Q: Session String是必需的吗？ | Is Session String required?
**A:** 不是必需的。如果只转发公开频道，可以留空。只有访问私有频道时才需要。

**A:** Not required. If you only forward public channels, leave it empty. Only needed for private channels.

### Q: 如何获取Session String？ | How to get Session String?
**A:** 运行 `python setup.py`，脚本会自动帮你生成。

**A:** Run `python setup.py`, the script will generate it automatically.

### Q: 配置错误怎么办？ | Configuration error?
**A:** 删除 `.env` 和 `config.json` 文件，重新运行 `python setup.py`。

**A:** Delete `.env` and `config.json` files, then run `python setup.py` again.

---

**需要帮助？ | Need Help?**

查看 [详细设置指南](SETUP_GUIDE.md) 或提交 [GitHub Issue](https://github.com/bipinkrish/Save-Restricted-Bot/issues)

See [Detailed Setup Guide](SETUP_GUIDE.md) or submit a [GitHub Issue](https://github.com/bipinkrish/Save-Restricted-Bot/issues)
