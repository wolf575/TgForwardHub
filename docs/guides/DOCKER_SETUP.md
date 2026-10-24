# Docker 部署指南

本项目提供公开的 GitHub Container Registry 镜像：

```text
ghcr.io/wolf575/tg-forward-hub:latest
```

镜像可以匿名拉取，不需要 GitHub Token，也不需要执行 `docker login ghcr.io`。

## 推荐方式：公开镜像

### 1. 创建持久化目录

```bash
mkdir -p /docker-data/tfh/data /docker-data/tfh/downloads
```

### 2. 拉取镜像

```bash
docker pull ghcr.io/wolf575/tg-forward-hub:latest
```

### 3. 启动容器

```bash
docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  ghcr.io/wolf575/tg-forward-hub:latest
```

打开 `http://服务器IP:10001`，使用默认账号 `admin` / `admin` 登录并完成 Web UI 初始化。

### 4. 查看日志

```bash
docker logs -f --tail=200 tg-forward-hub
```

## 端口

容器内 Web 服务固定监听 `10000`。`-p 10001:10000` 表示：

```text
宿主机 10001 → 容器 10000
```

如果宿主机端口被占用，只需要修改左侧端口：

```bash
-p 10002:10000
```

不需要传入 `PORT` 环境变量。

## 数据持久化

| 宿主机目录 | 容器目录 | 内容 |
| --- | --- | --- |
| `/docker-data/tfh/data` | `/app/data` | 配置、Session、数据库、日志、记录媒体 |
| `/docker-data/tfh/downloads` | `/app/downloads` | 受限媒体下载重传文件 |

重建或升级容器时必须继续挂载原来的目录，否则会丢失 Telegram 配置、监控任务和历史记录。

## 首次配置

1. 打开 Web 页面并使用 `admin` / `admin` 登录。
2. 修改管理员密码。
3. 在「设置」中填写 Bot Token、API ID、API Hash。
4. 填写手机号，完成验证码和两步验证。
5. 等待 Bot 和用户客户端连接成功。

配置保存在 `/app/data/config/config.json`。公开镜像不包含任何用户凭据。

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

升级前建议备份：

```bash
tar -czf tg-forward-hub-backup-$(date +%Y%m%d).tar.gz \
  /docker-data/tfh/data \
  /docker-data/tfh/downloads
```

## Docker Compose 从源码构建

仓库中的 `docker-compose.yml` 默认从当前目录构建：

```bash
git clone https://github.com/wolf575/TgForwardHub.git
cd TgForwardHub
docker compose up -d --build
docker compose logs -f
```

默认地址为 `http://服务器IP:10000`。数据目录为当前项目下的 `data/` 和 `downloads/`。

更新源码后：

```bash
docker compose down
git pull
docker compose up -d --build
docker compose logs -f
```

## Docker Compose 使用公开镜像

如果不想在服务器上保留源码，可以新建一个独立目录并写入 `compose.yml`：

```yaml
services:
  tg-forward-hub:
    image: ghcr.io/wolf575/tg-forward-hub:latest
    container_name: tg-forward-hub
    restart: unless-stopped
    ports:
      - "10001:10000"
    volumes:
      - ./data:/app/data
      - ./downloads:/app/downloads
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

启动：

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

## 一键脚本

仓库提供：

- Windows PowerShell：`docker-run.ps1`
- Linux / macOS：`docker-run.sh`

Linux / macOS：

```bash
chmod +x docker-run.sh
./docker-run.sh
```

Windows PowerShell：

```powershell
.\docker-run.ps1
```

脚本默认拉取 `ghcr.io/wolf575/tg-forward-hub:latest`，删除同名旧容器，再使用本地 `data` 和 `downloads` 启动新容器。

## 镜像平台

当前公开镜像发布为 `linux/amd64`。常见 x86_64 服务器可以直接使用。

ARM 设备可以本地构建：

```bash
git clone https://github.com/wolf575/TgForwardHub.git
cd TgForwardHub
docker build -t tg-forward-hub .
```

然后使用本地镜像名 `tg-forward-hub` 启动。

## 不要使用 `.env`

项目通过 Web UI 保存 Telegram 凭据，不需要 `.env`。

不要执行：

```bash
docker run --env-file .env ...
```

没有该文件时 Docker 会直接报错：

```text
docker: --env-file: open .env: no such file or directory
```

## 单实例要求

不要同时启动多个使用同一个 Bot Token 的容器或本地进程。多个实例可能同时处理相同更新，造成重复转发。更新时先停止旧容器，再启动新容器。

## 常见问题

**仍然提示 GHCR 需要登录**

确认镜像名没有拼错，并清理本机旧凭据：

```bash
docker logout ghcr.io
docker pull ghcr.io/wolf575/tg-forward-hub:latest
```

**页面打不开**

检查容器状态和端口：

```bash
docker ps
docker logs --tail=200 tg-forward-hub
```

**容器启动后配置丢失**

确认两个 `-v` 挂载目录与旧容器一致。删除容器不会删除宿主机目录，但挂载到新目录会得到一套空配置。

**Bot 已连接但批量转发失败**

批量转发需要用户客户端 Session String。在「设置」中确认用户客户端已连接，并确保该账号有权访问来源聊天。

更多说明：

- [快速开始](QUICKSTART.md)
- [初始配置](SETUP_GUIDE.md)
- [更新与维护](../UPDATE_GUIDE.md)
