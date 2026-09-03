# 更新说明 - Update Notes

## 最新更新 (Latest Update)

### 版本信息
- 分支: `feat-kwlist-add-preserve-forward-source-remove-forward-keyword-info`
- 更新时间: 2024

---

## 主要变更 (Major Changes)

### 1. ✅ 新增：保留转发来源选项

**功能描述：**
用户现在可以选择在自动转发消息时是否保留原始来源信息。

**使用方式：**
```bash
# 保留转发来源
/watch add @source @dest preserve_source:true

# 不保留（默认）
/watch add @source @dest
```

**行为差异：**
- `preserve_source:true` → 消息显示 "Forwarded from [原频道]"
- `preserve_source:false` → 消息不显示来源（默认）

---

### 2. ✅ 移除：关键词匹配信息显示

**功能描述：**
取消在转发消息中自动添加 `🔍 匹配关键词: ...` 的信息显示。

**影响：**
- ❌ 不再显示：`🔍 匹配关键词: 重要, 紧急`
- ✅ 保留功能：关键词白名单和黑名单过滤仍然正常工作
- ✅ 转发的消息：保持原始内容，更加简洁

---

## 配置数据结构 (Configuration Structure)

```json
{
  "user_id": {
    "source_chat_id": {
      "dest": "destination_chat_id",
      "whitelist": ["keyword1", "keyword2"],
      "blacklist": ["keyword3", "keyword4"],
      "preserve_forward_source": false
    }
  }
}
```

**新增字段：**
- `preserve_forward_source` (boolean): 是否保留转发来源，默认值 `false`

---

## 命令参考 (Command Reference)

### /watch add

**完整语法：**
```
/watch add <来源> <目标> [whitelist:关键词] [blacklist:关键词] [preserve_source:true/false]
```

**参数说明：**
| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| 来源 | ✅ | 来源频道 | `@channel` 或 ID |
| 目标 | ✅ | 目标位置 | `@dest`, ID, 或 `me` |
| whitelist | ❌ | 白名单关键词 | `whitelist:重要,紧急` |
| blacklist | ❌ | 黑名单关键词 | `blacklist:广告,垃圾` |
| preserve_source | ❌ | 保留来源 | `preserve_source:true` |

**示例命令：**
```bash
# 基本监控
/watch add @news_channel me

# 白名单过滤
/watch add @news_channel me whitelist:突发,重要

# 黑名单过滤
/watch add @content_channel me blacklist:广告

# 保留转发来源
/watch add @tech_channel me preserve_source:true

# 组合使用
/watch add @news me whitelist:科技 blacklist:娱乐 preserve_source:true
```

---

## 向后兼容性 (Backward Compatibility)

✅ **完全兼容**
- 旧配置格式继续工作
- 现有监控任务无需修改
- `preserve_forward_source` 自动使用默认值 `false`
- 关键词过滤功能完全保留

❌ **唯一变更**
- 转发的消息不再显示关键词匹配信息

---

## 测试验证 (Testing)

运行测试命令：
```bash
python3 test_changes.py
python3 test_feature.py
```

所有测试均已通过 ✅

---

## 相关文档 (Related Documentation)

- **详细变更说明**: `FEATURE_CHANGES_SUMMARY.md`
- **功能更新文档**: `FEATURE_UPDATE.md`
- **实现注意事项**: `IMPLEMENTATION_NOTES.md`
- **变更日志**: `CHANGES.md`

---

## 快速上手 (Quick Start)

### 场景 1: 新闻聚合（保留来源）
```bash
/watch add @news_channel @my_collection whitelist:突发 preserve_source:true
```
→ 只转发突发新闻，并显示来源频道

### 场景 2: 内容过滤（不保留来源）
```bash
/watch add @content_channel me blacklist:广告,推广
```
→ 过滤广告内容，转发的消息不显示来源

### 场景 3: 精准筛选
```bash
/watch add @tech_channel me whitelist:Python,AI blacklist:招聘 preserve_source:true
```
→ 只转发Python/AI相关技术内容，排除招聘信息，保留来源

---

## 支持 (Support)

如有问题，请使用 `/help` 命令查看完整帮助文档。

---

**更新完成！** 🎉
