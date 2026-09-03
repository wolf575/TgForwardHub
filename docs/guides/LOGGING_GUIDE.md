# 📝 日志系统使用指南

## 📋 日志保存位置

所有日志统一保存在 `data/logs/` 目录：

```
data/logs/
├── bot.log          # 应用日志（Python代码输出）
├── bot.log.1        # 轮转备份1
├── bot.log.2        # 轮转备份2
├── bot.log.3        # 轮转备份3
├── bot.log.4        # 轮转备份4
├── bot.log.5        # 轮转备份5
└── docker_*.log     # Docker日志导出文件
```

---

## 🔧 日志配置说明

### 应用日志（bot.log）

**自动配置：**
- ✅ 同时输出到控制台和文件
- ✅ 文件记录DEBUG级别，控制台显示INFO级别
- ✅ 自动轮转：单文件最大10MB
- ✅ 保留最近5个备份文件
- ✅ 包含详细的文件名和行号信息

**日志格式：**
```
2025-11-17 22:30:15 - __main__ - INFO - [main.py:123] - Bot启动成功
```

### Docker日志

**配置：**
- ✅ 自动轮转：单文件最大10MB
- ✅ 保留最近5个日志文件
- ✅ 自动压缩旧日志文件

**Docker日志位置：**
```bash
# Docker默认日志位置（系统管理）
/var/lib/docker/containers/<容器ID>/<容器ID>-json.log
```

---

## 📖 使用方法

### 1. 查看实时日志

#### 本地运行：
```bash
# 查看应用日志
tail -f data/logs/bot.log

# 只看错误
tail -f data/logs/bot.log | grep -i error
```

#### Docker运行：
```bash
# 查看实时日志
docker logs -f save-restricted-bot

# 只看错误
docker logs -f save-restricted-bot 2>&1 | grep -i error
```

---

### 2. 导出Docker日志

使用提供的导出脚本：

```bash
# 导出所有日志
./export_docker_logs.sh

# 导出最近500行
./export_docker_logs.sh tail 500

# 导出最近30分钟
./export_docker_logs.sh since 30m

# 只导出错误日志
./export_docker_logs.sh error
```

**手动导出：**
```bash
# 导出所有日志
docker logs save-restricted-bot > data/logs/docker.log 2>&1

# 导出最近1000行
docker logs --tail 1000 save-restricted-bot > data/logs/docker.log 2>&1

# 导出最近1小时
docker logs --since 1h save-restricted-bot > data/logs/docker.log 2>&1
```

---

### 3. 分析日志

#### 查找错误：
```bash
# 查找所有错误
grep -i "error" data/logs/bot.log

# 查找异常堆栈
grep -A 10 "Traceback" data/logs/bot.log

# 查找特定错误
grep "PeerIdInvalid" data/logs/bot.log
```

#### 统计错误：
```bash
# 统计错误数量
grep -c "ERROR" data/logs/bot.log

# 按错误类型分组
grep "ERROR" data/logs/bot.log | cut -d'-' -f5 | sort | uniq -c
```

#### 查看特定时间段：
```bash
# 查看今天的日志
grep "$(date +%Y-%m-%d)" data/logs/bot.log

# 查看某个小时的日志
grep "2025-11-17 22:" data/logs/bot.log
```

---

## 🐛 Bug修复流程

### 方式A：手动触发（推荐）

1. **运行Bot并遇到错误**
2. **复制完整的错误信息**（包括堆栈追踪）
3. **发给老王分析**

**示例：**
```bash
# 查看最近的错误
tail -100 data/logs/bot.log | grep -A 20 "ERROR"

# 或导出错误日志
grep -A 20 "ERROR" data/logs/bot.log > error_report.txt
```

### 方式B：定期检查

```bash
# 每天检查一次错误日志
grep "ERROR" data/logs/bot.log | tail -50

# 查看今天的所有错误
grep "$(date +%Y-%m-%d)" data/logs/bot.log | grep "ERROR"
```

---

## 🔍 常见问题排查

### 问题1：日志文件不存在

**原因：** Bot还没启动过

**解决：**
```bash
# 启动Bot
python main.py
# 或
docker-compose up -d
```

### 问题2：日志文件太大

**原因：** 日志轮转未生效

**解决：**
```bash
# 检查日志文件大小
du -h data/logs/bot.log

# 手动清理旧日志
rm data/logs/bot.log.*

# 重启Bot触发轮转
docker-compose restart
```

### 问题3：Docker日志找不到

**原因：** 容器未运行或名称错误

**解决：**
```bash
# 查看容器名称
docker ps -a

# 使用正确的容器名
docker logs <实际容器名>
```

---

## 📊 日志级别说明

| 级别 | 用途 | 示例 |
|------|------|------|
| DEBUG | 详细调试信息 | 变量值、函数调用 |
| INFO | 一般信息 | Bot启动、消息处理 |
| WARNING | 警告信息 | 重试操作、配置问题 |
| ERROR | 错误信息 | 异常、失败操作 |
| CRITICAL | 严重错误 | 系统崩溃 |

**文件日志：** 记录所有级别（DEBUG及以上）
**控制台日志：** 只显示INFO及以上

---

## 🎯 最佳实践

1. **定期检查日志**
   ```bash
   # 每天检查一次错误
   grep "ERROR" data/logs/bot.log | tail -20
   ```

2. **遇到问题时导出完整日志**
   ```bash
   ./export_docker_logs.sh tail 1000
   ```

3. **保留重要的错误日志**
   ```bash
   cp data/logs/bot.log data/logs/bot_backup_$(date +%Y%m%d).log
   ```

4. **清理过期日志**
   ```bash
   # 删除30天前的导出日志
   find data/logs -name "docker_*.log" -mtime +30 -delete
   ```

---

## 🤝 给老王提供日志

**需要提供的信息：**

1. ❗ **完整的错误堆栈** - 从`Traceback`到最后一行
2. ❗ **错误发生的场景** - 你在做什么操作时出错的
3. 📋 **错误前后的日志** - 前后10-20行的上下文
4. 🔧 **你的操作步骤** - 怎么触发的这个bug

**导出方法：**
```bash
# 方法1：导出最近的日志
tail -200 data/logs/bot.log > error_report.txt

# 方法2：导出特定错误
grep -A 30 "ERROR" data/logs/bot.log > error_report.txt

# 方法3：导出Docker日志
./export_docker_logs.sh tail 500
```

---

## 📞 联系老王

把导出的日志文件或错误信息发给老王，老王立马帮你分析修复！

**老王能修复的Bug类型：**
- ✅ Python语法错误
- ✅ 逻辑错误
- ✅ 异常处理缺失
- ✅ API调用错误
- ✅ 配置问题
- ⚠️ Telegram API限制（需要分析）

**老王修不了的：**
- ❌ Telegram服务器故障
- ❌ 网络问题
- ❌ API凭据错误（需要你重新配置）
