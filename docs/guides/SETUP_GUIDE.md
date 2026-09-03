# 快速设置指南 - Quick Setup Guide

[English](#english) | [中文](#中文)

---

## 中文

### 🚀 一键自动配置

本项目现在支持**自动登录并获取 Session String**，无需手动生成！

#### 准备工作

在开始之前，您需要：

1. **Bot Token** - 从 [@BotFather](https://t.me/BotFather) 获取
2. **API ID 和 API Hash** - 从 [my.telegram.org](https://my.telegram.org) 获取
3. **手机号** - 用于登录 Telegram（仅在需要访问私有内容时）

#### 快速开始

1. **克隆项目**

```bash
git clone <repository-url>
cd Save-Restricted-Content-Bot-Repo
```

2. **安装依赖**

```bash
pip install -r requirements.txt
```

3. **运行自动配置脚本**

```bash
python setup.py
```

脚本会引导您完成以下步骤：
- ✅ 输入 Bot Token
- ✅ 输入 API ID 和 API Hash
- ✅ 选择是否需要生成 Session String
- ✅ 如需要，自动登录 Telegram 并生成 Session String
- ✅ 自动保存配置到 `.env` 和 `config.json`

4. **启动机器人**

```bash
python main.py
```

或使用 Docker：

```bash
docker-compose up -d
```

### 📝 详细步骤

#### 步骤 1: 获取 Bot Token

1. 在 Telegram 中搜索 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 命令
3. 按提示设置机器人名称和用户名
4. 保存 BotFather 返回的 Token

#### 步骤 2: 获取 API 凭据

1. 访问 [my.telegram.org](https://my.telegram.org)
2. 使用手机号登录
3. 点击 "API development tools"
4. 填写应用信息（随便填）
5. 保存 `api_id` 和 `api_hash`

#### 步骤 3: 运行自动配置

运行配置脚本：

```bash
python setup.py
```

按照提示操作：

```
📋 步骤 1/4: Bot Token
请输入 Bot Token: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

📋 步骤 2/4: API 凭据
请输入 API ID: 12345678
请输入 API Hash: 0123456789abcdef0123456789abcdef

📋 步骤 3/4: Session String
是否需要生成 Session String? (y/n) [y]: y

📱 开始登录 Telegram 账号...
手机号: +8613800138000

⚠️  Telegram 将发送验证码到您的账号

Enter phone code: 12345
Enter password (if any): 
✅ Session String 生成成功！

📋 步骤 4/4: 保存配置
✅ 配置已保存到 .env 文件
✅ 配置已保存到 config.json 文件

✅ 配置完成！
```

### ⚙️ 配置说明

脚本会自动生成两个配置文件：

**`.env` 文件：**
```env
TOKEN=your_bot_token
ID=your_api_id
HASH=your_api_hash
STRING=your_session_string
```

**`config.json` 文件：**
```json
{
    "TOKEN": "your_bot_token",
    "ID": "your_api_id",
    "HASH": "your_api_hash",
    "STRING": "your_session_string"
}
```

### 🔧 手动配置（备选方案）

如果自动配置失败，您可以手动创建配置文件：

1. 复制示例文件：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入您的凭据

3. 手动生成 Session String（可选）：
```bash
python -c "from pyrogram import Client; app = Client('my_account', api_id=YOUR_API_ID, api_hash='YOUR_API_HASH'); app.start(); print(app.export_session_string())"
```

### 🐳 Docker 部署

配置完成后，使用 Docker Compose 一键部署：

```bash
docker-compose up -d
```

查看日志：
```bash
docker-compose logs -f
```

停止机器人：
```bash
docker-compose down
```

### ❓ 常见问题

**Q: Session String 是必需的吗？**
- A: 不是。如果只转发公开频道内容，可以跳过此步骤。只有访问私有频道或受限内容时才需要。

**Q: 配置脚本卡住不动？**
- A: 请检查网络连接，确保能访问 Telegram 服务器。也可以尝试使用代理。

**Q: 收不到验证码？**
- A: 验证码会发送到您的 Telegram 账号（不是手机短信）。请在 Telegram 客户端查看。

**Q: 已有 Session String，如何使用？**
- A: 可以跳过自动配置，直接编辑 `.env` 文件填入您的 Session String。

**Q: 如何重新配置？**
- A: 删除 `.env` 和 `config.json` 文件，重新运行 `python setup.py`。

### 🔒 安全提示

- ⚠️ **请勿分享您的配置文件** - 其中包含敏感凭据
- ⚠️ **Session String 等同于您的账号密码** - 请妥善保管
- ⚠️ **建议使用小号生成 Session String** - 避免主账号风险
- ✅ `.gitignore` 已配置忽略 `.env` 和 `config.json`

---

## English

### 🚀 One-Click Auto Configuration

This project now supports **automatic login and Session String generation** - no manual setup required!

#### Prerequisites

Before starting, you need:

1. **Bot Token** - Get from [@BotFather](https://t.me/BotFather)
2. **API ID and API Hash** - Get from [my.telegram.org](https://my.telegram.org)
3. **Phone Number** - For Telegram login (only if accessing private content)

#### Quick Start

1. **Clone the repository**

```bash
git clone <repository-url>
cd Save-Restricted-Content-Bot-Repo
```

2. **Install dependencies**

```bash
pip install -r requirements.txt
```

3. **Run the auto-configuration script**

```bash
python setup.py
```

The script will guide you through:
- ✅ Enter Bot Token
- ✅ Enter API ID and API Hash
- ✅ Choose whether to generate Session String
- ✅ Automatically login to Telegram and generate Session String
- ✅ Save configuration to `.env` and `config.json`

4. **Start the bot**

```bash
python main.py
```

Or using Docker:

```bash
docker-compose up -d
```

### 📝 Detailed Steps

#### Step 1: Get Bot Token

1. Search for [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot` command
3. Follow the prompts to set bot name and username
4. Save the Token returned by BotFather

#### Step 2: Get API Credentials

1. Visit [my.telegram.org](https://my.telegram.org)
2. Login with your phone number
3. Click "API development tools"
4. Fill in the application information (anything is fine)
5. Save the `api_id` and `api_hash`

#### Step 3: Run Auto Configuration

Run the setup script:

```bash
python setup.py
```

Follow the prompts:

```
📋 Step 1/4: Bot Token
Enter Bot Token: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

📋 Step 2/4: API Credentials
Enter API ID: 12345678
Enter API Hash: 0123456789abcdef0123456789abcdef

📋 Step 3/4: Session String
Generate Session String? (y/n) [y]: y

📱 Starting Telegram login...
Phone number: +1234567890

⚠️  Telegram will send a verification code to your account

Enter phone code: 12345
Enter password (if any): 
✅ Session String generated successfully!

📋 Step 4/4: Save Configuration
✅ Configuration saved to .env file
✅ Configuration saved to config.json file

✅ Setup complete!
```

### ⚙️ Configuration Files

The script automatically generates two configuration files:

**`.env` file:**
```env
TOKEN=your_bot_token
ID=your_api_id
HASH=your_api_hash
STRING=your_session_string
```

**`config.json` file:**
```json
{
    "TOKEN": "your_bot_token",
    "ID": "your_api_id",
    "HASH": "your_api_hash",
    "STRING": "your_session_string"
}
```

### 🔧 Manual Configuration (Alternative)

If auto-configuration fails, you can manually create config files:

1. Copy the example file:
```bash
cp .env.example .env
```

2. Edit the `.env` file with your credentials

3. Manually generate Session String (optional):
```bash
python -c "from pyrogram import Client; app = Client('my_account', api_id=YOUR_API_ID, api_hash='YOUR_API_HASH'); app.start(); print(app.export_session_string())"
```

### 🐳 Docker Deployment

After configuration, deploy with Docker Compose:

```bash
docker-compose up -d
```

View logs:
```bash
docker-compose logs -f
```

Stop the bot:
```bash
docker-compose down
```

### ❓ FAQ

**Q: Is Session String required?**
- A: No. If you only forward public channel content, you can skip this step. It's only needed for private channels or restricted content.

**Q: Setup script stuck?**
- A: Check your network connection and ensure you can access Telegram servers. Try using a proxy if needed.

**Q: Not receiving verification code?**
- A: The code is sent to your Telegram account (not SMS). Check your Telegram client.

**Q: I already have a Session String, how to use it?**
- A: You can skip auto-configuration and directly edit the `.env` file with your Session String.

**Q: How to reconfigure?**
- A: Delete `.env` and `config.json` files, then run `python setup.py` again.

### 🔒 Security Notice

- ⚠️ **Never share your configuration files** - They contain sensitive credentials
- ⚠️ **Session String equals your account password** - Keep it safe
- ⚠️ **Recommended to use secondary account** - Avoid risks to main account
- ✅ `.gitignore` is configured to ignore `.env` and `config.json`

---

## 📚 Additional Resources

- [Full README](README.md)
- [中文完整文档](README.zh-CN.md)
- [Docker Setup Guide](DOCKER_SETUP.md)
- [GitHub Issues](https://github.com/bipinkrish/Save-Restricted-Bot/issues)

## 💡 Tips

1. **First-time users**: Use the auto-configuration script for easiest setup
2. **Advanced users**: Manual configuration offers more control
3. **Docker users**: Make sure Docker is running before deployment
4. **Security**: Use environment variables for production deployments

---

**Need help?** Open an issue on GitHub or check the documentation.
