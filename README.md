# TG Forward Hub

TG Forward Hub 是一个把「网页端批量转发」和「Telegram 自动监控/记录」合并在一起的 Pyrogram 转发中心。项目不再调用外部 `tdl` CLI，而是直接使用 Pyrogram 完成 Telegram 消息获取、转发和复制；同时保留命令构建器的网页表单、任务范围和命令历史，以及 Save-Restricted-Bot 的实时监控、记录模式、WebDAV 存储和校准能力。

## 功能特性

### 批量转发

- 支持来源聊天和目标聊天，可使用数字 ID 或可解析的 `@username` / 邀请链接。
- 支持按消息 ID 范围转发，也支持按开始日期、结束日期转发。
- 支持正序和倒序处理，适合把旧频道内容镜像到新频道。
- 支持排除关键词：命中关键词的消息直接跳过。
- 支持尾部文案清理：删除消息末尾常见的“加入群组 / 免责声明 / 广告”段落。
- 支持两种转发方式：
  - `保留来源`：使用 `forward_messages` 保留原消息的来源签名。
  - `隐藏来源`：使用 `copy_message` 复制消息，不显示原来源。
- 任务实时展示进度、成功、失败和跳过数量，可取消任务。
- 命令历史持久化到 `data/history.db`，刷新页面后仍可查看历史任务。

### 实时监控与自动转发

- 为多个 Telegram 用户账号分别配置监控源和目标聊天。
- 支持关键词白名单、黑名单、正则白名单、正则黑名单。
- 支持完整转发、内容提取、记录模式等处理方式。
- 媒体组去重、FloodWait 自动等待与重试、无效 Peer 自动跳过。
- 支持监控配置的 Web API 与页面管理。

### 记录与媒体管理

- 笔记记录模式，可收藏、编辑、删除和管理 Telegram 消息内容。
- 支持磁力链接提取、文件名校准和观看站跳转。
- 支持本地媒体存储和 WebDAV 远程存储。
- 支持自动校准任务队列和后台调度。

### 网页端

- 统一 Flask 页面：批量转发、实时监控、记录笔记、系统设置。
- 默认管理员账号：`admin` / `admin`，首次登录后建议在管理页面修改密码。
- 内置 Telegram 配置向导，可填写 Bot Token、API ID、API Hash，并通过手机号验证码和两步验证生成 String Session。

## 技术栈

- Python 3.9+
- Flask + Flask-Login
- Pyrogram + TgCrypto
- SQLite
- Docker / Docker Compose

## 目录结构

```text
TgForwardHub/
├── app.py                 # Flask Web 与统一 API
├── batch_forward.py       # 批量转发任务服务
├── main.py                # Pyrogram Bot/User 客户端启动入口
├── config.py              # 配置读写
├── database.py            # SQLite 数据库
├── web_setup.py           # Telegram Session 网页配置向导
├── bot/                   # 自动转发、记录、校准、WebDAV
├── static/                # 合并后的前端资源
├── templates/             # 网页模板
├── Dockerfile
├── docker-compose.yml
├── docker-run.ps1         # Windows 一键 docker run
├── docker-run.sh          # Linux/macOS 一键 docker run
└── .env.example
```

## 准备 Telegram 凭据

运行项目前需要准备以下信息：

| 变量 | 说明 | 必填 |
| --- | --- | --- |
| `TOKEN` | Bot Token，从 `@BotFather` 获取 | 是 |
| `ID` | Telegram API ID | 是 |
| `HASH` | Telegram API Hash | 是 |
| `STRING` | 用户账号 Session String | 自动转发、批量转发的用户客户端需要 |
| `FLASK_SECRET_KEY` | Flask Session 加密密钥，生产环境必须修改 | 建议 |
| `DATA_DIR` | 容器内数据目录，默认 `/app/data` | Docker 中保持默认 |
| `PORT` | Web 服务监听端口，默认 `10000` | 可选 |
| `TZ` | 时区，默认 `Asia/Shanghai` | 可选 |

> 也可以通过网页端「设置 → 初始配置」生成 Session String，不必手动复制长字符串。

## 本地运行

```bash
cd TgForwardHub

python -m venv .venv

# Windows PowerShell
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

浏览器打开 `http://127.0.0.1:10000`。

本地运行时可以先登录 Web UI，再进入「设置 → 初始配置」保存 Bot 凭据并生成 Session String。后台 Bot 线程会每 10 秒检查一次配置，配置完成后自动启动。

## Docker Compose 部署

```bash
cd TgForwardHub

# 复制配置模板并填写真实凭据
cp .env.example .env

docker compose up -d --build
docker compose logs -f
```

打开 `http://服务器IP:10000`。

`.env` 示例：

```dotenv
TOKEN=123456789:AA...
ID=123456
HASH=abc...
STRING=1...
FLASK_SECRET_KEY=replace-with-a-long-random-string
```

默认账号为 `admin` / `admin`。

## Docker Run 部署

项目已经准备了 `docker run` 所需的条件：镜像暴露 `10000` 端口、声明 `/app/data` 和 `/app/downloads` 数据卷，并内置健康检查。

### 使用云端镜像

如果你不想在服务器上重新构建，可以直接使用 GitHub Container Registry 上的镜像：

```bash
docker pull ghcr.io/wolf575/tg-forward-hub:latest
```

> GHCR 包默认是私有的。如果不想在服务器上登录，可以在 GitHub Packages 页面把 `tg-forward-hub` 的可见性改为 Public；否则先执行 `docker login ghcr.io -u wolf575`，再粘贴一个具有 `read:packages` 权限的 token。

在服务器上运行，并把宿主机端口改成 `10001`：

```bash
docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  --env-file .env \
  -e DATA_DIR=/app/data \
  -e PORT=10000 \
  -e TZ=Asia/Shanghai \
  ghcr.io/wolf575/tg-forward-hub:latest
```

容器内 Web 服务继续监听 `10000`，宿主机通过 `10001` 访问。打开 `http://服务器IP:10001` 即可。

如果你想同时把容器内部端口也改成 `10001`，端口映射和 `PORT` 环境变量要保持一致：

```bash
-p 10001:10001 -e PORT=10001
```

不要使用 `-p 10001:10000` 搭配 `-e PORT=10001`，这会让宿主机映射到容器 `10000`，但 Flask 实际监听在 `10001`，导致页面无法访问。

### Windows PowerShell

```powershell
cd TgForwardHub

Copy-Item .env.example .env -Force
# 编辑 .env，填入 TOKEN / ID / HASH / STRING

.\docker-run.ps1
```

### Linux / macOS

```bash
cd TgForwardHub

cp .env.example .env
# 编辑 .env，填入 TOKEN / ID / HASH / STRING

chmod +x docker-run.sh
./docker-run.sh
```

### 手动执行 docker run

```bash
docker build -t tg-forward-hub .

docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10000:10000 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/downloads:/app/downloads" \
  --env-file .env \
  -e DATA_DIR=/app/data \
  -e PORT=10000 \
  -e TZ=Asia/Shanghai \
  tg-forward-hub
```

Windows PowerShell 手动执行时，将 `$(pwd)` 替换为实际绝对路径：

```powershell
docker run -d `
  --name tg-forward-hub `
  --restart unless-stopped `
  -p 10000:10000 `
  -v "C:\path\to\TgForwardHub\data:/app/data" `
  -v "C:\path\to\TgForwardHub\downloads:/app/downloads" `
  --env-file .env `
  -e DATA_DIR=/app/data `
  -e PORT=10000 `
  -e TZ=Asia/Shanghai `
  tg-forward-hub
```

## 初始配置

1. 打开 `http://服务器IP:10000`。
2. 使用 `admin` / `admin` 登录。
3. 进入「设置」标签，点击「初始配置」。
4. 填写 Bot Token、API ID、API Hash。
5. 点击「生成 Session」并输入 Telegram 手机号。
6. 输入 Telegram 收到的验证码；如账号开启两步验证，再输入两步验证密码。
7. 配置完成后，后台 Bot 和用户客户端会自动启动。

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/batch-forward` | 创建批量转发任务 |
| `GET` | `/api/batch-forward/<job_id>` | 查询任务进度 |
| `POST` | `/api/batch-forward/<job_id>/cancel` | 取消任务 |
| `GET/POST/DELETE` | `/api/history` | 查看、保存或清空命令历史 |
| `GET/POST` | `/api/watch-config` | 查看或保存实时监控规则 |
| `PUT/DELETE` | `/api/watch-config/<path>` | 更新或删除单条监控规则 |
| `GET` | `/api/notes` | 获取记录笔记 |
| `GET` | `/api/status` | 获取运行状态 |
| `GET` | `/api/sources` | 获取可用来源信息 |

## 数据与安全

- 所有敏感数据（`.env`、`config.json`、Session 文件）均已加入 `.gitignore` 和 `.dockerignore`，不会提交到 Git，也不会进入 Docker 镜像。
- 持久化数据保存在宿主机 `data` 目录，下载媒体保存在 `downloads` 目录。
- 公网部署时务必修改 `FLASK_SECRET_KEY` 和管理员密码。
- Telegram 登录凭据和 Session String 具有账号控制权限，请勿泄露。

## 常见问题

- **页面能打开，但批量转发提示用户客户端未初始化**：先在「设置」中完成 Telegram 用户账号授权并生成 String Session，然后重启容器或服务。
- **实时监控没有触发**：检查监控源是否已经加入配置、目标账号是否有权访问源聊天，以及黑白名单是否把消息过滤掉了。
- **Docker 镜像构建慢**：首次构建需要安装依赖；第二次构建会使用缓存。
- **提示 FloodWait**：项目会自动等待 Telegram 限流时间并重试，不必手动处理。
