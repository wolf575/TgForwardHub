# TG Forward Hub 文档

项目主文档：[README](../README.md)

## 开始使用

| 文档 | 适合场景 |
| --- | --- |
| [快速开始](guides/QUICKSTART.md) | 想用最短步骤启动公开镜像 |
| [Docker 部署](guides/DOCKER_SETUP.md) | 需要端口、持久化、Compose、更新和 ARM 构建说明 |
| [初始配置](guides/SETUP_GUIDE.md) | 第一次配置 Bot Token、API ID 和 Session String |
| [使用示例](guides/USAGE_EXAMPLES.md) | 批量转发、监控、记录和链接格式示例 |

## 功能与维护

| 文档 | 内容 |
| --- | --- |
| [功能说明](../FEATURES.md) | 当前功能、转发模式、监控配置和限制 |
| [更新与维护](UPDATE_GUIDE.md) | 备份、升级、迁移和回滚 |

## 公开镜像

```text
ghcr.io/wolf575/tg-forward-hub:latest
```

镜像已经公开，可以匿名拉取，不需要 GitHub Token，也不需要执行 `docker login ghcr.io`。

当前镜像发布平台为 `linux/amd64`。ARM 设备可以从源码构建。

## 数据安全

- `data/` 保存配置、Session、数据库和媒体。
- `downloads/` 保存受限媒体回退下载文件。
- 公开镜像不包含用户配置或 Session。
- 升级前请备份 `data/` 和 `downloads/`。
- 不要提交、分享或公开发送 `data/config/config.json`、Session 文件和 WebDAV 密码。
