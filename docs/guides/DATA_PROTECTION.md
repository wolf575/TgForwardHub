# 数据和配置保护指南

## 🔒 重要说明

本项目的配置文件和用户数据已经从Git仓库中移除，确保在代码更新时不会丢失您的数据。

## 📁 保护的文件和目录

以下文件和目录**不会**被Git跟踪，在 `git pull` 更新代码时会保留：

### 1. 配置文件
- `config.json` - Bot 配置（TOKEN, ID, HASH, STRING）
- `watch_config.json` - 监控任务配置

### 2. 数据目录
- `data/` - 所有用户数据目录
  - `data/notes.db` - 记录模式的笔记数据库
  - `data/media/` - 下载的图片和视频缩略图

### 3. Session 文件
- `*.session` - Pyrogram session 文件
- `*.session-journal` - Session 日志文件

## ⚙️ 首次配置

### 方式一：从示例文件创建

```bash
# 复制配置示例
cp config.json.example config.json
cp watch_config_example.json watch_config.json

# 编辑配置文件
nano config.json  # 填入你的 TOKEN, ID, HASH, STRING
```

### 方式二：使用自动配置脚本

```bash
python3 setup.py
```

## 🔄 更新代码时的注意事项

更新代码时，你的配置和数据**会自动保留**：

```bash
# 更新代码（安全操作）
git pull origin main

# 你的以下文件不会被覆盖：
# ✅ config.json
# ✅ watch_config.json
# ✅ data/ 目录下的所有内容
# ✅ *.session 文件
```

## 🚨 如果配置文件被git跟踪了

如果你发现配置文件仍然被git跟踪（会导致更新时丢失），执行以下命令修复：

```bash
# 停止跟踪配置文件（但保留本地文件）
git rm --cached config.json
git rm --cached watch_config.json

# 确认 .gitignore 包含这些文件
cat .gitignore | grep -E "config.json|watch_config.json|data/"

# 提交改动
git add .gitignore
git commit -m "Stop tracking config files"
```

## 💾 备份建议

虽然配置和数据已经受到保护，但建议定期备份：

```bash
# 备份配置文件
cp config.json config.json.backup
cp watch_config.json watch_config.json.backup

# 备份整个数据目录
tar -czf data_backup_$(date +%Y%m%d).tar.gz data/

# 或使用rsync同步到其他位置
rsync -av data/ /path/to/backup/location/
```

## 🔍 验证配置保护状态

### 快速检查（推荐）

使用自动检查脚本一键检查所有配置保护状态：

```bash
# 运行自动检查脚本
./check_config_protection.sh
```

该脚本会自动检查：
- ✅ 配置文件是否被Git跟踪
- ✅ 本地配置文件是否存在
- ✅ .gitignore 是否正确配置
- ✅ data 目录状态
- ✅ Git 工作区状态

### 手动检查

检查文件是否被Git跟踪：

```bash
# 查看被跟踪的文件
git ls-files | grep -E "config\.json|watch_config\.json|data/"

# 如果没有输出，说明配置已被正确保护
# 如果有输出，说明文件仍被跟踪，需要执行上面的"停止跟踪"步骤
```

检查本地文件是否存在：

```bash
# 检查配置文件
ls -la config.json watch_config.json

# 检查数据目录
ls -la data/
```

## 📋 数据迁移

如果你从旧版本升级，数据文件可能在项目根目录，使用迁移脚本：

```bash
python3 migrate_data.py
```

该脚本会自动将 `notes.db` 和 `media/` 移动到 `data/` 目录。

## ⚡ 快速诊断

如果遇到数据丢失问题，按以下步骤排查：

1. **检查文件是否被Git跟踪**：
   ```bash
   git ls-files | grep config.json
   ```
   - 如果有输出：文件被跟踪，需要停止跟踪
   - 如果无输出：文件已被正确保护

2. **检查.gitignore**：
   ```bash
   cat .gitignore | grep -E "config|watch_config|data"
   ```
   - 应该包含：config.json, watch_config.json, data/

3. **检查本地文件**：
   ```bash
   ls -la config.json watch_config.json data/
   ```
   - 确认文件确实存在

4. **检查git状态**：
   ```bash
   git status
   ```
   - config.json, watch_config.json 不应出现在变更列表中

## 🎯 最佳实践

1. **首次部署**：
   - 先配置好 config.json 和 watch_config.json
   - 确认 .gitignore 正确配置
   - 验证文件未被Git跟踪

2. **日常使用**：
   - 不要手动 `git add config.json` 或 `git add watch_config.json`
   - 定期备份 data/ 目录
   - 更新代码前先备份配置

3. **团队协作**：
   - 不要将 config.json 提交到远程仓库
   - 使用 config.json.example 作为模板
   - 每个环境使用独立的配置文件

## 🆘 恢复数据

如果不小心丢失了配置：

1. **从备份恢复**：
   ```bash
   cp config.json.backup config.json
   ```

2. **从其他环境复制**：
   ```bash
   scp user@server:/path/to/config.json ./
   ```

3. **重新配置**：
   ```bash
   python3 setup.py  # 重新生成 session string
   # 然后手动编辑 config.json
   ```

## 📞 获取帮助

如果仍然遇到配置丢失问题：

1. 检查git日志，看看配置何时被修改：
   ```bash
   git log --all --full-history -- config.json
   ```

2. 查看当前分支：
   ```bash
   git branch
   ```

3. 确认远程仓库状态：
   ```bash
   git remote -v
   git fetch
   git status
   ```

---

**记住**：正确配置 .gitignore 并停止跟踪配置文件后，你的数据在代码更新时会自动保留！
