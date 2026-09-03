# Quick Reference: Peer Cache Fix

## 问题
重启后配置存在但消息无法处理（Peer id invalid）

## 解决方案
实现了启动预加载 + 延迟加载 + 自动重试机制

## 核心机制

### 1. 启动预加载
- 启动时尝试缓存所有配置的 peer
- 失败的 peer 记录到 `failed_peers`
- 启动日志显示缓存状态

### 2. 延迟加载
- 消息到达时，检测 peer 是否已缓存
- 未缓存则立即尝试加载
- 成功：消息入队处理
- 失败：跳过消息，等待重试

### 3. 自动重试
- 失败的 peer 有 60 秒冷却时间
- 冷却后自动重试
- 成功后从失败列表移除

## 关键函数

### bot/utils/peer.py
```python
# 标记 peer 缓存失败
mark_peer_failed(peer_id)

# 检查是否可以重试
should_retry_peer(peer_id) -> bool

# 获取失败的 peer 列表
get_failed_peers() -> Dict[str, float]

# 缓存 peer（带重试逻辑）
cache_peer(client, peer_id, peer_type, force=False) -> bool
```

## 日志关键字

### 启动时
```
🔄 预加载目标Peer信息到缓存...
✅ 已缓存目标: <peer_id>
⚠️ 无法缓存目标 <peer_id>: <error>
📦 成功缓存 X/Y 个目标Peer
⚠️  Peer缓存失败摘要
```

### 运行时
```
🔄 目标频道未缓存，尝试延迟加载: <peer_id>
✅ 延迟加载目标频道成功: <peer_id>
❌ 延迟加载目标频道失败: <peer_id>
⏭️ 跳过消息（目标频道未就绪）
```

## 配置

### 重试冷却时间
```python
# bot/utils/peer.py
RETRY_COOLDOWN = 60  # 秒
```

## 验证

### 运行测试
```bash
# 单元测试
python3 test_peer_cache_fix.py

# 综合测试
python3 test_refactoring.py
```

### 检查日志
```bash
# 启动时检查
grep "Peer缓存失败摘要" <log_file>

# 运行时检查
grep "延迟加载" <log_file>
```

## 常见场景

### 场景 1：正常启动
✅ 所有 peer 预加载成功 → 消息直接处理

### 场景 2：启动失败，延迟加载成功
⚠️ 预加载失败 → 📋 记录到 failed_peers → 🔄 第一条消息触发延迟加载 → ✅ 成功 → 正常处理

### 场景 3：延迟加载也失败
⚠️ 预加载失败 → 🔄 延迟加载失败 → ⏭️ 跳过消息 → ⏰ 等待 60 秒 → 🔄 下次消息重试

### 场景 4：记录模式
✅ 记录模式不需要目标频道，始终可用

## 优势
- ✅ 零配置：自动处理
- ✅ 零消息丢失：失败会重试
- ✅ 清晰日志：问题一目了然
- ✅ 智能重试：避免 API 限流
- ✅ 向后兼容：不影响现有功能

## 相关文件
- `bot/utils/peer.py` - 核心实现
- `main.py` - 启动预加载和延迟加载
- `PEER_CACHE_FIX.md` - 详细文档
- `CHANGELOG_PEER_CACHE_FIX.md` - 完整变更记录
