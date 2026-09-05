# Docker 部署指南

本项目采用开箱即用的 Web UI 初始化方式。容器启动时只需要映射 Web 端口并
挂载两个持久化目录；Bot Token、API ID、API Hash、Session String 全部在网页中
填写并保存到持久化的 `/app/data/config/config.json`。

## 使用云端镜像

```bash
docker pull ghcr.io/wolf575/tg-forward-hub:latest

docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  ghcr.io/wolf575/tg-forward-hub:latest
```

容器内 Web 服务监听 `10000`，宿主机通过 `10001` 访问：
`http://服务器IP:10001`。

容器内置数据目录 `/app/data`、服务端口 `10000` 和默认时区
`Asia/Shanghai`。时区可以在 Web UI 设置页中修改，无需写入 Docker 命令。

## 使用 Docker Compose

```bash
cd TgForwardHub
docker compose up -d --build
docker compose logs -f
```

默认地址为 `http://服务器IP:10000`。Compose 只声明运行所需的基础环境，不要求创建 `.env`，也不读取 Bot 凭据。

## 初始化

1. 打开 Web 页面，使用默认账号 `admin` / `admin` 登录。
2. 进入「设置」，填写 Bot Token、API ID 和 API Hash。
3. 填写 Telegram 手机号，依次完成验证码和两步验证，生成 Session String。
4. 保存后后台会自动启动 Bot 和用户客户端。

配置保存在宿主机 `data` 目录，重建容器不会丢失。

## 常用命令

```bash
# 查看日志
docker logs -f tg-forward-hub

# 重启容器
docker restart tg-forward-hub

# 更新到最新镜像
docker pull ghcr.io/wolf575/tg-forward-hub:latest
docker rm -f tg-forward-hub
# 再执行上面的 docker run 命令
```

## 端口与持久化

- `-p 10001:10000`：宿主机 `10001` 映射到容器内 Web 端口 `10000`。
- 容器内端口固定为 `10000`，要换宿主机端口时只需修改 `-p` 左侧的端口，
  例如 `-p 10001:10000`；不需要传 `PORT` 环境变量。
- `data` 保存配置、会话、数据库和历史记录。
- `downloads` 保存受限媒体下载回退时的临时上传文件。

## 禁止使用 `.env`

不要创建 `.env`，也不要在 `docker run` 或 `docker compose` 命令中添加
`--env-file .env`。这个项目的云端容器不读取宿主机凭据文件；没有该文件时，
Docker 会直接报错：

```text
docker: --env-file: open .env: no such file or directory
```

需要重置配置时，在 Web UI 中重新填写，或删除持久化目录里的
`data/config/config.json` 后重启容器。
