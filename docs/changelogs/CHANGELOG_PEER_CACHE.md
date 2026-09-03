# Changelog - Peer Cache Initialization Fix

## 变更日期
2025-11-16

## 变更类型
Bug Fix - 修复重启后监控配置不生效问题

## 问题描述
- 重启Bot后，已配置的监控任务不生效
- 消息被跳过，日志显示 "Peer id invalid" 错误
- 删除后重新添加监控可以临时解决，但重启后又失效

## 根本原因
Pyrogram需要通过 `get_chat(peer_id)` 将频道信息存入内部SQLite session数据库。仅配置频道ID是不够的，必须主动触发获取频道信息的操作。

## 解决方案

### 1. 新增函数：`initialize_peer_cache_on_startup(acc)`
**文件**：`main.py` (第388-479行)

**功能**：
- 从 `watch_config.json` 加载所有监控配置
- 收集所有源频道和目标频道的ID
- 对每个频道调用 `acc.get_chat(peer_id)` 强制初始化
- 记录每个频道的初始化状态（成功/失败）
- 标记成功的peer为已缓存（`mark_dest_cached()`）
- 失败的peer标记为需要重试（`mark_peer_failed()`）
- 输出详细的初始化日志和结果摘要

**代码特点**：
```python
# 1. 收集所有peer ID
for user_id, watches in watch_config.items():
    for watch_key, watch_data in watches.items():
        if isinstance(watch_data, dict):
            source_id = watch_data.get("source")
            dest_id = watch_data.get("dest")
            # 添加到 all_peers 集合

# 2. 强制初始化
for peer_id in sorted(all_peers):
    chat = acc.get_chat(peer_id)  # ← 关键操作
    mark_dest_cached(str(peer_id))  # 标记为已缓存
```

### 2. 集成到启动流程：修改 `print_startup_config()`
**文件**：`main.py` (第515-551行)

**变更**：
- 移除了旧的 `_cache_channels()` 和 `_cache_dest_peers()` 调用
- 在打印watch任务后，调用新的 `initialize_peer_cache_on_startup(acc)`
- 简化了启动流程，减少重复代码

**调用顺序**：
```
1. reload_monitored_sources()    # 重新加载监控源配置
2. 打印启动信息和watch任务
3. initialize_peer_cache_on_startup(acc)  # ← 新增
4. 打印"机器人已就绪"
```

## 代码变更统计

### 新增代码
- **函数**：`initialize_peer_cache_on_startup()` (92行)
- **文档**：`PEER_CACHE_INITIALIZATION.md` (完整技术文档)

### 修改代码
- **函数**：`print_startup_config()` 
  - 删除：约30行（旧的缓存逻辑）
  - 新增：3行（调用新函数）
  - 净变化：-27行

### 总代码变化
- 新增：92行（新函数）
- 删除：27行（简化的启动逻辑）
- 净增加：65行

## 功能改进

### 1. 更可靠的初始化
- ✅ 强制初始化所有配置的peer
- ✅ 启动时立即执行，不依赖延迟加载
- ✅ 确保session数据库包含所有必要信息

### 2. 更清晰的日志
```
============================================================
⚡ 启动时初始化 5 个Peer缓存...
============================================================
   ✅ -1001234567890: 测试频道A
   ✅ -1009876543210: 测试频道B
   ✅ 987654321: John Doe 🤖
   ⚠️ -1001111111111: Peer id invalid
   ✅ -1002222222222: 私有群组
============================================================
✅ Peer缓存初始化完成: 4/5 成功
⚠️ 失败的Peer (共1个):
   - -1001111111111: Peer id invalid
💡 失败的Peer将在接收到第一条消息时自动重试延迟加载
============================================================
```

### 3. 更好的容错性
- ✅ 单个peer失败不影响其他peer
- ✅ 失败的peer记录时间戳，60秒后可重试
- ✅ 延迟加载机制作为后备方案
- ✅ 详细的错误信息便于排查问题

## 向后兼容性
- ✅ 完全兼容现有配置文件格式
- ✅ 不影响现有的延迟加载机制
- ✅ 不需要用户修改配置
- ✅ 平滑升级，无需数据迁移

## 测试建议

### 测试场景1：正常启动
1. 配置多个监控任务（包括forward和record模式）
2. 重启Bot
3. 检查启动日志，确认所有peer都显示 ✅
4. 发送测试消息，验证转发和记录功能正常

### 测试场景2：部分peer无效
1. 配置包含无效peer ID的监控任务
2. 重启Bot
3. 检查启动日志，确认：
   - 有效peer显示 ✅
   - 无效peer显示 ⚠️ 并记录错误信息
   - 显示失败peer的摘要
4. 有效peer的监控任务应正常工作

### 测试场景3：FloodWait限流
1. 配置大量监控任务（10+个频道）
2. 重启Bot
3. 检查启动日志，确认：
   - 遇到限流时显示 ⚠️ 和等待时间
   - 限流的peer被标记为失败
   - 其他peer继续正常初始化
4. 等待60秒后，限流的peer应通过延迟加载成功

### 测试场景4：无配置
1. 删除所有监控配置（空的watch_config.json）
2. 重启Bot
3. 检查启动日志，应显示："📭 没有配置的Peer需要初始化"
4. Bot应正常启动，可以手动添加监控任务

## 相关文件
- `main.py` - 主要修改
- `bot/utils/peer.py` - Peer缓存工具（已有代码，未修改）
- `config.py` - 配置加载（已有代码，未修改）

## 依赖关系
- Pyrogram >= 2.0
- Python >= 3.8
- 无新增依赖

## 性能影响
- **启动时间**：每个peer约增加0.1-0.5秒（取决于网络延迟）
- **内存占用**：无显著影响（peer信息已存在session数据库）
- **运行时性能**：提升（避免了延迟加载的RTT开销）

## 安全性
- ✅ 不引入新的安全风险
- ✅ 使用现有的认证机制
- ✅ 错误信息不泄露敏感数据
- ✅ 遵循Pyrogram的最佳实践

## 后续改进建议
1. 可以考虑添加初始化超时机制（避免单个peer耗时过长）
2. 可以考虑并行初始化（提高启动速度）
3. 可以考虑缓存peer信息到本地文件（减少网络请求）

## 作者
AI Assistant

## 审核状态
待审核
