# 初始配置指南

## 启动容器

公开镜像可以直接匿名拉取：

```bash
mkdir -p /docker-data/tfh/data /docker-data/tfh/downloads

docker pull ghcr.io/wolf575/tg-forward-hub:latest

docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  ghcr.io/wolf575/tg-forward-hub:latest
```

打开 `http://服务器IP:10001`。

## 准备 Telegram 凭据

### Bot Token

1. 在 Telegram 联系 `@BotFather`。
2. 发送 `/newbot`，按提示创建机器人。
3. 保存 BotFather 返回的 Token。

Bot Token 格式类似：

```text
123456789:AA...
```

### API ID 和 API Hash

1. 登录 [my.telegram.org](https://my.telegram.org)。
2. 打开「API development tools」。
3. 创建应用。
4. 保存 `api_id` 和 `api_hash`。

### 用户客户端账号

准备一个 Telegram 手机号。该项目需要一个用户账号来执行：

- 网页批量转发
- 实时监控
- 私有频道读取
- 受限内容下载重传

建议使用专用账号，并确认账号已经加入需要访问的频道或群组。

## 网页初始化

### 登录

默认账号：

```text
用户名：admin
密码：admin
```

登录后立即进入「设置 → 账号与密码」修改密码。

### 保存 Bot 配置

进入「设置 → 初始配置 / Session String」：

1. 填写 Bot Token。
2. 填写 API ID。
3. 填写 API Hash。
4. 点击「保存配置」。

### 生成 Session String

1. 在同一个表单填写 Telegram 手机号，包含国家区号。
2. 点击「发送验证码并生成 Session String」。
3. 输入 Telegram 客户端收到的验证码。
4. 如果账号开启两步验证，输入两步验证密码。
5. 等待页面显示 Session String 已生成。

后台会自动把配置写入持久化的：

```text
data/config/config.json
```

### 检查运行状态

「设置」页会显示：

- 网页端
- Telegram Bot
- 用户客户端
- 监控源数量

Bot 和用户客户端都显示已连接后，再开始批量转发或监控任务。

## 配置持久化

Docker 部署必须挂载：

```text
/docker-data/tfh/data → /app/data
/docker-data/tfh/downloads → /app/downloads
```

`data` 目录包含：

- Telegram 配置和 Session
- 监控任务
- 笔记数据库
- 批量任务历史
- WebDAV 配置
- 应用设置
- 记录媒体

删除容器不会删除这些数据，但删除宿主机目录会。

## 修改配置

### 修改 Bot Token 或 API 信息

在 Web UI 中重新填写并保存。修改已生效的凭据后，建议重启容器：

```bash
docker restart tg-forward-hub
```

### 重新生成 Session String

在设置页点击重新配置，按手机号、验证码和两步验证流程重新生成。不要复用旧验证码。

### 重置全部配置

先停止容器并备份数据，然后删除：

```bash
/docker-data/tfh/data/config/config.json
```

重新启动容器后，在 Web UI 中完成初始化。

## 安全要求

- Session String 等同于 Telegram 账号登录凭据。
- 不要把 `data/config/config.json` 提交到 Git。
- 不要把 Session String 发到公开 Issue。
- 不要公开 WebDAV 用户名和密码。
- 公网部署时修改默认管理员密码。
- 建议通过反向代理启用 HTTPS。
- 只处理你有权访问和转发的内容。

公开镜像只包含程序，不包含用户配置、Session、数据库或媒体。

## 常见问题

**保存 Bot Token 后机器人仍未运行**

查看日志：

```bash
docker logs -f --tail=200 tg-forward-hub
```

确认 Token、API ID 和 API Hash 正确，并确认服务器可以访问 Telegram API。

**验证码收不到**

确认手机号包含国家区号，并检查 Telegram 客户端和短信。验证码过期后需要重新点击发送。

**提示需要两步验证密码**

这是 Telegram 账号自身开启了两步验证。输入账号的两步验证密码，不是 Bot Token。

**用户客户端未连接**

重新完成手机号、验证码和两步验证。如果仍然失败，检查服务器网络和 Telegram 登录设备列表。

**提示 HTTP 503 或服务不可用**

先检查容器状态和日志，再确认 Telegram API 是否可达。容器内部 Web 端口为 `10000`，外部通过映射端口访问。

更多说明：

- [快速开始](QUICKSTART.md)
- [Docker 部署](DOCKER_SETUP.md)
- [使用示例](USAGE_EXAMPLES.md)
