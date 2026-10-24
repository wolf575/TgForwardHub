# 更新与维护指南

## 更新前备份

公开镜像部署通常使用以下目录：

```text
/docker-data/tfh/data
/docker-data/tfh/downloads
```

备份：

```bash
tar -czf tg-forward-hub-backup-$(date +%Y%m%d).tar.gz \
  /docker-data/tfh/data \
  /docker-data/tfh/downloads
```

备份文件中包含 Telegram Session、Bot Token、监控规则、笔记和媒体，必须妥善保管。

## 更新公开镜像

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

`docker rm -f` 只删除容器，不删除宿主机挂载目录。不要删除 `data` 和 `downloads`。

## 固定版本

GitHub Actions 会同时发布：

```text
ghcr.io/wolf575/tg-forward-hub:latest
ghcr.io/wolf575/tg-forward-hub:sha-<commit>
```

需要固定版本时，把启动命令中的 `latest` 替换为对应的 SHA 标签。

## Docker Compose 从源码更新

```bash
cd TgForwardHub
docker compose down
git pull
docker compose up -d --build
docker compose logs -f --tail=200
```

如果使用独立的公开镜像 Compose 文件：

```bash
docker compose pull
docker compose up -d
docker compose logs -f --tail=200
```

## 只重启

```bash
docker restart tg-forward-hub
```

修改 Bot Token、API 信息或 Session String 后，建议重启一次容器。

## 查看日志

```bash
docker logs -f --tail=200 tg-forward-hub
```

应用日志也会写入持久化目录：

```text
data/logs/bot.log
```

仓库的 Docker Compose 配置启用了 json-file 日志轮转，单个文件上限约 10 MB，保留 5 个文件。

## 修改 Telegram 配置

1. 打开 Web UI「设置」。
2. 修改 Bot Token、API ID、API Hash 或重新生成 Session String。
3. 保存配置。
4. 重启容器。

不需要编辑 `.env`，也不要在 Docker 命令中加入 `--env-file .env`。

## 数据迁移

1. 停止旧服务器容器。
2. 备份旧服务器的 `data` 和 `downloads`。
3. 把目录复制到新服务器。
4. 在新服务器使用相同的挂载路径启动容器。
5. 打开 Web UI 检查 Bot、用户客户端和监控任务状态。

迁移后不要重新生成 Session String，除非旧 Session 已失效。

## 回滚

### 回滚镜像

如果保留了旧 SHA 标签，直接使用旧标签启动：

```bash
docker pull ghcr.io/wolf575/tg-forward-hub:sha-<old-commit>
```

### 回滚源码部署

```bash
git log --oneline
git switch --detach <上一个可用提交>
docker compose up -d --build
```

回滚前先备份当前数据。不同版本如果包含数据库迁移，直接回退程序可能需要同时恢复旧数据库。

## 清理空间

安全清理未使用的镜像和构建缓存：

```bash
docker image prune
docker builder prune
```

不要在没有确认的情况下执行 `docker system prune -a`。它会删除所有未使用镜像，并可能影响服务器上的其他项目。

## 单实例检查

同一个 Bot Token 只能有一个正在运行的实例：

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

如果发现多个容器或本地进程使用同一个 Token，先停止多余实例，避免重复处理旧消息。

## 常见问题

**更新后配置为空**

新容器没有挂载原来的 `data` 目录。停止容器并使用正确路径重新启动。

**更新后镜像仍要求登录**

执行：

```bash
docker logout ghcr.io
docker pull ghcr.io/wolf575/tg-forward-hub:latest
```

**更新后用户客户端未连接**

检查日志和 Telegram 登录设备。必要时在 Web UI 重新生成 Session String。

**ARM 设备拉取后无法运行**

当前公开镜像为 `linux/amd64`。在 ARM 设备上从源码构建本地镜像。

## 相关文档

- [快速开始](guides/QUICKSTART.md)
- [Docker 部署](guides/DOCKER_SETUP.md)
- [初始配置](guides/SETUP_GUIDE.md)
- [使用示例](guides/USAGE_EXAMPLES.md)
