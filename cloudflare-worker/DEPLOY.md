# Cloudflare Worker + Container 部署教程

本文使用 D1 存储白名单，步骤适用于 `cloudflare-worker` 分支。

## 1. 准备

- Cloudflare Workers Paid 计划。
- 本机安装 Node.js 和 Docker。
- Telegram Bot Token。
- Telegram API ID 和 API Hash。
- 自己的数字 Telegram 用户 ID。
- 如果要复制私有频道，先把 Bot 加入频道并授予读取消息权限。

## 2. 获取代码

```bash
git clone --branch cloudflare-worker https://github.com/wolf575/TgForwardHub.git
cd TgForwardHub/cloudflare-worker
```

已克隆仓库时：

```bash
git switch cloudflare-worker
git pull
cd cloudflare-worker
```

## 3. 登录 Cloudflare

```bash
npx wrangler@4.152.0 login
```

## 4. 创建 D1

```bash
npx wrangler@4.152.0 d1 create tg-forward-hub-worker
```

复制命令返回的 `database_id`。

## 5. 修改 `wrangler.jsonc`

至少修改以下三项：

```jsonc
"d1_databases": [
  {
    "binding": "DB",
    "database_name": "tg-forward-hub-worker",
    "database_id": "粘贴自己的 D1 database_id"
  }
],
"vars": {
  "ADMIN_ID": "自己的数字 Telegram ID",
  "WEB_ADMIN_USER": "admin"
}
```

首次部署建议删除 `routes` 整段，先使用 Wrangler 输出的 `workers.dev` 地址。需要自定义域名时，再填写自己的 `pattern` 和 `zone_name`。

## 6. 设置 Secrets

依次执行，命令会提示输入对应值：

```bash
npx wrangler@4.152.0 secret put BOT_TOKEN
npx wrangler@4.152.0 secret put API_ID
npx wrangler@4.152.0 secret put API_HASH
npx wrangler@4.152.0 secret put WEBHOOK_SECRET
npx wrangler@4.152.0 secret put WEB_ADMIN_PASSWORD
npx wrangler@4.152.0 secret put SESSION_SECRET
```

`WEBHOOK_SECRET` 和 `SESSION_SECRET` 请使用随机长字符串。不要把任何 Secret 提交到 GitHub。

## 7. 部署

```bash
npx wrangler@4.152.0 deploy
```

记下命令输出的 Worker 地址，例如：

```text
https://tg-forward-hub-worker.<account>.workers.dev
```

## 8. 安装 Telegram Webhook

浏览器访问：

```text
https://<Worker域名>/install?secret=<WEBHOOK_SECRET>
```

返回 `{"ok":true,...}` 表示安装成功。

## 9. 验证

1. 打开 `https://<Worker域名>/health`，确认返回 `"ok": true`。
2. 在 Telegram 向 Bot 发送 `/start`。
3. 发送 `/whoami`，确认管理员和白名单状态。
4. 发送 `/help`，确认链接格式和命令说明正常。
5. 用管理员发送 `/allow <数字ID>` 添加测试用户。
6. 用白名单用户发送一条 Telegram 消息链接。
7. 如果链接属于相册，确认完整媒体组都已复制。

## 可选：使用 KV

不使用 D1 时：

```bash
npx wrangler@4.152.0 kv namespace create WHITELIST_KV
```

把返回的 `id` 填入 `wrangler.kv.jsonc`，设置相同 Secrets 和 `ADMIN_ID`，然后部署：

```bash
npx wrangler@4.152.0 deploy -c wrangler.kv.jsonc
```

## 更新部署

```bash
git pull
npx wrangler@4.152.0 deploy
```

如果修改了 `container/` 内的代码、实例规格或保活配置，先把 `CONTAINER_INSTANCE_ID` 从 `singleton-v9` 递增到 `singleton-v10`，再部署，确保 Container 拉起新实例。

## 常见问题

- `/health` 不是 `ok`：按返回的 `issues` 检查 D1/KV、Secrets 和 Container 绑定。
- Bot 不回复：确认 `/install` 已成功执行，并检查 Telegram Webhook 状态。
- Container 启动失败：确认已开通 Workers Paid、Docker 正常运行、`API_ID` 和 `API_HASH` 正确。
- 私有频道无法复制：确认 Bot 已加入频道并有读取消息权限。
- 相册只出现第一项：确认部署的是 `cloudflare-worker` 分支最新版本，并检查 `CONTAINER_INSTANCE_ID` 是否已递增。
