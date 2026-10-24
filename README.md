# TG Forward Hub

[![Public GHCR image](https://img.shields.io/badge/GHCR-public-2496ED?logo=docker&logoColor=white)](https://github.com/wolf575/TgForwardHub/pkgs/container/tg-forward-hub)
[![GitHub](https://img.shields.io/badge/GitHub-wolf575%2FTgForwardHub-181717?logo=github)](https://github.com/wolf575/TgForwardHub)

TG Forward Hub 是一个把 **网页端批量转发** 和 **Telegram 自动监控/记录** 合并在一起的 Pyrogram 转发中心。

项目直接使用 Pyrogram 完成消息读取、缓存复制、隐藏来源转发和受限媒体下载重传，同时提供 Flask Web 管理页、Bot 私聊链接转发、监控任务、记录笔记、WebDAV 存储和磁力链接校准能力。

> 公共镜像：`ghcr.io/wolf575/tg-forward-hub:latest`
>
> 无需 GitHub 登录，无需 `read:packages` Token。

## 快速开始

推荐使用已经发布的公开 Docker 镜像。服务器需要安装 Docker，并能够访问 Telegram API。

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

打开 `http://服务器IP:10001`，使用默认账号 `admin` / `admin` 登录，然后：

1. 立即在「设置 → 账号与密码」修改管理员密码。
2. 填写 Bot Token、API ID 和 API Hash。
3. 填写 Telegram 手机号，完成验证码和两步验证，生成 Session String。
4. 等待「Telegram Bot」和「用户客户端」状态变为已连接。

配置保存在宿主机的 `/docker-data/tfh/data`，重建容器不会丢失。项目不需要 `.env`，也不要添加 `--env-file .env`。

更完整的部署说明见 [Docker 部署指南](docs/guides/DOCKER_SETUP.md)。

## 功能特性

### 网页端批量转发

- 支持数字 ID、`@username` 和可解析的频道/群组引用。
- 支持按消息 ID 范围或日期范围选择消息。
- 支持正序和逆序处理。
- 支持排除关键词、排除正则、删除关键词和删除正则。
- 支持媒体组整组处理，避免相册只发出第一项。
- 支持实时进度、成功/失败/跳过统计、任务取消和命令历史。
- 历史任务保存在 `data/history.db`，刷新页面或重启服务后仍可查看。

### 三种批量转发模式

| 模式 | 行为 | 适用场景 |
| --- | --- | --- |
| `clone` | 隐藏来源。优先使用 `messages.ForwardMessages(drop_author=True)`，失败后尝试缓存复制和下载重传 | 默认模式，希望目标频道看不到原来源 |
| `direct` | 保留来源。使用 `forward_messages` | 需要显示“Forwarded from” |
| `cache` | 缓存发送。使用 `copy_message` / `copy_media_group`，受限时可配置 Bot 中转缓冲会话 | 希望复用 Telegram 缓存，减少下载和上传 |

网页批量转发以用户客户端为主。只有 `cache` 模式且填写了「中转缓冲会话」时，受限来源才可能使用 Bot 中转：`来源 → 缓冲会话 → 目标`。

### Bot 私聊链接转发

直接给 Bot 发送 Telegram 消息链接即可取回内容。

```text
https://t.me/channel_name/123
https://t.me/c/1234567890/456
https://t.me/b/example_bot/789
```

支持以下区间写法：

```text
https://t.me/channel_name/100-120
https://t.me/channel_name/100 120
https://t.me/channel_name/100-https://t.me/channel_name/120
https://t.me/channel_name/100 https://t.me/channel_name/120
```

公开内容通常可以由 Bot 直接处理。私有频道、Bot 聊天或受限内容的回退路径需要先配置 Session String。

### 实时监控与自动转发

- 监控频道、群组、私聊和 `me`（个人收藏夹）。
- 一个来源可以配置多个目标。
- 支持完整转发和内容提取。
- 支持关键词白名单/黑名单、正则白名单/黑名单。
- 支持保留来源、自动补全磁力链接 `dn` 参数。
- 支持记录模式，把消息保存到网页笔记。
- 支持媒体组去重、FloodWait 自动等待、无效 Peer 跳过和失败重试。

### 记录、媒体与校准

- 笔记支持搜索、日期筛选、来源筛选、收藏、编辑和删除。
- 支持本地媒体存储和 WebDAV 远程存储。
- 支持磁力链接提取、文件名校准和观看站跳转。
- 支持自动校准队列、重试策略、并发数和后台调度。

### Web 管理与运行设置

- 统一管理批量转发、实时监控、记录笔记和系统设置。
- 内置 Bot Token、API ID、API Hash 和 Session String 配置向导。
- 显示网页端、Bot、用户客户端和监控源状态。
- 支持深色、浅色、青蓝、暖金四种主题。
- 支持修改时区、管理员账号、密码和批量转发完成通知。

## 首次配置

### 获取 Telegram 凭据

1. 在 Telegram 联系 `@BotFather`，使用 `/newbot` 创建 Bot，取得 Bot Token。
2. 登录 [my.telegram.org](https://my.telegram.org)，创建应用，取得 API ID 和 API Hash。
3. 准备用于用户客户端的 Telegram 手机号。

### 在网页中完成授权

1. 打开 Web 页面并使用 `admin` / `admin` 登录。
2. 进入「设置 → 初始配置 / Session String」。
3. 填写 Bot Token、API ID、API Hash。
4. 填写手机号，点击「发送验证码并生成 Session String」。
5. 输入 Telegram 验证码；如开启两步验证，再输入两步验证密码。
6. 保存后等待 Bot 和用户客户端自动启动。

Session String 等同于 Telegram 账号登录凭据。不要把 `data/config/config.json`、Session 文件或 WebDAV 密码提交到 Git、发给他人或放进公开 Issue。

## 使用教程

### 网页批量转发

1. 打开「批量转发」标签。
2. 填写来源 ID 和目标 ID。
3. 选择消息 ID 范围或日期范围。
4. 选择 `clone`、`direct` 或 `cache`。
5. 按需填写中转缓冲会话、排除规则和删除规则。
6. 点击「生成并执行」，在右侧查看进度和日志。

日期范围按本地日期选择，后端会转换为时间戳查询。逆序转发适合把旧内容按从新到旧的顺序镜像到新频道。

### 添加监控任务

1. 在 Bot 中发送 `/watch`，或点击「监控管理」。
2. 选择「添加监控」。
3. 输入来源：频道 ID、`@username`、转发消息，或输入 `me` 监控个人收藏夹。
4. 选择记录模式或转发模式。
5. 填写目标、过滤规则、提取规则和来源保留选项。
6. 保存后，新消息会进入后台队列处理。

### 查看记录笔记

在 Web 页面打开「笔记」，可以按内容、来源、日期和收藏状态筛选。记录模式保存的媒体会进入本地 `data/media`，启用 WebDAV 后可同步到远程存储。

更多示例见 [使用示例](docs/guides/USAGE_EXAMPLES.md)。

## 其他部署方式

### Docker Compose 从源码构建

```bash
git clone https://github.com/wolf575/TgForwardHub.git
cd TgForwardHub
docker compose up -d --build
docker compose logs -f
```

默认访问地址为 `http://服务器IP:10000`。Compose 只声明端口、数据目录和基础环境，不读取 Bot 凭据，也不需要 `.env`。

### 本地 Python 运行

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

打开 `http://127.0.0.1:10000`，在 Web 设置页完成 Telegram 配置。

## 数据目录

| 路径 | 内容 |
| --- | --- |
| `data/config/config.json` | Bot Token、API ID、API Hash、Session String |
| `data/config/watch_config.json` | 监控任务 |
| `data/config/app_settings.json` | 时区、通知等运行设置 |
| `data/config/webdav_config.json` | WebDAV 配置 |
| `data/notes.db` | 记录笔记和校准任务 |
| `data/history.db` | 批量转发历史 |
| `data/media/` | 记录模式媒体 |
| `downloads/` | 受限媒体下载重传时的临时文件 |

公开镜像只包含程序，不包含用户配置、Session、数据库或媒体。升级前建议备份 `data/` 和 `downloads/`。

## 更新与回滚

使用公开镜像更新时，保留原来的挂载目录即可：

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

工作流同时发布 `sha-<commit>` 标签，需要固定版本时可以使用对应的 SHA 标签。完整说明见 [更新与维护指南](docs/UPDATE_GUIDE.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [文档索引](docs/README.md) | 全部文档导航 |
| [快速开始](docs/guides/QUICKSTART.md) | 最短部署和首次配置流程 |
| [Docker 部署](docs/guides/DOCKER_SETUP.md) | 公共镜像、Compose、端口、持久化和更新 |
| [初始配置](docs/guides/SETUP_GUIDE.md) | Bot Token、API ID、Session String 和安全说明 |
| [使用示例](docs/guides/USAGE_EXAMPLES.md) | 批量转发、监控、记录和链接格式示例 |
| [功能说明](FEATURES.md) | 当前功能、配置字段和限制 |
| [更新与维护](docs/UPDATE_GUIDE.md) | 备份、升级、迁移和回滚 |

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/batch-forward` | 创建批量转发任务 |
| `GET` | `/api/batch-forward/<job_id>` | 查询任务进度 |
| `POST` | `/api/batch-forward/<job_id>/cancel` | 取消任务 |
| `GET/POST/DELETE` | `/api/history` | 查看、保存或清空命令历史 |
| `GET/POST` | `/api/watch-config` | 查看或保存监控规则 |
| `PUT/DELETE` | `/api/watch-config/<path>` | 更新或删除单条监控规则 |
| `GET` | `/api/notes` | 获取记录笔记 |
| `GET` | `/api/status` | 获取运行状态 |
| `GET` | `/api/sources` | 获取可用来源信息 |

## 技术栈与目录

- Python 3.9+
- Flask + Flask-Login
- Pyrogram + TgCrypto
- SQLite
- Docker / Docker Compose

```text
TgForwardHub/
├── app.py                 # Flask Web 与统一 API
├── batch_forward.py       # 批量转发任务服务
├── main.py                # Pyrogram Bot/User 客户端启动入口
├── config.py              # 配置读写
├── database.py            # SQLite 数据库
├── web_setup.py           # Telegram Session 网页配置向导
├── bot/                   # 自动转发、记录、校准、WebDAV
├── static/                # 前端资源
├── templates/             # 网页模板
├── docs/                  # 部署、配置和使用文档
├── Dockerfile
├── docker-compose.yml
├── docker-run.ps1         # Windows 一键 docker run
└── docker-run.sh          # Linux/macOS 一键 docker run
```

## 常见问题

**`docker pull` 提示 `unauthorized` 或仍要求登录**

先确认镜像名是 `ghcr.io/wolf575/tg-forward-hub:latest`。旧的 GHCR 登录凭据可能仍保存在本机，可以执行 `docker logout ghcr.io` 后再匿名拉取。

**页面能打开，但批量转发提示用户客户端未初始化**

在「设置」中完成 Telegram 用户账号授权并生成 Session String，然后重启容器或服务。

**实时监控没有触发**

检查监控源是否存在、用户账号是否已加入来源聊天、目标是否有发送权限，以及黑白名单是否把消息过滤掉。

**提示 FloodWait**

项目会自动等待 Telegram 限流时间并重试。不要同时启动多个使用同一个 Bot Token 的实例，否则可能出现重复处理。

**Apple Silicon 或其他 ARM 设备无法直接运行镜像**

当前公开镜像发布为 `linux/amd64`。ARM 设备可以在仓库目录执行 `docker build -t tg-forward-hub .` 本地构建。

**如何重置配置**

优先在 Web UI 中重新填写。如果必须彻底重置，停止容器后删除持久化目录中的 `data/config/config.json`，再启动容器重新初始化。

## 反馈

- Issues: [wolf575/TgForwardHub Issues](https://github.com/wolf575/TgForwardHub/issues)
- 仓库: [wolf575/TgForwardHub](https://github.com/wolf575/TgForwardHub)

使用本项目时请遵守 Telegram 服务条款和所在地区的法律法规，只处理你有权访问和转发的内容。
