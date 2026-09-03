# Docker 部署快速指南 / Docker Setup Quick Guide

[English](#english) | [中文](#中文)

---

## English

### Quick Start with Docker Compose

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in your credentials
3. Run `docker-compose up -d`

### Environment Variables

- `TOKEN`: Your bot token from @BotFather
- `ID`: Your API ID from my.telegram.org
- `HASH`: Your API Hash from my.telegram.org
- `STRING`: Your session string (optional)

### Useful Commands

```bash
# Start the bot
docker-compose up -d

# View logs
docker-compose logs -f

# Restart the bot
docker-compose restart

# Stop the bot
docker-compose down

# Update the bot
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

---

## 中文

### 使用 Docker Compose 快速开始

1. 克隆仓库
2. 复制 `.env.example` 为 `.env` 并填入你的凭据
3. 运行 `docker-compose up -d`

### 环境变量

- `TOKEN`: 从 @BotFather 获取的机器人 token
- `ID`: 从 my.telegram.org 获取的 API ID
- `HASH`: 从 my.telegram.org 获取的 API Hash
- `STRING`: 会话字符串（可选）

### 常用命令

```bash
# 启动机器人
docker-compose up -d

# 查看日志
docker-compose logs -f

# 重启机器人
docker-compose restart

# 停止机器人
docker-compose down

# 更新机器人
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### 目录结构

```
.
├── main.py              # 主程序
├── app.py               # Flask Web 服务
├── Dockerfile           # Docker 镜像配置
├── docker-compose.yml   # Docker Compose 配置
├── .env.example         # 环境变量示例
├── config.json.example  # 配置文件示例
├── requirements.txt     # Python 依赖
└── downloads/           # 下载文件目录（自动创建）
```
