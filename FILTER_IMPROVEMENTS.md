# Filter Whitelist/Blacklist Interaction Improvements

## Summary of Changes

This document describes the improvements made to the whitelist/blacklist filtering system to address interaction flow and filtering logic issues.

## Issues Fixed

### Issue 1: Interaction Flow Defects 🔴

**Problem:**
- After setting a filter rule, the menu would loop back without showing what was set
- Users had to remember what they configured
- No clear way to finish setup
- Risk of accidentally clicking "不设置过滤" and clearing all rules

**Solution:**
- Filter options menu now displays all currently-set rules
- Added "✅ 完成设置" (Complete Setup) button
- Replaced "⏭ 不设置过滤" with "🗑️ 清空规则" (Clear Rules) button
- Users can now see their configuration and make informed decisions

### Issue 2: Filter Menu Lacks Information 🔴

**Problem:**
- Menu didn't show which filters were already configured
- No completion button
- "不设置" button was ambiguous

**Solution:**
- Menu now shows a "📋 已设置的规则" section displaying:
  - 🟢 关键词白名单 (if set)
  - 🔴 关键词黑名单 (if set)
  - 🟢 正则白名单 (if set)
  - 🔴 正则黑名单 (if set)
- Added clear action buttons:
  - ✅ 完成设置 - saves and proceeds
  - 🗑️ 清空规则 - clears all filters
  - ❌ 取消 - cancels setup

### Issue 3: Filter Logic Priority 🟡

**Problem:**
- Original order: whitelist → blacklist → regex whitelist → regex blacklist
- Blacklist should have higher priority (it's a "deny" rule)

**Solution:**
- Reordered filter checks to prioritize blacklist:
  1. Check keyword blacklist (deny first)
  2. Check regex blacklist (deny first)
  3. Check keyword whitelist (allow)
  4. Check regex whitelist (allow)
- This follows security best practices: "deny by default" takes precedence

## Technical Changes

### 1. Updated Filter Logic (lines 268-317)

```python
# Priority: blacklist > whitelist (blacklist has higher priority)

# Step 1: Check blacklists first (higher priority)
if blacklist:
    for keyword in blacklist:
        if keyword.lower() in message_text.lower():
            return "skip"  # Filtered out by blacklist

if blacklist_regex:
    for pattern in blacklist_regex:
        try:
            if re.search(pattern, message_text):
                return "skip"  # Filtered out by regex blacklist
        except re.error as e:
            logger.warning(f"⚠️ 正则黑名单表达式错误 '{pattern}': {e}")

# Step 2: Check whitelists
if whitelist:
    matched = False
    for keyword in whitelist:
        if keyword.lower() in message_text.lower():
            matched = True
            break
    if not matched:
        return "skip"

if whitelist_regex:
    matched = False
    for pattern in whitelist_regex:
        try:
            if re.search(pattern, message_text):
                matched = True
                break
        except re.error as e:
            logger.warning(f"⚠️ 正则白名单表达式错误 '{pattern}': {e}")
    if not matched:
        return "skip"
```

### 2. Enhanced Filter Options Menu

**Function: `show_filter_options()` (lines 1852-1908)**

New features:
- Reads current filter settings from `user_states[user_id]`
- Builds filter status display showing all configured rules
- Updated keyboard with new action buttons
- Better explanatory text

**Function: `show_filter_options_single()` (lines 1910-1968)**

Similar enhancements for record mode:
- Shows current filter configuration
- Same new button layout
- Consistent user experience

### 3. New Callback Handlers (lines 1400-1452)

Added handlers for:

**`filter_done`**: 
- Saves filter rules
- Proceeds to preserve_source_options
- Shows success message

**`filter_done_single`**: 
- Saves filter rules for record mode
- Completes watch setup
- Shows success message

**`clear_filters`**: 
- Clears all filter arrays in user_states
- Refreshes menu to show empty state
- Confirms with callback answer

**`clear_filters_single`**: 
- Same as clear_filters but for record mode
- Refreshes single mode menu

### 4. Updated Text Input Handlers (lines 2230-2294)

Modified filter setting handlers to:
- Show confirmation message separately
- Display "⏳ 继续设置..." message
- Call appropriate filter menu (normal or single)
- Menu now displays newly-set filters

### 5. Enhanced Skip Handlers (lines 1488-1558)

Updated skip button handlers to:
- Check if in record_mode
- Call appropriate menu function
- Maintain consistency across both modes

## User Experience Improvements

### Before:
1. User sets whitelist → loops back to menu (no indication of what was set)
2. User confused, might click "不设置" thinking it means "done"
3. All filters cleared accidentally ❌

### After:
1. User sets whitelist → confirmation message
2. Menu updates showing: "🟢 关键词白名单: `重要, 紧急`"
3. User can see what's configured and choose to:
   - Add more filters
   - Clear filters (明确的选项)
   - Complete setup ✅

## Testing Scenarios

### Test 1: Set Multiple Filters
```
1. Start /watch
2. Choose source and destination
3. Click "🟢 关键词白名单"
4. Enter: 重要,紧急
5. ✅ Menu should show: 🟢 关键词白名单: `重要, 紧急`
6. Click "🔴 关键词黑名单"
7. Enter: 广告,spam
8. ✅ Menu should show both rules
9. Click "✅ 完成设置"
10. ✅ Should proceed to next step
```

### Test 2: Clear Filters
```
1. Set some filters
2. Menu shows configured rules
3. Click "🗑️ 清空规则"
4. ✅ Menu should show: 📋 **暂未设置过滤规则**
5. ✅ Filters should be empty arrays
```

### Test 3: Filter Priority
```
Setup: whitelist=["重要"], blacklist=["广告"]

Message: "重要广告"
✅ Should SKIP (blacklist matches first)

Message: "重要通知"
✅ Should PASS (blacklist doesn't match, whitelist matches)

Message: "普通消息"
✅ Should SKIP (whitelist doesn't match)

Message: "广告"
✅ Should SKIP (blacklist matches)
```

## Benefits

1. ✅ **Better User Experience**: Users always know what's configured
2. ✅ **Prevents Accidents**: Clear "清空规则" vs "完成设置" buttons
3. ✅ **Logical Priority**: Blacklist (deny) takes precedence over whitelist (allow)
4. ✅ **Better Logging**: Improved debug messages for filter matching
5. ✅ **Consistent**: Works the same in both forward and record modes
6. ✅ **Robust Error Handling**: Catches and logs regex errors without breaking

## Backwards Compatibility

All changes are backwards compatible:
- Existing watch configurations continue to work
- Filter logic still supports all four filter types
- Old filters are evaluated with new priority (improvement, not breaking change)
- User state structure unchanged

## Files Modified

- `main.py`:
  - Lines 268-317: Filter logic reordering
  - Lines 1400-1452: New callback handlers
  - Lines 1488-1558: Enhanced skip handlers
  - Lines 1852-1908: Updated show_filter_options()
  - Lines 1910-1968: Updated show_filter_options_single()
  - Lines 2230-2294: Updated text input handlers
