# 修复：转发重复问题 - 消息去重机制

## 问题描述

同一条消息在极短时间内（1ms内）被多次转发，导致目标频道收到重复消息。

### 日志证据
```
04:25:23,826 - 📤 转发模式：开始处理
04:25:23,827 - 📤 转发模式：开始处理  // 1ms 后重复
04:25:23,828 - 📤 转发模式：开始处理  // 又重复
04:25:23,829 - 📤 转发模式：开始处理  // 又重复
04:25:23,830 - 📤 转发模式：开始处理  // 又重复
```

## 根本原因

同一条消息 ID 在极短时间内被多次处理，原因：
1. Telegram 可能在极短时间内发送多个 update 事件
2. 没有去重机制来防止重复处理

## 解决方案

### 1. 实现消息去重系统

在 `main.py` 中添加了基于内存缓存的消息去重系统：

```python
# Message deduplication cache
processed_messages = {}
MESSAGE_CACHE_TTL = 5  # 5秒TTL


def is_message_processed(message_id, chat_id):
    """检查消息是否已处理"""
    key = f"{chat_id}_{message_id}"
    if key in processed_messages:
        if time.time() - processed_messages[key] < MESSAGE_CACHE_TTL:
            return True
        else:
            del processed_messages[key]
    return False


def mark_message_processed(message_id, chat_id):
    """标记消息已处理"""
    key = f"{chat_id}_{message_id}"
    processed_messages[key] = time.time()


def cleanup_old_messages():
    """清理过期的消息记录"""
    current_time = time.time()
    expired_keys = [key for key, timestamp in processed_messages.items() 
                    if current_time - timestamp > MESSAGE_CACHE_TTL]
    for key in expired_keys:
        del processed_messages[key]
```

### 2. 在 auto_forward 函数中添加去重检查

在 `auto_forward` 函数的开始处添加了去重逻辑：

```python
# Check for duplicate messages
if not hasattr(message, 'id') or message.id is None:
    logger.debug("跳过：消息缺少有效的 message ID")
    return

if is_message_processed(message.id, message.chat.id):
    logger.debug(f"⏭️ 跳过已处理的消息: chat_id={message.chat.id}, message_id={message.id}")
    return

# Mark message as processed immediately to prevent duplicate processing
mark_message_processed(message.id, message.chat.id)

# Periodically clean up old message records
if len(processed_messages) > 1000:
    cleanup_old_messages()
```

### 3. 关键特性

- **唯一键**：使用 `{chat_id}_{message_id}` 组合作为唯一标识
- **TTL机制**：5秒过期时间，自动清理旧记录
- **性能优化**：当缓存超过1000条记录时自动触发清理
- **早期检查**：在消息处理的最开始就进行去重检查，避免浪费资源

## 测试验证

创建了完整的测试脚本 `test_deduplication.py`，验证了：

1. ✅ 新消息未被标记为已处理
2. ✅ 消息可以被正确标记为已处理
3. ✅ 重复消息被成功检测
4. ✅ 不同消息ID不会被误判为重复
5. ✅ 不同聊天ID不会被误判为重复
6. ✅ TTL过期后消息记录被正确清理
7. ✅ 清理函数正常工作
8. ✅ 模拟原始问题：5次重复处理中只有1次被执行，其余4次被正确跳过

## 代码位置

- **去重系统定义**：`main.py` 第 1734-1762 行
- **去重检查调用**：`main.py` 第 1812-1826 行（在 `auto_forward` 函数中）

## 影响范围

- **最小化影响**：只在消息处理开始时添加轻量级检查
- **向后兼容**：不影响现有功能，只是防止重复
- **性能开销**：O(1) 字典查找，几乎无性能影响

## 预期效果

修复后：
- 同一条消息在5秒内只会被处理一次
- 日志中不再出现相同消息的重复处理日志
- 目标频道不会收到重复的转发消息
- 系统性能不受影响

## 部署说明

1. 更新 `main.py` 文件
2. 重启机器人服务
3. 测试发送多张图片的媒体组消息
4. 观察日志，确认同一消息不会被重复处理
