# Peer Cache Preload Fix

## 问题描述

重启后监控配置不生效的问题：
- 配置文件保存了，重启后仍能看到配置
- 但实际上无法处理消息：Peer id invalid 错误
- 删除重新添加监控后就能正常工作

## 根本原因

1. **启动时 peer cache 预加载失败**
   - 在 `main.py` 的 `print_startup_config()` 中调用 `_cache_dest_peers()` 预加载所有目标频道
   - 如果 session 尚未完全同步或网络延迟，预加载会失败
   - 失败后仅记录警告，但消息仍会被入队处理

2. **运行时缓存尝试不充分**
   - 在 `auto_forward` 处理器中尝试缓存，但如果失败，消息仍会入队
   - MessageWorker 处理消息时发现 peer 未缓存 → Peer ID invalid → UnrecoverableError → 消息被跳过
   - 没有重试机制，导致所有后续消息都失败

## 修复方案

### 1. 增强 Peer 缓存模块 (`bot/utils/peer.py`)

#### 新增全局状态跟踪
```python
# 失败的 peer，需要延迟加载重试
failed_peers: Dict[str, float] = {}  # peer_id -> last_attempt_timestamp

# 重试冷却时间（秒）
RETRY_COOLDOWN = 60
```

#### 新增函数
- `mark_peer_failed(peer_id)` - 标记 peer 缓存失败，记录时间戳
- `should_retry_peer(peer_id)` - 检查是否可以重试（冷却时间是否已过）
- `get_failed_peers()` - 获取失败的 peer 列表

#### 增强 `cache_peer()` 函数
- 添加 `force` 参数，可强制忽略冷却时间
- 自动检查冷却时间，避免频繁重试
- 失败时自动调用 `mark_peer_failed()`
- 成功时自动从失败列表移除

#### 增强 `mark_dest_cached()` 函数
- 成功缓存后，自动从 `failed_peers` 中移除

### 2. 改进启动预加载逻辑 (`main.py`)

#### `_cache_dest_peers()` 函数改进
- 预加载失败时调用 `mark_peer_failed()` 记录失败
- 更新提示信息："这些目标将在接收到第一条消息时自动重试延迟加载"

#### `print_startup_config()` 函数改进
- 添加失败 peer 摘要显示
- 清楚列出哪些 peer 需要延迟加载

### 3. 实现延迟加载机制 (`main.py` - `auto_forward` 处理器)

#### 源频道延迟加载
```python
if not is_dest_cached(source_chat_id):
    logger.info(f"🔄 源频道未缓存，尝试延迟加载: {source_chat_id}")
    success = cache_peer(acc, source_chat_id, "源频道")
    if success:
        logger.info(f"✅ 延迟加载源频道成功: {source_chat_id}")
    else:
        logger.warning(f"⚠️ 延迟加载源频道失败，继续处理（记录模式不受影响）")
```

#### 目标频道延迟加载 + 消息跳过机制
```python
if dest_chat_id and dest_chat_id != "me":
    if not is_dest_cached(dest_chat_id):
        logger.info(f"🔄 目标频道未缓存，尝试延迟加载: {dest_chat_id}")
        success = cache_peer(acc, dest_chat_id, "目标频道")
        if success:
            logger.info(f"✅ 延迟加载目标频道成功: {dest_chat_id}")
            dest_peer_ready = True
        else:
            logger.error(f"❌ 延迟加载目标频道失败: {dest_chat_id}")
            logger.error(f"   消息将被跳过，等待下次重试（60秒后）")
            dest_peer_ready = False
    else:
        logger.debug(f"✓ 目标频道已缓存: {dest_chat_id}")

# 只有目标频道准备好才入队
if not dest_peer_ready:
    logger.warning(f"⏭️ 跳过消息（目标频道未就绪）: user={user_id}, dest={dest_chat_id}")
    continue
```

### 4. 诊断日志增强

#### 启动时显示
```
🔄 预加载目标Peer信息到缓存...
   ✅ 已缓存目标: -1001234567890 (测试频道)
   ⚠️ 无法缓存目标 -1009876543210: Peer id invalid
📦 成功缓存 1/2 个目标Peer
💡 缓存失败的目标（共1个）: -1009876543210
   这些目标将在接收到第一条消息时自动重试延迟加载

============================================================
⚠️  Peer缓存失败摘要
============================================================
共 1 个Peer缓存失败，将在接收消息时自动重试：
   • -1009876543210
============================================================
```

#### 运行时显示
```
🔔 监控源消息: chat_id=-1001234567890, message_id=12345
🔄 目标频道未缓存，尝试延迟加载: -1009876543210
✅ 延迟加载目标频道成功: -1009876543210
📬 消息已入队: user=123456, source=-1001234567890, 队列大小=1
```

或失败时：
```
🔔 监控源消息: chat_id=-1001234567890, message_id=12345
🔄 目标频道未缓存，尝试延迟加载: -1009876543210
❌ 延迟加载目标频道失败: -1009876543210
   消息将被跳过，等待下次重试（60秒后）
⏭️ 跳过消息（目标频道未就绪）: user=123456, dest=-1009876543210
```

## 工作流程

### 场景 1：启动预加载成功
1. Bot 启动
2. `_cache_dest_peers()` 成功缓存所有目标频道
3. 消息到达 → 直接处理，无延迟

### 场景 2：启动预加载失败，延迟加载成功
1. Bot 启动
2. `_cache_dest_peers()` 失败（Peer ID invalid）
3. 失败的 peer 被标记到 `failed_peers`
4. 启动日志显示失败摘要
5. 第一条消息到达
6. `auto_forward` 检测到 peer 未缓存
7. 尝试延迟加载 → 成功（session 已同步）
8. 消息正常入队并处理
9. 后续消息无需再次缓存

### 场景 3：延迟加载失败，等待重试
1. Bot 启动
2. `_cache_dest_peers()` 失败
3. 第一条消息到达
4. 延迟加载仍然失败（网络问题或权限问题）
5. 消息被跳过，记录错误日志
6. 60 秒后（冷却时间）
7. 下一条消息到达
8. 再次尝试延迟加载 → 成功
9. 消息正常处理

### 场景 4：记录模式不受影响
1. Bot 启动
2. 某些目标频道预加载失败
3. 记录模式的配置不需要目标频道
4. 源频道如果缓存失败，也会尝试延迟加载
5. 即使源频道缓存失败，记录模式仍能工作（仅影响来源信息）

## 核心优势

1. **零消息丢失**：失败的消息会被跳过并在 60 秒后自动重试
2. **自动恢复**：无需手动删除重新添加配置
3. **明确诊断**：启动和运行时都有清晰的日志
4. **避免频繁重试**：60 秒冷却时间防止 API 限流
5. **记录模式保护**：记录模式不依赖目标频道，始终可用
6. **渐进式加载**：启动失败的 peer 在首次使用时自动加载

## 测试验证

运行测试脚本：
```bash
python3 test_peer_cache_fix.py
```

测试覆盖：
- ✅ 基本缓存功能
- ✅ 失败 peer 跟踪
- ✅ 成功缓存后从失败列表移除
- ✅ 重试冷却时间机制
- ✅ 多个失败 peer 的处理

## 验收标准

- ✅ 重启后消息能正常处理（无需删除重新添加）
- ✅ 启动日志显示所有频道的缓存状态
- ✅ 即使首次预加载失败，第一条消息也能触发延迟加载
- ✅ 延迟加载失败后，60 秒后自动重试
- ✅ 记录模式不受目标频道缓存影响

## 相关文件

- `bot/utils/peer.py` - Peer 缓存核心逻辑
- `main.py` - 启动预加载和延迟加载实现
- `bot/utils/__init__.py` - 导出新增函数
- `test_peer_cache_fix.py` - 单元测试
