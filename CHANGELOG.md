# Changelog

## 2026-11-08

### Fixed

- 修复富文本过滤前 `NFKC` 归一化改变用户可见符号的问题：`‼️`、`🔞` 等 emoji 正则现在按原始可见字符匹配；NFKC 视图仅作为全角字符兼容兜底
- 删除规则命中后优先使用原始可见字符清理结果，避免过滤文本被改写成普通 ASCII 标点后仍保留原广告内容
- 修复 Pyrofork 2.3.69 `copy_media_group` 构造 Layer 220 `messages.Messages` 时缺少 `topics`，导致媒体组已发送却被误判失败并下载重传的问题
- 精简批量发送路径：媒体组、单条媒体和文本统一为缓存复制/直接转发两条路径，移除重复的 raw `ForwardMessages` 隐藏转发实现
- 为批量任务增加同步桥接超时、卡住检测和 FloodWait 状态事件，任务不会再无限等待且无提示；FloodWait 会显示等待秒数并自动重试
- 移除单条媒体发送后的不可靠 caption 二次校验，避免偶发误报“发送后编辑回退”和额外编辑请求
- 时间范围任务改为边扫描边转发，每收集 100 条消息即可开始发送，不再等待完整扫描结束
- 客户端批量转发新增每分钟发送单元上限，默认 25，可在 Web UI 调整；达到上限时显示等待状态并自动继续
- 媒体组不再对所有非空 caption 做二次确认，仅在需要清空 caption 时执行定向编辑，减少额外请求和误报

## 2026-11-07

### Added

- 同一账户可在新浏览器或新设备通过活动任务列表接管运行中/暂停中的批量任务，也可切换到新任务模式
- 批量任务完成或失败后支持通过 `NOTIFY_CONFIG` 发送包含总数、已处理、成功、失败和跳过统计的通知
- 设置页新增通知渠道参数配置和测试通知按钮，支持直接管理 notify.py 的 Telegram、Bark、Webhook、SMTP 等渠道
- 通知设置拆分为“机器人私聊状态通知”和“客户端批量转发外部通知”；外部通知按 notify.py 参数名逐项填写，例如 BARK_PUSH、BARK_ARCHIVE、BARK_GROUP

### Changed

- 媒体组过滤改为在 `copy_media_group` 首次请求中携带清理后的 caption，避免正常过滤路径先发送后逐项编辑；仅过滤后为空的原有 caption 补一次清空编辑

### Fixed

- 修复 Bot dispatcher 在默认事件循环中等待，导致 Bot 已启动但私聊消息无响应的问题
- 修复媒体组结果消息 ID 被排序后可能影响相册条目 caption 对应关系的问题
- 修复 Bot 同步包装器与 dispatcher 使用不同事件循环的风险，启动前显式绑定客户端事件循环
- 兼容 Pyrofork 2.3.69 的 `skip_updates=True` 默认行为：Bot 和 User Client 显式启用 update gap recovery，修复连接正常但 update 不进入 handler 的问题

## 2026-11-05

### Changed

- Telegram 客户端从 Pyrogram 2.0.106 升级到 Pyrofork 2.3.69，启用 Layer 220 的 `message.quote`、`quote_text` 和 `quote_entities` 解析
- GHCR 基础镜像从 Python 3.9 升级到 Python 3.12，满足 Pyrofork 2.3.69 的运行时要求
- 增加 Pyrofork `WEB_PAGE_PREVIEW` 兼容映射和 Telegram 客户端版本启动日志
- 排除/删除关键词改为任务级预编译，规则不变时不再为每条消息重复编译
- 无过滤规则的任务直接走快速路径，跳过富文本归一化和规则匹配
- 移除发送链路中重复的暂停/取消检查，仅保留发送前和下载重传上传前的必要检查点

### Fixed

- 媒体组修改 caption 时改为“先复制或隐藏转发原媒体组，再逐项调用 edit_message_caption”，避免 `SendMultiMedia` 因 `INPUT_REQUEST_TOO_LONG` 被误判为受限频道
- 媒体组先按源消息 ID 顺序完成原相册发送，再逐项写入纯文本 caption；空字符串会真正清除对应条目说明
- 下载重传日志不再统一标记为“受限媒体”，只有真实 `CHAT_FORWARDS_RESTRICTED` 才记录受限状态
- 暂停或取消会在每个发送单元开始前再次检查；下载重传完成、真正上传前也会检查，取消后不再启动新的上传
- 修复 Telegram 引用回复中的可见文本未被读取，导致富文本内容无法命中排除/删除规则的问题
- 过滤任务日志会记录首次检测到 Pyrofork 引用文本，便于确认规则是否进入过滤分支
- 过滤前统一生成纯文本视图，清除 Telegram entities、零宽字符、双向控制符、变体选择符并执行 Unicode NFKC 归一化
- 删除规则命中富文本时使用纯文本结果重发，确保目标消息不再保留粗体、引用、自定义表情等格式
- 排除和删除规则现在会检查正文、媒体 caption、引用文本、回复预览和链接预览标题/描述
- 删除规则命中引用或回复预览时会移除引用并重发正文，避免原生转发继续保留广告文本
- 媒体组过滤继续对每一条 caption 独立执行，并覆盖富文本和回复预览

### Added

- 命令历史支持单独删除指定记录，运行中或暂停中的任务禁止删除
- 时间范围历史命令会从 Unix 时间戳回显开始日期、结束日期和创建时间

## 2026-11-04

### Added

- 批量转发支持运行时热更新排除关键词、排除正则、删除关键词和删除正则
- 批量转发支持暂停、继续和暂停状态下取消；继续时从下一条未处理消息接着执行
- 批量执行状态新增收集、准备、转发阶段、进度百分比和预计剩余时间
- 批量读取改为每 100 条一次 RPC，显著减少大量消息任务的准备时间
- 新增媒体组逐条 caption 过滤和原生相册 caption 覆盖测试

### Fixed

- 修复删除正则清空媒体组 caption 时，Pyrogram 缓存复制仍保留原说明的问题
- 补齐 clone、direct、cache 以及 Bot 中转媒体组路径的空 caption 覆盖逻辑
- 修复媒体组只检查第一条 caption，导致后续消息中的排除/删除规则不生效的问题
- 修复媒体组过滤后只能修改第一条 caption、其余条目可能保留原说明的问题
- 修复排除命中、空消息和清理后空文本任务未及时持久化“跳过/已处理”进度的问题
- 增加用户样例正则、三种转发模式、运行时改规则和暂停续跑的回归测试

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
