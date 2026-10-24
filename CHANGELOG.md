# Changelog

## 2026-10-25

### Changed

- GHCR 镜像已改为公开，可直接匿名拉取 `ghcr.io/wolf575/tg-forward-hub:latest`
- README 改为以公开镜像作为推荐部署方式，移除私有包登录和 Token 步骤
- 重写功能说明、快速开始、Docker 部署、初始配置、使用示例和更新维护文档
- 补充三种批量转发模式、Bot 链接区间格式、监控/记录/WebDAV 能力和数据安全说明
- 新增文档索引 `docs/README.md`

## 2026-09-02

### Added

- 新增 Web 端 Bot 配置页 `/setup`
- 集成 Session String 两阶段验证码/两步验证状态机
- 自动写入持久化的 `data/config/config.json`
- 补齐 WebDAV、Viewer、Calibration、Calibration Queue 模板
- 补齐 `calibration_manager.py`、`calibration_scheduler.py`、`calibrate_helper.py`
- 新增中文部署与更新文档

### Changed

- Dockerfile 显式设置 `FLASK_APP=app.py`
- `docker-compose.yml` 增加 `FLASK_SECRET_KEY` 环境变量
