# 启动时自动导入配置 - 更新日志

## 问题描述
机器人重启后，保存在 `watch_config.json` 中的监控配置不会自动生效，需要手动通过 Telegram 命令 `/add` 重新添加才能工作。

## 解决方案
实现了 `import_watch_config_on_startup()` 函数，该函数**复用手动添加的逻辑**，确保启动时的配置导入使用与手动添加完全相同的代码路径。

## 主要变更

### 新增函数：`import_watch_config_on_startup(acc)`
**位置**: `main.py` 第 515-614 行

**功能**:
1. 遍历 `watch_config.json` 中的所有监控配置
2. 对每个配置的源和目标频道，调用 `acc.get_chat()` 进行初始化
3. 这与手动添加时的 `handle_add_source()` 和 `handle_add_dest()` 使用相同的逻辑
4. 标记成功的 peer 为已缓存，失败的 peer 标记为延迟加载
5. 提供详细的日志输出，显示每个配置的导入状态

**关键设计**:
- ✅ 简单明了：直接调用 `acc.get_chat()`，无复杂重试逻辑
- ✅ 代码复用：与手动添加使用完全相同的代码路径
- ✅ 容错机制：失败的 peer 会在首次接收消息时自动重试（现有的延迟加载机制）
- ✅ 详细日志：清晰显示每个配置的导入进度和结果

### 修改：`print_startup_config()` 函数
**位置**: `main.py` 第 687 行

**变更**:
```python
# 旧代码（复杂的重试逻辑）
initialize_peer_cache_on_startup_with_retry(acc, max_retries=3)

# 新代码（简单的导入逻辑）
import_watch_config_on_startup(acc)
```

## 启动流程

1. `acc.start()` - 启动用户客户端
2. `reload_monitored_sources()` - 从磁盘重新加载监控源列表
3. **等待 2 秒** - 确保 Session 完全建立
4. `import_watch_config_on_startup(acc)` - 导入所有配置（新增）
   - 遍历所有用户的监控配置
   - 对每个源频道调用 `acc.get_chat(source_id)`
   - 对每个目标频道调用 `acc.get_chat(dest_id)`
   - 使用与手动添加完全相同的逻辑
5. 机器人进入就绪状态

## 日志示例

```
============================================================
🔄 开始导入监控配置...
============================================================
📋 找到 2 个监控配置

👤 用户 123456 的配置:
   ✅ 源频道: My Channel (-1001234567890)
   ✅ 目标频道: Destination Channel (-1009876543210)
   📤 模式: 转发模式
   ✅ 源频道: Another Channel (-1001111111111)
   📝 模式: 记录模式

============================================================
✅ 配置导入完成: 2/2 成功
============================================================
```

## 优势

1. **简单可靠**: 复用已验证的手动添加逻辑，无需维护复杂的重试机制
2. **易于维护**: 代码路径统一，未来修改手动添加逻辑会自动应用到启动导入
3. **清晰日志**: 详细的日志输出，便于排查问题
4. **容错机制**: 失败的 peer 会在运行时自动重试，不影响其他配置
5. **向后兼容**: 保留了旧的 `initialize_peer_cache_on_startup_with_retry()` 函数，不影响其他代码

## 测试建议

1. **正常启动测试**:
   - 配置一些监控任务
   - 重启机器人
   - 验证配置自动生效，无需手动重新添加

2. **失败恢复测试**:
   - 配置一个无法访问的频道
   - 重启机器人
   - 验证其他配置正常导入
   - 验证失败的配置会在延迟加载时重试

3. **空配置测试**:
   - 清空 `watch_config.json`
   - 重启机器人
   - 验证正常启动，显示"没有监控配置需要导入"

## 相关文件

- `main.py`: 新增 `import_watch_config_on_startup()` 函数，修改 `print_startup_config()`
- `bot/handlers/watch_setup.py`: 手动添加逻辑的参考实现（`handle_add_source`, `handle_add_dest`）
- `bot/utils/peer.py`: peer 缓存标记函数（`mark_dest_cached`, `mark_peer_failed`）
- `config.py`: 配置加载和监控源管理（`load_watch_config`, `reload_monitored_sources`）

## 验收标准

- ✅ 机器人启动时自动导入 watch_config.json 中的所有监控配置
- ✅ 每个配置都通过相同的手动添加逻辑进行初始化（包括 Peer 缓存等）
- ✅ 启动日志显示导入配置的数量和结果
- ✅ 重启后无需手动添加配置，监控立即生效
- ✅ 代码简洁，易于维护
