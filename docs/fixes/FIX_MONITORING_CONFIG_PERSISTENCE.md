# 修复监控配置重启后失效的问题

## 问题描述

用户报告："修改完代码，重启机器人后，之前监控的配置不生效，要把监控删除重新添加才生效"

## 根本原因

1. **全局变量 `monitored_sources` 未同步更新**
   - `monitored_sources` 是一个全局集合，在Bot启动时通过 `build_monitored_sources()` 构建
   - 用于在 `auto_forward` 处理函数中快速过滤消息（第2846-2848行）
   - 当用户添加/删除监控任务时，配置文件被更新，但 `monitored_sources` 没有同步更新

2. **消息过滤逻辑的早期返回**
   ```python
   if source_chat_id not in monitored_sources:
       # Not in monitored list, skip silently
       return
   ```
   - 这个检查在加载 `watch_config` 之前执行
   - 如果新添加的source不在旧的 `monitored_sources` 中，消息会被直接跳过
   - 永远不会执行到后面加载配置的代码

3. **部分操作缺少reload调用**
   - 虽然添加和删除监控时有调用 `reload_monitored_sources()`
   - 但某些编辑操作（虽然不影响source列表）没有调用reload
   - 容易在未来的代码修改中引入bug

## 解决方案

### 1. 增强 `save_watch_config` 函数

**修改前：**
```python
def save_watch_config(config):
    with open(WATCH_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
```

**修改后：**
```python
def save_watch_config(config, auto_reload=True):
    """Save watch config to file and optionally reload monitored sources
    
    Args:
        config: Configuration dictionary to save
        auto_reload: If True, automatically reload monitored sources after save (default: True)
    """
    with open(WATCH_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
        f.flush()  # Flush Python buffers
        os.fsync(f.fileno())  # Ensure OS writes to disk
    
    # Automatically reload monitored sources to keep them in sync
    if auto_reload:
        reload_monitored_sources()
```

**优势：**
- 自动在保存配置后重新加载监控源列表
- 添加了 `f.flush()` 和 `os.fsync()` 确保配置立即写入磁盘
- 提供 `auto_reload` 参数以便在特殊情况下禁用自动reload
- 所有调用 `save_watch_config` 的地方自动获得reload功能

### 2. 移动辅助函数定义位置

将 `build_monitored_sources()` 和 `reload_monitored_sources()` 从文件末尾移到 `save_watch_config()` 之前，使得 `save_watch_config` 可以调用它们。

**新的函数定义顺序（第913-963行）：**
```python
def load_watch_config():
    # ... (unchanged)

def build_monitored_sources():
    """Build a set of all monitored source chat IDs from watch config"""
    # ... (moved from line 2782)

def reload_monitored_sources():
    """Reload the monitored sources set (call after config changes)"""
    # ... (moved from line 2801)

def save_watch_config(config, auto_reload=True):
    # ... (enhanced with auto-reload)
```

### 3. 移除冗余的显式reload调用

由于 `save_watch_config` 现在自动调用reload，移除了以下位置的重复调用：
- 第1466行：删除监控任务后
- 第2223行：添加转发任务后
- 第2286行：添加记录模式任务后

这些位置现在只需调用 `save_watch_config(watch_config)` 即可。

## 测试验证

创建了 `test_monitoring_config_fix.py` 验证修复：

1. **自动reload测试**：
   - 添加监控任务 → 验证 `monitored_sources` 自动更新
   - 模拟重启 → 验证配置正确加载
   - 添加第二个任务 → 验证增量更新
   - 删除任务 → 验证正确移除

2. **消息过滤测试**：
   - 验证监控源的消息能通过过滤
   - 验证非监控源的消息被正确过滤

**测试结果：** ✅ 所有测试通过

## 影响范围

- 所有调用 `save_watch_config()` 的地方现在会自动更新监控源列表
- 配置文件的写入更加可靠（增加了flush和fsync）
- 不会再出现"配置保存了但监控不生效"的问题
- 重启后配置始终正确加载

## 向后兼容性

- 完全向后兼容，不需要修改现有配置文件
- 所有现有的调用代码无需修改（默认 `auto_reload=True`）
- 如果未来需要批量更新配置，可以传入 `auto_reload=False` 然后手动调用一次reload

## 性能影响

- 每次保存配置时多调用一次 `build_monitored_sources()`
- 对于正常使用（偶尔添加/删除监控），性能影响可忽略
- 相比解决的问题（配置失效），这点性能开销完全可以接受

## 相关文件

- `main.py`: 主要修复代码
- `test_monitoring_config_fix.py`: 测试验证
- `test_config_persistence.py`: 配置持久化基础测试
