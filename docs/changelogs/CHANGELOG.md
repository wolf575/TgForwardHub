# 更新日志 / Changelog

## [v2.0.0] - 2024

### 新增功能 / Added

#### 1. 正则表达式过滤 (Regex Filtering)
- ✨ 添加正则表达式白名单功能
- ✨ 添加正则表达式黑名单功能
- ✨ 支持完整的 Python re 模块语法
- ✨ 添加正则表达式验证，防止无效表达式

#### 2. 提取模式 (Extract Mode)
- ✨ 新增提取模式 - 使用正则表达式从消息中提取特定内容
- ✨ 支持多个提取模式
- ✨ 自动去重提取结果
- ✨ 提取的内容以独立消息发送

#### 3. 监控任务编辑 (Monitor Editing)
- ✨ 监控列表改为可点击的按钮界面
- ✨ 点击任务查看详细配置
- ✨ 支持编辑所有过滤规则（关键词、正则）
- ✨ 支持切换转发模式（完整/提取）
- ✨ 支持切换保留来源选项
- ✨ 支持清空单个规则
- ✨ 支持删除监控任务

#### 4. UI/UX 改进
- 🎨 优化监控列表显示，使用按钮代替纯文本
- 🎨 添加更详细的任务信息显示
- 🎨 改进添加监控的流程，支持设置所有新功能
- 🎨 优化错误提示信息
- 🎨 添加正则表达式示例和提示

### 改进 / Improved

- 🔧 重构过滤逻辑，支持多种过滤规则组合
- 🔧 优化配置文件结构，添加新字段
- 🔧 改进用户状态管理
- 🔧 增强错误处理和验证
- 📝 更新帮助文档，添加新功能说明
- 📝 添加 FEATURES.md 详细功能说明文档

### 技术更新 / Technical

- 📦 添加 re 模块用于正则表达式处理
- 📦 扩展 watch_config 数据结构
- 📦 新增字段：whitelist_regex, blacklist_regex, forward_mode, extract_patterns
- 🧪 添加 test_regex_extract.py 测试脚本
- 📄 添加 watch_config_example.json 示例配置

### 向后兼容 / Backward Compatibility

- ✅ 完全兼容旧版配置文件
- ✅ 缺失的新字段自动使用默认值
- ✅ 保持所有原有功能不变

---

## [v1.0.0] - 之前

### 核心功能
- 📥 消息转发（链接方式）
- 👁 频道/群组监控
- 🔍 关键词过滤（白名单/黑名单）
- 📤 保留转发来源选项
- 🎨 内联键盘界面
- 📦 批量下载
- 🔒 私有频道支持
- 🌐 中文界面

---

## 配置文件变化 / Config Changes

### v2.0.0 配置结构
```json
{
  "user_id": {
    "source_chat_id": {
      "dest": "dest_chat_id",
      "whitelist": [],
      "blacklist": [],
      "whitelist_regex": [],          // NEW
      "blacklist_regex": [],          // NEW
      "preserve_forward_source": false,
      "forward_mode": "full",         // NEW: "full" or "extract"
      "extract_patterns": []          // NEW
    }
  }
}
```

### v1.0.0 配置结构（仍然支持）
```json
{
  "user_id": {
    "source_chat_id": {
      "dest": "dest_chat_id",
      "whitelist": [],
      "blacklist": [],
      "preserve_forward_source": false
    }
  }
}
```

---

## 升级说明 / Upgrade Guide

### 从 v1.0.0 升级到 v2.0.0

1. **无需手动操作** - 配置文件会自动兼容
2. **新功能** - 使用监控编辑功能可以为现有任务添加新规则
3. **测试建议** - 建议在正式使用前测试正则表达式和提取模式

### 注意事项
- 现有监控任务会继续正常工作
- 新添加的字段使用默认值
- 可以随时编辑现有任务添加新功能

---

## 已知问题 / Known Issues

- 提取模式仅支持文本提取，不支持媒体文件
- 复杂的正则表达式可能影响性能
- 提取模式忽略 preserve_forward_source 设置

---

## 计划功能 / Planned Features

- [ ] 提取模式支持捕获组命名
- [ ] 提取结果格式化选项
- [ ] 批量编辑监控任务
- [ ] 导入/导出配置
- [ ] 统计和日志功能

---

## 贡献者 / Contributors

感谢所有为此项目做出贡献的人！

---

## 支持 / Support

- 📖 文档: [FEATURES.md](FEATURES.md)
- 🐛 问题反馈: GitHub Issues
- 💬 讨论: GitHub Discussions
