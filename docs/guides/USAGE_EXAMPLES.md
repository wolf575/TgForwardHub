# 使用示例 | Usage Examples

[中文](#中文示例) | [English](#english-examples)

---

## 中文示例

### 🎯 场景 1：转发公开频道内容

假设你想转发一个公开频道的消息：

1. **复制消息链接**：在 Telegram 中打开消息，点击右上角菜单 → "复制链接"
   ```
   https://t.me/example_channel/123
   ```

2. **发送给机器人**：直接把链接发送给你的机器人

3. **接收内容**：机器人会自动转发该消息给你

> 💡 **提示**：公开频道不需要 Session String

---

### 🔒 场景 2：转发私有频道内容

对于私有频道，需要先加入频道：

#### 方法 A：如果你的 Session String 账号已经加入了该频道

直接发送消息链接即可：
```
https://t.me/c/1234567890/456
```

#### 方法 B：如果还未加入

1. **先发送邀请链接**：
   ```
   https://t.me/+AbCdEfGhIjKlMn
   ```
   机器人会自动加入频道

2. **然后发送消息链接**：
   ```
   https://t.me/c/1234567890/456
   ```

> ⚠️ **注意**：私有频道必须配置 Session String

---

### 📦 场景 3：批量下载多条消息

使用 "起始-结束" 格式批量下载：

#### 公开频道批量下载
```
https://t.me/example_channel/100-110
```
这会下载从第100条到第110条的所有消息（共11条）

#### 私有频道批量下载
```
https://t.me/c/1234567890/50-60
```

#### 支持空格
```
https://t.me/example_channel/100 - 110
```
中间的空格可有可无，两种格式都支持

---

### 🤖 场景 4：转发机器人聊天内容

某些机器人的消息需要使用特殊格式：

```
https://t.me/b/example_bot/789
```

> 💡 **提示**：需要使用非官方客户端才能获取机器人消息的 ID

---

### 📸 场景 5：下载媒体组（相册）

如果消息包含多张图片或视频（媒体组），使用 `?single` 参数：

```
https://t.me/example_channel/123?single
```

机器人会下载该消息中的所有媒体文件

---

## 实际操作演示

### 示例 1：转发单条公开频道消息

```
你: https://t.me/telegram/123

机器人: [自动转发该消息的内容]
```

---

### 示例 2：加入私有频道并转发

```
你: https://t.me/+AbCdEfGhIjKlMn

机器人: **Chat Joined**

你: https://t.me/c/1234567890/100

机器人: __Downloading__ : 45.2%
机器人: __Uploaded__ : 78.9%
机器人: [转发的内容]
```

---

### 示例 3：批量下载10条消息

```
你: https://t.me/example_channel/1001-1010

机器人: [自动依次转发10条消息]
      消息ID 1001
      消息ID 1002
      ...
      消息ID 1010
```

---

## English Examples

### 🎯 Scenario 1: Forward Public Channel Content

To forward a message from a public channel:

1. **Copy message link**: Open message in Telegram, tap menu → "Copy Link"
   ```
   https://t.me/example_channel/123
   ```

2. **Send to bot**: Simply send the link to your bot

3. **Receive content**: Bot will automatically forward the message to you

> 💡 **Tip**: No Session String needed for public channels

---

### 🔒 Scenario 2: Forward Private Channel Content

For private channels, you need to join first:

#### Method A: If your Session String account already joined

Simply send the message link:
```
https://t.me/c/1234567890/456
```

#### Method B: If not yet joined

1. **First send invite link**:
   ```
   https://t.me/+AbCdEfGhIjKlMn
   ```
   Bot will automatically join the channel

2. **Then send message link**:
   ```
   https://t.me/c/1234567890/456
   ```

> ⚠️ **Note**: Private channels require Session String configuration

---

### 📦 Scenario 3: Batch Download Multiple Messages

Use "start-end" format for batch download:

#### Public channel batch
```
https://t.me/example_channel/100-110
```
This downloads messages from 100 to 110 (11 messages total)

#### Private channel batch
```
https://t.me/c/1234567890/50-60
```

#### Spaces are allowed
```
https://t.me/example_channel/100 - 110
```
Spaces in between are optional, both formats work

---

### 🤖 Scenario 4: Forward Bot Chat Content

Some bot messages require special format:

```
https://t.me/b/example_bot/789
```

> 💡 **Tip**: Requires unofficial client to get bot message IDs

---

### 📸 Scenario 5: Download Media Groups (Albums)

If message contains multiple photos/videos (media group), use `?single` parameter:

```
https://t.me/example_channel/123?single
```

Bot will download all media files in that message

---

## Live Demo

### Example 1: Forward Single Public Channel Message

```
You: https://t.me/telegram/123

Bot: [Automatically forwards the message content]
```

---

### Example 2: Join Private Channel and Forward

```
You: https://t.me/+AbCdEfGhIjKlMn

Bot: **Chat Joined**

You: https://t.me/c/1234567890/100

Bot: __Downloading__ : 45.2%
Bot: __Uploaded__ : 78.9%
Bot: [Forwarded content]
```

---

### Example 3: Batch Download 10 Messages

```
You: https://t.me/example_channel/1001-1010

Bot: [Automatically forwards 10 messages in sequence]
      Message ID 1001
      Message ID 1002
      ...
      Message ID 1010
```

---

## 注意事项 | Important Notes

### ⚠️ 限制 | Limitations

1. **速率限制**：批量下载时，每条消息间隔3秒，避免触发 Telegram 限制
2. **文件大小**：受 Telegram API 限制，超大文件可能下载失败
3. **私有内容**：需要确保 Session String 对应的账号有权限访问

### 🔒 隐私与安全 | Privacy & Security

1. **Session String 相当于账号密码**，请妥善保管
2. **建议使用小号**生成 Session String
3. **不要分享配置文件**（`data/config/config.json`、Session String）
4. **定期检查登录设备**，及时删除异常会话

### 💡 最佳实践 | Best Practices

1. **测试链接**：先用单条消息测试，确认可用后再批量下载
2. **合理使用**：避免频繁大量下载，遵守 Telegram 服务条款
3. **备份配置**：保存好 Session String，避免重复生成
4. **及时更新**：关注项目更新，获取新功能和修复

---

## 故障排除 | Troubleshooting

### ❌ "String Session is not Set"

**原因**：未配置 Session String 或配置错误

**解决**：
1. 运行 `python setup.py` 重新配置
2. 在 Web UI 设置页确认用户客户端已连接；如需检查持久化配置，可查看
   `data/config/config.json`，但不要手工公开或分享其中的 Session String
3. 如果只转发公开内容，可忽略此错误

---

### ❌ "The username is not occupied by anyone"

**原因**：频道用户名不存在或拼写错误

**解决**：
1. 检查链接是否正确
2. 确认频道是否存在
3. 尝试在 Telegram 中打开该链接验证

---

### ❌ "Error : ..."

**原因**：各种可能的错误（权限、网络等）

**解决**：
1. 查看详细错误信息
2. 确认 Session String 账号有访问权限
3. 检查网络连接
4. 查看 Docker 日志：`docker-compose logs -f`

---

## 更多帮助 | More Help

- [快速开始](QUICKSTART.md)
- [详细设置指南](SETUP_GUIDE.md)
- [完整文档](README.md)
- [提交问题](https://github.com/bipinkrish/Save-Restricted-Bot/issues)
