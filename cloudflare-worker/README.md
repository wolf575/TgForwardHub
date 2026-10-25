# Cloudflare Worker + Container Telegram Bot

这是 `TgForwardHub` 的独立 Cloudflare 版本。它不修改原 Python 项目，也不包含 WebDAV、监控、记录、校准、User Client 和受限内容下载重传。

快速部署见 [部署教程](DEPLOY.md)。首次部署建议先使用 `workers.dev` 域名，确认 Bot 正常后再绑定自定义域名。

## 功能

- 通过 Telegram Webhook 接收私聊命令和消息链接。
- 支持公开频道、Bot 已加入的私有频道、Bot 消息和消息 ID 区间。
- 单条相册链接会复制完整媒体组，包括带 `?single` 的分享链接。
- 支持数字 Telegram ID 或 `@username` 白名单。
- 提供 `/start`、`/help`、`/whoami`、`/allow`、`/deny`、`/list` 命令。
- 提供 Web 管理台，可管理白名单和批量转发完成通知。
- 支持 D1 或 KV 存储白名单，Container 使用 Pyrogram 读取相册和复制消息。

不包含：原 Python 项目的 WebDAV、监控、记录笔记、校准、User Client Session、受限内容下载重传和网页批量转发。

## Bot 命令

| 命令 | 说明 | 权限 |
| --- | --- | --- |
| `/start` | 查看快速入门和常用命令 | 所有人 |
| `/help` | 查看链接格式、使用说明和命令 | 所有人 |
| `/whoami` | 查看 Telegram ID、用户名、管理员和白名单状态 | 所有人 |
| `/allow <数字ID\|@username>` | 添加白名单 | 管理员 |
| `/deny <数字ID\|@username>` | 移出白名单 | 管理员 |
| `/list` | 查看全部白名单 | 管理员 |

管理员 ID 自动视为白名单，不能通过 `/deny` 移除。

## 快速部署

完整步骤见 [部署教程](DEPLOY.md)。最短流程如下：

1. 准备 Workers Paid、Docker、Bot Token、API ID、API Hash 和数字管理员 ID。
2. 登录 Cloudflare：`npx wrangler@4.152.0 login`
3. 创建 D1：`npx wrangler@4.152.0 d1 create tg-forward-hub-worker`
4. 把 D1 返回的 `database_id`、自己的 `ADMIN_ID` 和 `WEB_ADMIN_USER` 写入 `wrangler.jsonc`。
5. 设置 `BOT_TOKEN`、`API_ID`、`API_HASH`、`WEBHOOK_SECRET`、`WEB_ADMIN_PASSWORD`、`SESSION_SECRET` 六个 Secrets。
6. 执行 `npx wrangler@4.152.0 deploy`。
7. 访问 `https://<Worker域名>/install?secret=<WEBHOOK_SECRET>` 安装 Webhook。
8. 在 Telegram 向 Bot 发送 `/start`、`/help`、`/whoami`，确认部署成功。

## 结构

```text
cloudflare-worker/
├── _worker.js             # 唯一 Worker 入口：Webhook、白名单、命令、链接提交
├── wrangler.jsonc         # D1 + Container 配置
├── wrangler.kv.jsonc      # KV + Container 配置
├── container/
│   ├── Dockerfile
│   ├── app.py             # Pyrogram Bot 服务
│   └── requirements.txt
└── tests/
    └── worker.test.mjs
```

单条链接和区间链接都交给 Container 处理，因此可以识别并完整复制相册。Worker 只负责 Webhook、白名单、链接解析和把完整任务提交给 Container，不再拆分区间、维护转发队列或发送完成汇总。

Worker 始终通过固定的 `CONTAINER_INSTANCE_ID` 访问同一个逻辑 Container，避免多个 Telegram Bot 客户端并行运行。当前值是 `singleton-v7`。如果更新了 Container 镜像，需要把这个值递增为 `singleton-v8`、`singleton-v9`，强制 Durable Object 启动新镜像。

Container 实例类型为 `standard-1`（约 0.5 vCPU、4 GiB 内存），并使用 1 小时空闲保活。

### 为什么单相册链接需要 Container

Telegram Bot API 没有 `getMediaGroup` 或“读取任意历史消息”的接口。Bot API 只能：

- `copyMessage`：复制指定的单条消息；
- `copyMessages`：复制调用方明确提供的 1-100 个消息 ID，并保留这些消息的相册分组。

因此，如果用户只发一个相册锚点链接，Worker 无法从 Bot API 得知同组其他消息的 ID，也就无法可靠复制完整相册。Worker 端用“猜测附近 ID”会复制无关消息，不可接受。

Pyrogram 使用 MTProto，可以读取消息的 `media_group_id` 并调用 `get_media_group`，而且可以按 `@username` 直接读取这类典藏用户名频道。纯 Worker 若要达到同样效果，必须改用 GramJS/Telethon 等 MTProto 客户端，引入 API ID/hash、Durable Object 会话、长连接/重连、DC 迁移和运行时兼容问题，已经不是简单的单文件 Bot API Worker。

## 前置条件

- Cloudflare Workers Paid
- 本机 Docker（Wrangler 构建 Container 需要）
- Wrangler 4.136.0 或更新版本；本文命令使用 `4.152.0`
- 一个 Telegram Bot Token
- Telegram API ID 和 API Hash
- 一个数字 Telegram 管理员 ID
- D1 或 KV 二选一

`API_ID` 和 `API_HASH` 只有 Container 需要。Worker 本身调用 Bot API 只需要 `BOT_TOKEN`。

## 配置方式

### 方式一：Worker Secrets / Vars

推荐使用 Cloudflare Secrets，不要把 Token 写进仓库：

```bash
npx wrangler@4.152.0 secret put BOT_TOKEN
npx wrangler@4.152.0 secret put API_ID
npx wrangler@4.152.0 secret put API_HASH
npx wrangler@4.152.0 secret put WEBHOOK_SECRET
npx wrangler@4.152.0 secret put WEB_ADMIN_PASSWORD
npx wrangler@4.152.0 secret put SESSION_SECRET
```

在 `wrangler.jsonc` 的 `vars` 中填写 `ADMIN_ID`（数字用户 ID）和 `WEB_ADMIN_USER`（管理台用户名）。

运行时优先级：环境变量/Secrets > `_worker.js` 顶部的 `CODE_CONFIG`。

### 方式二：直接写代码

编辑 `_worker.js` 顶部的：

```js
const CODE_CONFIG = Object.freeze({
  BOT_TOKEN: "",
  ADMIN_ID: "",
  API_ID: "",
  API_HASH: "",
  WEBHOOK_SECRET: "",
  WEB_ADMIN_USER: "",
  WEB_ADMIN_PASSWORD: "",
  SESSION_SECRET: "",
  STORAGE_BACKEND: "auto",
  MAX_RANGE_MESSAGES: 10000,
  CONTAINER_PORT: 8080,
  CONTAINER_INACTIVITY_MS: 60 * 60 * 1000,
  CONTAINER_INSTANCE_ID: "singleton-v7",
});
```

即使直接写入代码，仍然需要绑定 D1/KV 和 Container。

## D1 部署

创建数据库：

```bash
npx wrangler@4.152.0 d1 create tg-forward-hub-worker
```

把返回的 `database_id` 填入 `wrangler.jsonc` 的 `d1_databases[0].database_id`。

设置密钥：

```bash
npx wrangler@4.152.0 secret put BOT_TOKEN
npx wrangler@4.152.0 secret put API_ID
npx wrangler@4.152.0 secret put API_HASH
npx wrangler@4.152.0 secret put WEBHOOK_SECRET
npx wrangler@4.152.0 secret put WEB_ADMIN_PASSWORD
npx wrangler@4.152.0 secret put SESSION_SECRET
```

修改 `wrangler.jsonc` 中的 `ADMIN_ID` 和 `WEB_ADMIN_USER`，然后部署：

```bash
npx wrangler@4.152.0 deploy
```

Worker 第一次处理请求时会自动创建 D1 表。

## KV 部署

创建命名空间：

```bash
npx wrangler@4.152.0 kv namespace create WHITELIST_KV
```

把返回的 `id` 填入 `wrangler.kv.jsonc`，设置同样的 Secrets 和 `ADMIN_ID`，然后使用 KV 配置部署：

```bash
npx wrangler@4.152.0 deploy -c wrangler.kv.jsonc
```

KV 只用于白名单和通知设置；大批量转发任务由 Container 内部队列处理。

## 设置 Telegram Webhook

推荐部署完成后访问：

```text
https://<你的-worker-域名>/install?secret=<WEBHOOK_SECRET>
```

这会自动调用 `setWebhook`，并只接收 `message` 和 `callback_query` 更新。

也可以手动调用：

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -d "url=https://<你的-worker-域名>/webhook" \
  -d "secret_token=<WEBHOOK_SECRET>" \
  -d 'allowed_updates=["message","callback_query"]'
```

## Web 白名单管理台

部署后访问：

```text
https://<你的-worker-域名>/admin
```

使用 `WEB_ADMIN_USER` 和 `WEB_ADMIN_PASSWORD` 登录。`SESSION_SECRET` 可选；未设置时会从管理员密码派生会话密钥，因此修改密码会让旧会话失效。

管理台支持：

- 查询白名单数字 ID 或用户名；
- 添加数字 ID 或 `@username`；
- 删除白名单记录；
- 开关 Bot 的批量转发完成通知；
- 查看当前存储后端和 Container 绑定状态。

管理台使用 HttpOnly、SameSite=Strict 会话 Cookie，并对写操作校验 CSRF Token。建议在生产环境再叠加 Cloudflare Access，限制 `/admin*` 的公网访问。

## 链接使用

白名单用户直接发送消息链接：

```text
https://t.me/username/123
https://t.me/username/123?single
https://t.me/c/123456789/123
https://t.me/b/botname/123
https://t.me/username/100-120
https://t.me/username/100 120
https://t.me/username/100 https://t.me/username/120
```

`?single` 不会改变相册复制行为，也不会取消后面的区间终点。

## 行为说明

- 单条链接：Worker 解析后提交给 Container，由 Pyrogram 复制；如果消息属于相册，会复制完整相册。
- 区间链接：Worker 把完整区间提交给 Container，由 Container 内部按 100 条分块并逐条复制；消息间等待 0.2 秒。
- `?single` 是 Telegram 分享链接的查询参数，不影响相册展开或区间终点。例如单条 `55260?single` 会复制 55260 所在完整相册，`55260?single ... 55268` 仍会处理 55260-55268。
- Container 默认保持 1 小时热实例，减少频繁冷启动；这会产生相应的 Container 运行时长费用。
- 暖 Container 单条转发通常在数秒内完成；Container 冷启动和 Pyrogram 重新连接 Telegram 时可能达到 20 秒以上。
- Telegram 429/FloodWait：任务进入 `retrying`，等待 `retry_after` 后重试。
- 同一用户 30 秒内重复发送完全相同的链接会被忽略，避免 Webhook 重试或连续点击造成重复内容。
- Container 接受任务后立即返回 202；任务队列保存在 Container 内存中，Container 重启会丢失尚未完成的任务。
- 汇总消息包含成功、失败、跳过和失败消息 ID。

## 限制

- 只支持 Bot 本身能访问的聊天；Bot 未加入的私有频道无法复制。
- 不支持 User Client、用户账号 Session、受限内容下载重传和中转缓冲会话。
- 用户名可能变更，也可能被其他账号重新注册；系统会优先把 `@username` 解析为数字 ID，但解析失败时仍会保存用户名别名。
- Container 会按 Pyrogram 的相册逻辑处理媒体组；跨分块的相册会通过内部 `next_id` 跳过已复制成员，避免重复。
- Container 需要 API ID 和 API Hash，且需要 Workers Paid 和 Docker。
- 原 Python Web UI、SQLite、WebDAV、监控和校准功能不包含在此目录。

`_worker.js` 是唯一 Worker 源码文件，可以单独复制到 Dashboard 的模块 Worker 编辑器中；但完整 Container 部署仍需要 `wrangler` 和本目录的 Container 配置。

## 本地检查

Worker 纯逻辑测试：

```bash
node --test tests/worker.test.mjs
```

Python 语法检查：

```bash
python -m py_compile container/app.py
```

Container 逻辑测试：

```bash
cd container
python -m unittest test_app.py -v
```

Container 构建：

```bash
docker build -t tg-forward-hub-worker-container ./container
```

本地 Wrangler：

```bash
npx wrangler@4.152.0 dev
```

本地开发需要 Docker 运行，并按 Cloudflare 要求配置本地 D1/KV 和 Container。
