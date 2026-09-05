# 初始配置指南

## 获取 Telegram 凭据

1. 在 Telegram 联系 `@BotFather`，发送 `/newbot` 创建机器人，取得 Bot Token。
2. 登录 [my.telegram.org](https://my.telegram.org)，创建应用，取得 API ID 和 API Hash。
3. 准备好要用于 Telegram 用户客户端的手机号；项目不会保存短信验证码或两步验证密码。

## Web UI 初始化

Docker 容器启动后打开 Web 页面：

1. 使用默认账号 `admin` / `admin` 登录。
2. 打开「设置 → 初始配置 / Session String」。
3. 填写 Bot Token、API ID 和 API Hash，点击保存。
4. 填写 Telegram 手机号，点击「发送验证码并生成 Session String」。
5. 输入 Telegram 收到的验证码。
6. 如果账号开启两步验证，输入两步验证密码。
7. 后台检测到配置后自动启动 Telegram Bot 和用户客户端。

配置会保存到持久化的 `data/config/config.json`。Docker 部署不需要创建或编辑 `.env`。

## Docker Run

```bash
docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  -e DATA_DIR=/app/data \
  -e PORT=10000 \
  -e TZ=Asia/Shanghai \
  ghcr.io/wolf575/tg-forward-hub:latest
```

## Docker Compose

```bash
cd TgForwardHub
docker compose up -d --build
```

Compose 文件只声明端口、数据目录和基础环境，不读取 Bot 凭据。

## 修改或重置配置

- 在 Web UI「设置」页直接修改 Telegram 凭据并保存。
- 如果必须重置，删除宿主机持久化目录中的 `data/config/config.json`，重启容器后重新初始化。
- 不要在 Docker 命令中加入 `--env-file .env`。

## 常见问题

**提示 HTTP 503 或用户客户端未连接**

检查用户客户端的 Session String 是否已经完整生成；如果重新填写了手机号，需要依次完成验证码和两步验证后再保存。修改账号后，重新获取一次验证码，不要复用旧验证码。

**保存 Bot Token 后机器人仍未运行**

查看 `docker logs -f tg-forward-hub`。确认 Bot Token、API ID、API Hash 与 Telegram 官方页面一致，并确认服务器能够访问 Telegram API。
