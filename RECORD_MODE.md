# 📝 记录模式使用指南 / Record Mode Guide

## 什么是记录模式？ / What is Record Mode?

记录模式允许你将监控到的消息保存到一个美观的网页界面，而不是转发到 Telegram。这对于以下场景非常有用：

Record Mode allows you to save monitored messages to a beautiful web interface instead of forwarding them to Telegram. This is useful for:

- 📚 收集和整理信息
- 🔍 保存符合特定关键词的内容
- 📊 建立个人知识库
- 💾 避免在 Telegram 中堆积大量消息

## 功能特性 / Features

✅ **保存内容类型 / Content Types:**
- 文本消息 / Text messages
- 图片（完整分辨率）/ Images (full resolution)
- 视频缩略图 / Video thumbnails

✅ **过滤支持 / Filtering Support:**
- 关键词白名单/黑名单 / Keyword whitelist/blacklist
- 正则表达式白名单/黑名单 / Regex whitelist/blacklist
- 提取模式（正则提取）/ Extract mode (regex extraction)

✅ **网页功能 / Web Features:**
- 🔐 安全登录（默认：admin/admin）/ Secure login (default: admin/admin)
- 🎨 美观的响应式设计 / Beautiful responsive design
- 📋 按来源筛选笔记 / Filter notes by source
- 📄 分页显示（每页50条）/ Pagination (50 per page)
- ⚙️ 管理员面板修改密码 / Admin panel to change password

## 使用方法 / How to Use

### 1️⃣ 创建监控任务 / Create Monitoring Task

1. 向机器人发送 `/start`
2. 点击 "📋 监控管理" / "Monitor Management"
3. 点击 "➕ 添加监控" / "Add Watch"
4. 按照提示设置来源和目标
5. 设置过滤规则（可选）

### 2️⃣ 启用记录模式 / Enable Record Mode

1. 点击 "📋 查看列表" / "View List"
2. 点击你要修改的监控任务
3. 点击 "📝 切换记录模式" / "Toggle Record Mode"
4. 当记录模式开启后，消息将保存到网页而非转发

### 3️⃣ 查看记录的笔记 / View Recorded Notes

#### 启动 Web 应用 / Start Web Application

```bash
# 方法 1：直接运行 / Method 1: Direct run
python app.py

# 方法 2：指定端口 / Method 2: Specify port
PORT=8000 python app.py
```

#### 访问网页 / Access Web Interface

打开浏览器访问 / Open browser and visit:
```
http://localhost:5000
```

或者如果部署到服务器 / Or if deployed to server:
```
http://your-server-ip:5000
```

#### 登录 / Login

默认凭据 / Default credentials:
- 用户名 / Username: `admin`
- 密码 / Password: `admin`

**⚠️ 重要 / Important:** 首次登录后立即通过管理员面板修改密码！
**⚠️ Important:** Change the password immediately after first login through the Admin Panel!

### 4️⃣ 修改密码 / Change Password

1. 登录后，点击右上角 "⚙️ 管理" / "Admin"
2. 输入当前密码
3. 输入新密码（至少6个字符）
4. 确认新密码
5. 点击 "更新密码" / "Update Password"

## 示例场景 / Example Scenarios

### 场景 1：收集技术文章 / Scenario 1: Collect Tech Articles

```
来源 / Source: 技术频道 @tech_channel
过滤 / Filter: 关键词白名单 = "Python, JavaScript, Docker"
模式 / Mode: 记录模式 ✅
```

结果 / Result: 所有包含这些技术关键词的消息将自动保存到网页笔记。

### 场景 2：提取链接 / Scenario 2: Extract Links

```
来源 / Source: 资源分享群 @resources_group
提取模式 / Extract Mode: 正则表达式 = "https?://[^\s]+"
模式 / Mode: 记录模式 ✅
```

结果 / Result: 从消息中提取所有链接并保存到网页笔记。

### 场景 3：保存图片 / Scenario 3: Save Images

```
来源 / Source: 摄影频道 @photography_channel
过滤 / Filter: 无过滤（保存所有消息）
模式 / Mode: 记录模式 ✅
```

结果 / Result: 所有文字和图片都会保存到网页笔记。

## Web 界面功能 / Web Interface Features

### 笔记列表页 / Notes List Page

- 📊 显示总笔记数和来源数量 / Display total notes and source count
- 🔍 按来源筛选 / Filter by source
- 📄 分页浏览 / Paginated browsing
- 🕒 显示时间戳 / Show timestamps
- 🖼️ 图片和视频缩略图预览 / Image and video thumbnail preview

### 管理员面板 / Admin Panel

- 🔐 修改登录密码 / Change login password
- ✅ 密码强度验证 / Password strength validation
- 🔄 立即生效 / Takes effect immediately

## 技术细节 / Technical Details

### 数据存储 / Data Storage

- **数据库 / Database:** SQLite (`notes.db`)
- **媒体文件 / Media Files:** `media/` 目录
- **文件命名 / File Naming:** `{message_id}_{timestamp}.jpg`

### 安全性 / Security

- ✅ Bcrypt 密码哈希 / Bcrypt password hashing
- ✅ Session-based 认证 / Session-based authentication
- ✅ 媒体文件需登录访问 / Media files require login
- ✅ CSRF 保护 / CSRF protection

### 性能 / Performance

- 每页显示 50 条笔记 / 50 notes per page
- 图片完整分辨率保存 / Images saved in full resolution
- 视频仅保存缩略图 / Videos save thumbnails only

## 注意事项 / Notes

1. **记录模式和转发模式互斥** / Record mode and forward mode are mutually exclusive
   - 开启记录模式后，消息不会转发
   - When record mode is enabled, messages won't be forwarded

2. **同一来源可以有多个任务** / Same source can have multiple tasks
   - 可以创建多个任务，有的转发，有的记录
   - You can create multiple tasks, some forwarding, some recording

3. **过滤规则仍然生效** / Filter rules still apply
   - 所有过滤规则（关键词、正则）在记录模式下仍然生效
   - All filter rules (keywords, regex) still work in record mode

4. **提取模式支持** / Extract mode support
   - 在记录模式下可以使用提取模式
   - Extract mode works with record mode
   - 提取的内容会保存为文本
   - Extracted content is saved as text

## 部署建议 / Deployment Recommendations

### Heroku 部署 / Heroku Deployment

`Procfile` 已包含 web 进程配置 / `Procfile` already includes web process:

```
worker: python3 main.py
web: python3 app.py
```

### Docker 部署 / Docker Deployment

确保映射端口和挂载卷 / Make sure to map ports and mount volumes:

```bash
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/notes.db:/app/notes.db \
  -v $(pwd)/media:/app/media \
  your-image-name
```

### 本地开发 / Local Development

```bash
# Terminal 1: 运行 Bot / Run Bot
python main.py

# Terminal 2: 运行 Web 应用 / Run Web App
python app.py
```

## 故障排查 / Troubleshooting

### 问题：无法登录 / Issue: Cannot login
**解决 / Solution:** 
- 确认用户名和密码正确 / Verify username and password
- 检查数据库文件是否存在 / Check if database file exists
- 尝试删除 `notes.db` 重新初始化 / Try deleting `notes.db` to reinitialize

### 问题：图片无法显示 / Issue: Images not showing
**解决 / Solution:**
- 检查 `media/` 目录权限 / Check `media/` directory permissions
- 确认已登录 / Make sure you're logged in
- 检查文件是否存在 / Check if files exist

### 问题：笔记未保存 / Issue: Notes not being saved
**解决 / Solution:**
- 检查 Bot 日志 / Check bot logs
- 确认记录模式已开启 / Confirm record mode is enabled
- 验证过滤规则是否正确 / Verify filter rules are correct

## 反馈与支持 / Feedback & Support

如果遇到问题或有建议，请在 GitHub 仓库提交 Issue。

If you encounter issues or have suggestions, please submit an Issue on the GitHub repository.

---

享受使用记录模式！📝✨

Enjoy using Record Mode! 📝✨
