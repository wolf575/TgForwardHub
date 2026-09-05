# 快速开始

## Docker 开箱即用

准备好 `docker` 后，直接启动云端镜像：

```bash
docker pull ghcr.io/wolf575/tg-forward-hub:latest

docker run -d \
  --name tg-forward-hub \
  --restart unless-stopped \
  -p 10001:10000 \
  -v /docker-data/tfh/data:/app/data \
  -v /docker-data/tfh/downloads:/app/downloads \
  -e DATA_DIR=/app/data \
  -e PORT=10000 \
  -e TZ=Asia/Shanghai \
  ghcr.io/wolf575/tg-forward-hub:latest
```

打开 `http://服务器IP:10001`，使用默认账号 `admin` / `admin` 登录，然后在「设置」中填写：

1. Bot Token
2. API ID 和 API Hash
3. Telegram 手机号，完成验证码和两步验证并生成 Session String

不需要创建 `.env`，也不要添加 `--env-file .env`。配置由 Web UI 写入宿主机持久化的 `data` 目录。

## 本地运行

```bash
cd TgForwardHub

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

浏览器打开 `http://127.0.0.1:10000`，同样在统一设置页完成配置。

## 查看日志

```bash
docker logs -f tg-forward-hub
```

## 常见问题

**为什么提示 `--env-file: open .env: no such file or directory`？**

Docker 命令中存在 `--env-file .env`。直接删除该参数即可，本项目的云端容器不依赖 `.env` 文件。

**需要修改 Telegram 凭据或 Session String？**

在 Web UI「设置」页直接修改并保存，或删除持久化目录中的 `data/config/config.json` 后重新初始化，不需要手工编辑 `.env`。
