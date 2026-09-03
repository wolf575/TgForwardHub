# 修复B→机器人提取任务的outgoing消息处理

## 问题分析

### 根本原因
**Pyrogram的message handler默认只监听incoming消息，不监听outgoing消息**

### 消息流转过程
```
A频道消息
  ↓（转发）
B频道收到消息 ← 从B频道的角度看，这是"outgoing"消息（由机器人发出的）
  ↓（自动提取）
机器人（应该触发提取任务）
  ❌ 但当前的消息处理器监听不到outgoing消息，所以不触发！
```

### 为什么是outgoing？
- A频道发消息 → 这是A频道的outgoing消息
- Bot转发到B频道 → 这是B频道的outgoing消息（因为是Bot发出的）
- 从B频道的角度看，收到的是由Bot转发过来的消息，属于outgoing类型
- Pyrogram默认的on_message只监听incoming，不监听outgoing

## 修复内容

### 1. 添加outgoing过滤器（核心修复）
**位置：main.py:2683**

**修改前：**
```python
@acc.on_message(filters.channel | filters.group | filters.private)
def auto_forward(client, message):
```

**修改后：**
```python
@acc.on_message((filters.channel | filters.group | filters.private) & (filters.incoming | filters.outgoing))
def auto_forward(client, message):
    """处理频道/群组/私聊消息，包括转发的消息"""
```

**关键改进：**
- ✅ 添加`filters.outgoing`
- ✅ 现在可以监听A→B转发后的消息
- ✅ B→机器人的提取任务能正常触发

### 2. 添加消息类型日志
**位置：main.py:2740-2744**

在消息预览日志后添加：
```python
# 记录消息来源类型
if message.outgoing:
    logger.debug(f"   📤 outgoing消息（由Bot转发）")
else:
    logger.debug(f"   📥 incoming消息（外部来源）")
```

这样可以在日志中清晰看到消息是由Bot转发的还是外部来源。

## 验证方法

### 完整的消息流转测试
```
A频道: 发送 "有个好资源：magnet:?xt=urn:btih:xxx"
  ↓
日志: 📨 收到消息: 内容=有个好资源：magnet:...
日志:    📥 incoming消息（外部来源）
  ↓
日志: 📤 转发消息到B频道
  ↓
B频道: 收到转发的消息 "有个好资源：magnet:..."
  ↓
日志: 📨 收到消息: 内容=有个好资源：magnet:...
日志:    📤 outgoing消息（由Bot转发）
  ↓
日志: 🔍 进入extract模式，检测到磁力链接
  ↓
日志: 📤 转发提取结果到机器人（仅磁力链接）
  ↓
机器人: 收到提取的磁力链接 "magnet:?xt=urn:btih:xxx"
```

### 关键日志标记
- `📥 incoming消息（外部来源）` - 从A频道直接收到的消息
- `📤 outgoing消息（由Bot转发）` - Bot转发到B频道后，B频道触发的消息
- 两种类型的消息都会被正确处理

## 预期结果

修复完成后应该能看到：

- ✅ A频道的消息成功转发到B频道
- ✅ B频道收到的消息被正确处理（作为outgoing消息）
- ✅ B→机器人的提取任务正常触发
- ✅ 机器人收到提取的磁力链接
- ✅ 日志中清晰显示消息流转过程和消息类型

## 技术细节

### Pyrogram消息类型
- **incoming**: 从其他用户/频道发送到当前账号的消息
- **outgoing**: 从当前账号发送出去的消息
- 当Bot转发消息到频道B时，这条消息在频道B的上下文中被标记为outgoing
- 只监听incoming会漏掉所有由Bot转发产生的消息

### 过滤器组合
```python
(filters.channel | filters.group | filters.private) & (filters.incoming | filters.outgoing)
```
- 监听所有类型的聊天（频道、群组、私聊）
- 监听所有方向的消息（incoming和outgoing）
- 确保不会漏掉任何需要处理的消息

## 注意事项

### 消息去重
当前实现已经有消息去重机制（基于chat_id和message_id），可以防止同一条消息被处理多次：
```python
if is_message_processed(message.id, message.chat.id):
    logger.debug(f"⏭️ 跳过已处理的消息: chat_id={message.chat.id}, message_id={message.id}")
    return

mark_message_processed(message.id, message.chat.id)
```

### 媒体组去重
媒体组也有独立的去重机制，防止重复处理：
```python
if media_group_key in processed_media_groups:
    logger.debug(f"   跳过：媒体组已处理 (media_group_key={media_group_key})")
    continue
register_processed_media_group(media_group_key)
```

## 相关配置

确保B→机器人的watch_config配置正确：
```json
{
  "user_id": {
    "B_channel_id|bot_id": {
      "source": "B_channel_id",
      "dest": "bot_id",
      "forward_mode": "extract",
      "extract_patterns": ["magnet:\\?xt=urn:btih:(?:[a-fA-F0-9]{40}|[a-zA-Z2-7]{32})"],
      "whitelist": ["magnet:"],
      "record_mode": false
    }
  }
}
```

## 测试场景

1. **A→B转发 + B→Bot提取**
   - A频道发送带磁力链接的消息
   - Bot转发到B频道（完整消息）
   - Bot从B频道提取磁力链接
   - Bot将提取的链接发送给自己

2. **多级转发**
   - A→B（转发）
   - B→C（转发）
   - C→Bot（提取）
   - 每一级都能正确触发

3. **混合模式**
   - A→B（转发+记录）
   - B→Bot（提取）
   - 两个任务都能正常工作

## 修复日期
2024-01-XX

## 修复文件
- `main.py`: 修改消息处理器过滤器，添加outgoing支持和日志记录
