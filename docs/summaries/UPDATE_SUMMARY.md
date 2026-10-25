# 更新摘要

## 网页批量转发模式

网页批量转发以用户客户端为主，支持三种模式：

- `clone`：隐藏来源，优先使用 `messages.ForwardMessages(drop_author=True)`，失败后回退到缓存复制和下载重传。
- `direct`：保留来源，使用 `forward_messages`。
- `cache`：缓存发送，使用 `copy_message` / `copy_media_group`；受限时可配置 Bot 中转缓冲会话。

`cache` 模式的 Bot 中转流程为：

```text
来源 → Bot 缓冲会话 → 用户客户端隐藏转发 → 目标
```

中转会话必须是 Bot 和用户客户端都能访问的频道或群组，并给 Bot 发送消息的权限。媒体组始终按整组处理。

## 批量任务历史

- 同名任务只保留一条历史记录，再次执行时覆盖更新。
- 运行中的同名任务不能重复启动。
- 时间范围任务点击历史后自动续期：原结束日期作为新开始日期，当前日期作为新结束日期。
- 日期范围结束日期包含当天；如果结束日期是今天，结束时间截到当前时刻。
- 已完成任务不能再次取消。

## Docker 配置

项目提供公开镜像：

```text
ghcr.io/wolf575/tg-forward-hub:latest
```

镜像可以匿名拉取，不需要 GitHub Token。Docker 部署不再创建 `.env`，也不使用 `--env-file .env`。凭据通过 Web UI 写入持久化的 `data/config/config.json`。

```bash
docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  ghcr.io/wolf575/tg-forward-hub:latest
```

`DATA_DIR`、`PORT` 和 `TZ` 使用容器内置默认值，默认时区为 `Asia/Shanghai`，可在设置页修改。
