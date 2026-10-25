# Changelog

## 2026-10-25

### Changed

- GHCR 镜像已改为公开，可直接匿名拉取 `ghcr.io/wolf575/tg-forward-hub:latest`
- README 改为以公开镜像作为推荐部署方式，移除私有包登录和 Token 步骤
- 重写功能说明、快速开始、Docker 部署、初始配置、使用示例和更新维护文档
- 补充三种批量转发模式、Bot 链接区间格式、监控/记录/WebDAV 能力和数据安全说明
- 新增文档索引 `docs/README.md`

### Fixed

- 批量转发命令历史按任务名更新，同名任务不再重复堆积，并清理旧重复记录
- 时间范围任务恢复时自动续期：原结束日期作为新开始日期，当前时间作为新结束日期
- 日期范围结束日期改为包含当天，结束日期为今天时截到当前时刻
- 禁止启动同名运行中任务，禁止取消已完成任务
- 修复历史数据库连接未关闭导致的文件锁和资源泄漏

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
