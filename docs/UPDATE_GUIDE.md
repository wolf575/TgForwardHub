# 更新与维护指南

## 更新前备份

建议先备份配置和数据：

```bash
tar -czf save-restricted-bot-backup-$(date +%Y%m%d).tar.gz \
  data .env docker-compose.yml
```

Windows 可手动复制 `data`、`.env`、`docker-compose.yml` 到备份目录。

## 常规更新

```bash
cd Save-Restricted-Bot
docker compose down
git pull
docker compose build --no-cache
docker compose up -d
docker compose logs -f
```

## 仅重启

```bash
docker compose restart
```

## 查看日志

```bash
docker compose logs -f --tail=200
```

日志文件由 Docker json-file driver 轮转，单个文件上限约 10 MB，保留 5 个文件。

## 修改 Bot 凭据

1. 打开 Web 面板的 **Bot 配置**
2. 修改 Token、API ID、API Hash 或重新生成 Session String
3. 保存后重启容器

也可以手动编辑 `data/config/config.json` 或项目根目录 `.env`。

## 数据迁移

将旧服务器的 `data/`、`downloads/`、`.env` 复制到新服务器项目目录，然后：

```bash
docker compose up -d --build
```

## 清理

```bash
docker image prune -a
docker system prune -a
```

## 回滚

```bash
git log --oneline
git checkout <上一个可用提交>
docker compose build --no-cache
docker compose up -d
```

