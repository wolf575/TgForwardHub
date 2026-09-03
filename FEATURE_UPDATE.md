# 功能更新说明

## 更新内容

### 1. 新增：保留转发来源选项

**需求：** 在监控转发功能中，增加一个选项让用户可以选择是否保留消息的原始转发来源信息。

**实现：**
- 在 `/watch add` 命令中新增 `preserve_source` 参数
- 配置数据结构中新增 `preserve_forward_source` 字段（默认值：false）
- 当设置为 `true` 时，使用 `forward_messages()` 方法保留原始转发来源
- 当设置为 `false` 时，使用 `copy_message()` 方法不保留转发来源

**使用方法：**
```bash
# 不保留转发来源（默认）
/watch add @source @dest

# 保留转发来源
/watch add @source @dest preserve_source:true

# 结合关键词过滤使用
/watch add @source me whitelist:重要 preserve_source:true
```

**技术细节：**
- `forward_messages()` - 会显示"Forwarded from"原始来源信息
- `copy_message()` - 不显示原始来源，看起来像是由转发者原创发送

### 2. 移除：关键词信息显示

**需求：** 取消在转发消息时自动添加的关键词匹配信息（`🔍 匹配关键词: ...`）。

**实现：**
- 完全移除了关键词信息的生成和显示逻辑
- 关键词过滤功能仍然正常工作（白名单/黑名单）
- 转发的消息将保持原始内容，不添加任何前缀信息

**变更前：**
转发的消息会在顶部显示：
```
🔍 匹配关键词: 重要, 紧急

[原始消息内容]
```

**变更后：**
转发的消息保持原始内容：
```
[原始消息内容]
```

## 修改的文件

### main.py

1. **help 命令更新（第 84-122 行）**
   - 更新了帮助文档，说明新的 `preserve_source` 参数
   - 移除了关于关键词信息显示的说明
   - 添加了新的使用示例

2. **watch list 命令更新（第 134-160 行）**
   - 显示 `preserve_forward_source` 选项的状态
   - 如果设置为 true，会显示"保留转发来源: 是"

3. **watch add 命令更新（第 162-231 行）**
   - 解析 `preserve_source:true/false` 参数
   - 将 `preserve_forward_source` 保存到配置中
   - 在成功消息中显示该选项的状态

4. **auto_forward 函数重构（第 493-540 行）**
   - 读取 `preserve_forward_source` 配置
   - 根据配置选择转发方式：
     - `preserve_forward_source=true` → 使用 `forward_messages()`
     - `preserve_forward_source=false` → 使用 `copy_message()`
   - 完全移除了关键词信息生成和显示的代码
   - 保持了关键词白名单和黑名单的过滤逻辑

## 数据结构变更

### 监控配置格式

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
- `preserve_forward_source` (boolean): 是否保留转发来源
  - `true`: 保留原始转发来源信息
  - `false`: 不保留（默认值）

## 向后兼容

- 旧的配置格式（简单字符串）仍然支持
- 没有 `preserve_forward_source` 字段的配置会自动使用默认值 `false`
- 关键词过滤功能保持不变，只是移除了显示部分

## 测试

已通过以下测试：
1. ✅ Python 语法编译检查
2. ✅ 配置数据结构读写测试
3. ✅ 向后兼容性测试
4. ✅ 默认值测试

## 迁移说明

**现有用户无需任何操作**：
- 现有的监控任务将继续工作
- `preserve_forward_source` 会自动使用默认值 `false`（不保留转发来源）
- 关键词过滤功能继续正常工作，只是不会再显示匹配的关键词信息

如果需要保留转发来源，请删除现有任务并使用新的 `preserve_source:true` 参数重新添加。
