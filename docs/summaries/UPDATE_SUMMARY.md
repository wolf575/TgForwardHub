# 更新摘要

## 网页批量转发强制使用用户客户端

本次更新移除了网页端批量转发中的 Bot 身份分支。网页任务从获取消息、解析聊天、发送到失败回退全部只使用已登录的用户客户端。

### 复制模式顺序

`隐藏来源` 模式按以下顺序执行：

1. 用户客户端原生 `messages.ForwardMessages`，`drop_author=True`
2. 用户客户端 `copy_message` / `copy_media_group`
3. 用户客户端下载并重新上传

`保留来源` 模式继续使用用户客户端的 `forward_messages`，失败后按用户客户端路径回退。媒体组始终整组处理，避免只转发第一项。

## Docker 配置

Docker 部署不再创建 `.env`，也不使用 `--env-file .env`。凭据通过 Web UI 写入持久化的 `data/config/config.json`。

```bash
docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  ghcr.io/wolf575/tg-forward-hub:latest
```

`DATA_DIR`、`PORT` 和 `TZ` 均使用容器内置默认值，默认时区为
`Asia/Shanghai`，可在设置页修改。
