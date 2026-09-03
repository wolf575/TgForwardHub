# Peer Caching Fix - 解决 "Peer id invalid" 错误

## 问题描述

在使用机器人监控频道时，部分用户遇到以下错误：

```
KeyError: 'ID not found: -1002379846980'
ValueError: Peer id invalid: -1002379846980
```

这导致一些频道的消息无法保存到网页笔记或无法正常转发。

## 问题原因

Pyrogram 在处理来自频道的消息时，需要从本地 session 文件中查找该频道的 peer 信息。如果 session 中没有缓存这个频道的信息，就会抛出 "Peer id invalid" 错误。

这个问题通常发生在：
- Bot 首次监控一个新频道
- Session 文件被清空或重新生成
- 长时间未与某个频道交互，缓存过期

## 解决方案

实现了**启动时预缓存机制**：

1. **启动时自动缓存**: Bot 启动时会遍历所有监控任务的配置，提取所有被监控的频道 ID
2. **主动获取频道信息**: 对每个频道调用 `acc.get_chat()` 来获取频道信息，Pyrogram 会自动将这些信息缓存到 session 文件中
3. **智能过滤**: 只缓存频道和群组（负数 ID），不缓存用户 ID（正数）
4. **错误处理**: 如果某个频道无法访问，会显示警告但不影响其他频道的缓存

## 修改内容

修改文件：`main.py`

在 `print_startup_config()` 函数中添加了预缓存逻辑：

```python
# Collect all unique source IDs to pre-cache
source_ids_to_cache = set()

# 遍历所有监控任务，收集需要缓存的频道 ID
for user_id, watches in watch_config.items():
    for watch_key, watch_data in watches.items():
        # 提取 source_id
        # 只添加负数 ID（频道/群组）
        if chat_id_int < 0:
            source_ids_to_cache.add(source_id)

# Pre-cache all source channels
if acc is not None and source_ids_to_cache:
    print("🔄 预加载频道信息到缓存...")
    for source_id in source_ids_to_cache:
        try:
            acc.get_chat(int(source_id))
            print(f"   ✅ 已缓存: {source_id}")
        except Exception as e:
            print(f"   ⚠️ 无法缓存 {source_id}: {str(e)}")
```

## 启动日志示例

修复后，Bot 启动时会显示缓存进度：

```
🤖 Telegram Save-Restricted Bot 启动成功
============================================================

📋 已加载 1 个用户的 3 个监控任务：

👤 用户 123456789:
   📤 -1001234567890 → me
   📝 -1002379846980 → 记录模式
   📤 -1003333333333 → me

🔄 预加载频道信息到缓存...
   ✅ 已缓存: -1001234567890
   ✅ 已缓存: -1002379846980
   ✅ 已缓存: -1003333333333
📦 成功缓存 3/3 个频道

============================================================
✅ 机器人已就绪，正在监听消息...
============================================================
```

## 注意事项

1. **需要正确的权限**: 如果某个频道无法访问（如机器人未加入或被踢出），会显示警告但不影响其他功能
2. **Session String 必需**: 预缓存功能需要配置了 Session String (acc 对象存在)
3. **监控 "me" 不会缓存**: 监控自己的收藏夹（source="me"）时使用用户 ID，不需要缓存
4. **自动生效**: 无需手动操作，Bot 重启后自动执行预缓存

## 测试方法

1. 配置监控任务，包括之前出现 "Peer id invalid" 错误的频道
2. 重启 Bot
3. 查看启动日志，确认频道是否成功缓存
4. 发送测试消息到被监控的频道
5. 验证消息是否正常保存到网页笔记或转发

## 相关问题

如果仍然遇到 "Peer id invalid" 错误：

1. 检查 Session String 是否正确配置
2. 确认机器人账号已加入被监控的频道/群组
3. 查看启动日志中的缓存状态
4. 如果频道是私有的，确保使用的是正确的 Chat ID（负数）

## 技术细节

- **频道/群组 ID**: 都是负数，通常以 `-100` 开头（如 `-1002379846980`）
- **用户 ID**: 都是正数（如 `123456789`）
- **预缓存时机**: Bot 启动时一次性完成
- **Session 存储**: Pyrogram 自动将 peer 信息保存到 `.session` 文件中
- **有效期**: 缓存在 session 中长期有效，除非 session 文件被删除
