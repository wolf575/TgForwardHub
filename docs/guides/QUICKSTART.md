# 快速开始

## 1. 启动公开镜像

准备一台安装 Docker 的 Linux 服务器，然后执行：

```bash
mkdir -p /docker-data/tfh/data /docker-data/tfh/downloads

docker pull ghcr.io/wolf575/tg-forward-hub:latest

docker rm -f tg-forward-hub 2>/dev/null || true

docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  ghcr.io/wolf575/tg-forward-hub:latest
```

镜像已经公开，不需要 GitHub 登录，也不需要 `read:packages` Token。

容器内端口固定为 `10000`，这里映射到宿主机 `10001`。打开：

```text
http://服务器IP:10001
```

## 2. 登录并修改密码

默认账号：

```text
用户名：admin
密码：admin
```

第一次登录后，进入「设置 → 账号与密码」修改用户名和密码。

## 3. 准备 Telegram 凭据

需要准备：

1. Bot Token：在 Telegram 联系 `@BotFather`，使用 `/newbot` 创建。
2. API ID 和 API Hash：登录 [my.telegram.org](https://my.telegram.org) 创建应用。
3. 用于用户客户端的 Telegram 手机号。

## 4. 完成网页初始化

1. 打开「设置 → 初始配置 / Session String」。
2. 填写 Bot Token、API ID 和 API Hash。
3. 填写 Telegram 手机号。
4. 点击「发送验证码并生成 Session String」。
5. 输入验证码。
6. 如果账号开启两步验证，再输入两步验证密码。
7. 等待「Telegram Bot」和「用户客户端」显示已连接。

项目不需要 `.env`，也不要在启动命令中添加 `--env-file .env`。

## 5. 执行第一个批量任务

1. 打开「批量转发」。
2. 来源填写 `@channel_name` 或 `-100...`。
3. 目标填写目标频道 ID，或填写 `me` 发送到收藏夹。
4. 选择消息 ID 范围或日期范围。
5. 先使用默认 `clone（隐藏来源）`。
6. 点击「生成并执行」。

如果来源限制缓存复制，可以先使用默认模式测试。需要 Bot 中转时，选择 `cache` 并填写「中转缓冲会话」。

## 6. 添加第一个监控任务

1. 在 Bot 中发送 `/watch`。
2. 点击「添加监控」。
3. 输入来源 ID、`@username` 或 `me`。
4. 选择记录模式或转发模式。
5. 设置目标、过滤规则和提取规则。
6. 保存后发送一条测试消息。

## 7. 查看日志

```bash
docker logs -f --tail=200 tg-forward-hub
```

## 8. 更新

保留原来的 `data` 和 `downloads` 挂载目录，重新拉取并创建容器：

```bash
docker pull ghcr.io/wolf575/tg-forward-hub:latest
docker rm -f tg-forward-hub

docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  ghcr.io/wolf575/tg-forward-hub:latest
```

## 常见问题

**镜像仍然要求登录**

确认镜像名是 `ghcr.io/wolf575/tg-forward-hub:latest`。如果本机保存了旧 GHCR 凭据，可以执行：

```bash
docker logout ghcr.io
docker pull ghcr.io/wolf575/tg-forward-hub:latest
```

**提示 `--env-file: open .env: no such file or directory`**

删除命令中的 `--env-file .env`。本项目通过 Web UI 保存配置。

**用户客户端未连接**

回到「设置」重新完成手机号、验证码和两步验证。修改 Telegram 凭据后，重启容器通常更稳妥。

**端口被占用**

修改 `-p` 左侧端口，例如改为 `-p 10002:10000`，容器内端口仍然是 `10000`。

更多说明：

- [Docker 部署](DOCKER_SETUP.md)
- [初始配置](SETUP_GUIDE.md)
- [使用示例](USAGE_EXAMPLES.md)
