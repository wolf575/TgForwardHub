# TG Forward Hub 功能说明

本文档对应当前仓库版本，介绍网页批量转发、Bot 链接转发、实时监控、记录模式、媒体存储和运行设置。

## 功能总览

| 模块 | 能力 |
| --- | --- |
| 网页批量转发 | 按消息 ID 或日期范围转发，支持三种模式、过滤规则、媒体组和任务历史 |
| Bot 链接转发 | 私聊发送 Telegram 消息链接，取回单条、区间或媒体组内容 |
| 实时监控 | 监控频道、群组、私聊或收藏夹，自动转发、提取或记录 |
| 记录笔记 | 保存、搜索、筛选、收藏、编辑和删除 Telegram 内容 |
| 媒体存储 | 本地存储或 WebDAV 远程存储 |
| 磁力校准 | 提取磁力链接、补全 `dn`、自动重试和后台队列 |
| Web 管理 | Telegram 配置向导、运行状态、账号密码、时区、通知和主题 |

## 网页批量转发

### 来源与目标

来源和目标支持以下写法：

- `@channel_name`
- `-1001234567890`
- 当前账号可以解析的频道/群组引用
- 目标为 `me` 时发送到个人收藏夹

网页批量转发始终需要用户客户端 Session String。Bot 客户端只在 `cache` 模式配置了中转缓冲会话时参与受限内容中转。

### 范围类型

**消息 ID 范围**

填写起始消息 ID 和结束消息 ID。后端会自动把倒序输入整理为正序，再根据「逆序转发」决定处理顺序。

**日期范围**

在网页中选择开始日期和结束日期。前端会转换为本地零点时间戳，后端按消息时间读取来源历史。执行前请以页面显示的实际时间戳为准。

### 转发模式

#### `clone`：隐藏来源

默认模式，适合镜像频道内容。

处理顺序：

1. 尝试用户客户端 `messages.ForwardMessages(drop_author=True)`，保留 Telegram 缓存媒体并隐藏原来源。
2. 失败后尝试缓存复制。
3. 仍受限时，下载媒体后通过用户客户端重新上传。

媒体组会整组处理，避免相册只发送第一项。

#### `direct`：保留来源

使用 `forward_messages`，目标消息会显示原始转发来源。适合需要明确标注来源的场景。

#### `cache`：缓存发送

使用 `copy_message` 或 `copy_media_group` 复用 Telegram 缓存媒体，不显示转发来源。

如果来源禁止缓存复制，可以在网页中填写「中转缓冲会话」：

```text
来源 → Bot 中转缓冲会话 → 用户客户端隐藏转发 → 目标
```

中转缓冲会话必须是 Bot 和用户客户端都能访问的频道或群组，并给 Bot 发送消息的权限。

### 过滤规则

| 规则 | 行为 |
| --- | --- |
| 排除关键词 | 文本包含任一关键词时，整条消息或整个媒体组跳过 |
| 排除正则 | 正则匹配时，整条消息或整个媒体组跳过 |
| 删除关键词 | 从文本中删除命中的关键词后继续转发 |
| 删除正则 | 从文本中删除正则匹配内容后继续转发 |

关键词支持逗号或 `|` 分隔。正则每行一条，使用 Python `re` 语法。排除规则优先级高于删除规则。

如果删除文本后只剩空文本，且消息没有媒体，则该消息会跳过。

### 进度与历史

- 实时显示状态、已处理、成功、失败和跳过数量。
- 支持取消运行中的任务。
- 任务日志保留在右侧面板，历史任务可从「命令历史」恢复。
- 历史记录写入 `data/history.db`。

## Bot 链接转发

在 Bot 私聊中直接发送 Telegram 消息链接。支持公开频道、私有频道和 Bot 聊天。

### 单条链接

```text
https://t.me/channel_name/123
https://t.me/c/1234567890/456
https://t.me/b/example_bot/789
```

### 区间链接

以下四种写法等价：

```text
https://t.me/channel_name/100-120
https://t.me/channel_name/100 120
https://t.me/channel_name/100-https://t.me/channel_name/120
https://t.me/channel_name/100 https://t.me/channel_name/120
```

私有频道和 Bot 聊天同样支持完整第二条链接或只写结束 ID。

### 媒体组

如果链接指向相册中的消息，Bot 会尝试复制整个媒体组。网页批量转发也会识别媒体组，并把同一组消息只处理一次。

### 权限要求

- 公开内容通常可以直接由 Bot 读取和复制。
- 私有频道、Bot 聊天或受限来源需要 Session String。
- 用户客户端账号必须已加入私有频道，或具备访问该消息的权限。

## 实时监控

### 监控来源

支持：

- 频道和群组
- 私聊
- `me`：当前用户客户端的个人收藏夹

来源可以是数字 ID、`@username`，也可以直接转发一条来源消息给 Bot 进行识别。

### 监控目标

- 频道、群组或 `me`
- 一个来源可以配置多个目标
- 同一个来源可以同时存在记录任务和转发任务

### 处理模式

**完整转发**

转发原始文本、媒体、媒体组和实体信息，可选择是否保留来源。

**内容提取**

先通过关键词/正则过滤，再用提取正则从文本中提取内容。提取结果去重后以新消息发送。

**记录模式**

把消息写入网页笔记和本地/WebDAV 媒体存储，不发送到目标聊天。

### 过滤规则

监控任务支持：

- 关键词白名单
- 关键词黑名单
- 正则白名单
- 正则黑名单
- 提取正则
- 磁力链接 `dn` 自动补全

### 可靠性

- 媒体组去重
- FloodWait 自动等待
- 无效 Peer 自动跳过
- 失败消息重试
- 目标频道也是监控源时，支持链式触发
- 启动时自动加载监控配置

不要在多个容器或多个进程中同时使用同一个 Bot Token，否则可能造成重复处理。

## 记录笔记与媒体管理

### 笔记

- 按文本或来源搜索
- 按日期筛选
- 按来源筛选
- 仅显示收藏
- 编辑和删除
- 搜索结果关键词高亮

### 媒体

- 本地媒体目录：`data/media/`
- WebDAV 可选远程存储
- 可选择是否保留本地副本
- 下载文件目录：`downloads/`

### 磁力链接与校准

- 自动提取消息中的磁力链接
- 为缺少 `dn` 的链接补全文件名
- 自动校准任务进入队列
- 支持配置首次延迟、重试次数、并发数、单磁力超时和批次超时
- 支持手动重试或删除校准任务

## Web 管理与设置

### 初始配置

- Bot Token
- Telegram API ID 和 API Hash
- 手机号
- 验证码
- 两步验证密码
- Session String 自动生成和保存

### 运行设置

- 管理员用户名和密码
- 时区
- 批量转发完成通知开关
- WebDAV
- 自动校准
- 观看网站 URL
- 深色、浅色、青蓝、暖金主题

### 状态检查

设置页显示：

- Web 服务状态
- Telegram Bot 状态
- 用户客户端状态
- 当前监控源数量

## 配置文件

### 主配置

`data/config/config.json`

```json
{
  "TOKEN": "your_bot_token",
  "ID": "your_api_id",
  "HASH": "your_api_hash",
  "STRING": "your_session_string"
}
```

### 监控配置

`data/config/watch_config.json`

```json
{
  "123456789": {
    "-1001234567890|me": {
      "source": "-1001234567890",
      "dest": "me",
      "whitelist": ["重要", "紧急"],
      "blacklist": ["测试", "广告"],
      "whitelist_regex": [],
      "blacklist_regex": ["(?i)spam"],
      "preserve_forward_source": false,
      "forward_mode": "full",
      "extract_patterns": [],
      "append_dn_to_magnet": false,
      "record_mode": false
    }
  }
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `source` | 来源聊天 ID |
| `dest` | 目标聊天 ID 或 `me` |
| `whitelist` | 关键词白名单 |
| `blacklist` | 关键词黑名单 |
| `whitelist_regex` | 正则白名单 |
| `blacklist_regex` | 正则黑名单 |
| `preserve_forward_source` | 是否保留来源 |
| `forward_mode` | `full` 或 `extract` |
| `extract_patterns` | 提取正则 |
| `append_dn_to_magnet` | 是否补全磁力链接 `dn` |
| `record_mode` | 是否使用记录模式 |

### 应用设置

`data/config/app_settings.json`

```json
{
  "timezone": "Asia/Shanghai",
  "batch_completion_notifications_enabled": true
}
```

## 限制与注意事项

- 网页批量转发和监控依赖用户客户端 Session String。
- 私有频道必须由用户账号加入，Bot 不能绕过 Telegram 权限。
- 受限内容能否缓存复制由 Telegram 服务端决定，下载重传是通用回退路径。
- 提取模式只处理文本，不处理媒体文件。
- 复杂正则可能增加处理时间。
- 当前公开 Docker 镜像为 `linux/amd64`，ARM 设备可本地构建。
- 公共镜像公开的是程序，不包含任何用户配置、Session、数据库或媒体。

## 相关文档

- [README](README.md)
- [快速开始](docs/guides/QUICKSTART.md)
- [Docker 部署](docs/guides/DOCKER_SETUP.md)
- [初始配置](docs/guides/SETUP_GUIDE.md)
- [使用示例](docs/guides/USAGE_EXAMPLES.md)
- [更新与维护](docs/UPDATE_GUIDE.md)

## 反馈

- 仓库: <https://github.com/wolf575/TgForwardHub>
- Issues: <https://github.com/wolf575/TgForwardHub/issues>
