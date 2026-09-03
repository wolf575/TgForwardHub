# 媒体组重复转发问题修复

## 问题描述
发送包含多个媒体文件的消息时，每个文件都被单独转发一次，导致重复转发：
- 发送4张图片 → 转发4次
- 发送3个视频 → 转发3次

### 日志证据
```
04:53:11,227 - 📤 转发模式：开始处理
04:53:11,284 - 📤 转发模式：开始处理  // 57ms后重复
04:53:11,287 - 📤 转发模式：开始处理
04:53:11,294 - 📤 转发模式：开始处理
```

## 根本原因
Telegram 的媒体组（media_group）会被分割成多条独立的消息，每条消息具有相同的 `media_group_id`。在高并发场景下，多条消息几乎同时到达（相差仅几十毫秒），它们都通过了 `processed_media_groups` 检查（因为还没有被标记为已处理），导致每条消息都被独立转发。

### 竞态条件时间线
```
T+0ms:   消息1到达 → 检查 processed_media_groups → 未找到 → 开始处理
T+57ms:  消息2到达 → 检查 processed_media_groups → 未找到 → 开始处理
T+60ms:  消息3到达 → 检查 processed_media_groups → 未找到 → 开始处理
T+67ms:  消息4到达 → 检查 processed_media_groups → 未找到 → 开始处理
T+100ms: 消息1处理完成 → 标记 media_group 为已处理（太晚了！）
```

## 修复方案

### 旧代码逻辑
1. 检查 `media_group_id` 是否已处理
2. 应用所有过滤规则（白名单/黑名单）
3. 执行转发操作
4. **转发完成后**标记 `media_group_id` 为已处理 ❌

### 新代码逻辑
1. 检查 `media_group_id` 是否已处理
2. 应用所有过滤规则（白名单/黑名单）
3. **立即标记** `media_group_id` 为已处理 ✅
4. 执行转发操作

### 代码变更
```python
# 在 main.py line 1995-1998
logger.info(f"🎯 消息通过所有过滤规则，准备处理")

# Mark media group as processed immediately to prevent duplicate processing
if media_group_key:
    register_processed_media_group(media_group_key)
    logger.debug(f"   ✅ 已标记媒体组为已处理: {media_group_key}")

try:
    # Record mode - save to database
    if record_mode:
        ...
```

移除了所有在转发后执行的 `register_processed_media_group()` 调用（共4处）。

## 关键改进

### 1. 提前标记，防止竞态
将标记操作移到转发前，确保后续到达的同组消息能立即看到"已处理"标记。

### 2. 尊重过滤规则
标记操作放在所有过滤规则检查之后，确保不会误标记未通过过滤的消息。

### 3. 统一处理
对记录模式和转发模式都使用相同的去重逻辑，确保一致性。

## 验证步骤

1. 重启机器人
2. 发送包含4张图片的消息到监控频道
3. 检查日志：
   - 应只看到1次"📤 转发模式：开始处理"
   - 应看到3次"⏭️ 跳过已处理的媒体组"
4. 检查目标频道：
   - 只应收到1条消息（包含所有4张图片）

## 预期日志输出
```
04:53:11,227 - 📨 收到消息: chat_id=-1001234567890, 内容=媒体组 (ID: abc123)
04:53:11,228 - 🎯 消息通过所有过滤规则，准备处理
04:53:11,229 - ✅ 已标记媒体组为已处理: 12345_source|dest_abc123
04:53:11,230 - 📤 转发模式：开始处理
04:53:11,284 - 📨 收到消息: chat_id=-1001234567890, 内容=媒体组 (ID: abc123)
04:53:11,285 - ⏭️ 跳过：媒体组已处理 (media_group_key=12345_source|dest_abc123)
04:53:11,287 - 📨 收到消息: chat_id=-1001234567890, 内容=媒体组 (ID: abc123)
04:53:11,288 - ⏭️ 跳过：媒体组已处理 (media_group_key=12345_source|dest_abc123)
04:53:11,294 - 📨 收到消息: chat_id=-1001234567890, 内容=媒体组 (ID: abc123)
04:53:11,295 - ⏭️ 跳过：媒体组已处理 (media_group_key=12345_source|dest_abc123)
```

## 技术细节

### media_group_key 格式
```python
media_group_key = f"{user_id}_{watch_key}_{message.media_group_id}"
```
- `user_id`: 监控任务所属用户
- `watch_key`: 监控任务标识
- `media_group_id`: Telegram 媒体组ID

### 缓存管理
使用 LRU 策略，最多保留300个最近的 media_group_key：
```python
def register_processed_media_group(key):
    if not key:
        return
    processed_media_groups.add(key)
    processed_media_groups_order.append(key)
    if len(processed_media_groups_order) > 300:
        old_key = processed_media_groups_order.pop(0)
        processed_media_groups.discard(old_key)
```

## 影响范围
- ✅ 修复了所有转发模式的重复问题
- ✅ 修复了记录模式的重复问题
- ✅ 修复了提取模式的重复问题
- ✅ 不影响单条消息的处理
- ✅ 不影响过滤规则的执行

## 相关文件
- `main.py` (line 1995-1998): 添加提前标记逻辑
- `main.py` (line 2150, 2183, 2205, 2224): 移除重复标记代码
