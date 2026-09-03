# Changelog

## 2026-09-02

### Added

- 新增 Web 端 Bot 配置页 `/setup`
- 集成 Session String 两阶段验证码/两步验证状态机
- 自动写入 `.env` 和 `data/config/config.json`
- 补齐 WebDAV、Viewer、Calibration、Calibration Queue 模板
- 补齐 `calibration_manager.py`、`calibration_scheduler.py`、`calibrate_helper.py`
- 新增中文部署与更新文档

### Changed

- Dockerfile 显式设置 `FLASK_APP=app.py`
- `docker-compose.yml` 增加 `FLASK_SECRET_KEY` 环境变量

