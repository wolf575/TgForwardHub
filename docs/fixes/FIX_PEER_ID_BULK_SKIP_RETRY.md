# Fix: Peer ID Invalid Errors in Bulk Recording

## Problem Summary

When recording 10+ messages in batch mode, many messages failed due to `Peer id invalid` errors:
- Queue stats showed: completed=3, failed=5, retry=15
- Only first 3 messages were recorded to database
- Subsequent messages encountered `ValueError: Peer id invalid: -1002529437122`
- Messages were retried 15 times unnecessarily
- No new notes appeared in web interface

## Root Causes

1. **Unrecoverable errors triggered retries**: Invalid Peer ID errors are permanent and should not be retried
2. **Error context was lost**: When `_execute_with_flood_retry` returned False, calling code raised generic Exception, losing the "Peer id invalid" context
3. **No distinction between error types**: Recoverable errors (FloodWait) and unrecoverable errors (invalid Peer ID) were treated the same

## Solution Implemented

### 1. Created UnrecoverableError Exception

```python
class UnrecoverableError(Exception):
    """Exception for unrecoverable errors that should not be retried"""
    pass
```

This exception is used to signal errors that should not trigger retries.

### 2. Updated _execute_with_flood_retry

Changed from returning True/False to raising exceptions:

**Before:**
- Returned False for "Peer id invalid" errors
- Calling code couldn't distinguish why it failed

**After:**
- Raises `UnrecoverableError` for:
  - Peer ID invalid errors
  - ID not found errors
  - Timeout errors
  - FloodWait retry limit exceeded
- Still raises original exceptions for recoverable errors

### 3. Simplified Operation Calls

**Before:**
```python
success = self._execute_with_flood_retry("转发消息", lambda: acc.forward_messages(...))
if success:
    logger.info("✅ Success")
    time.sleep(0.5)
else:
    raise Exception("转发消息失败")  # Lost error context!
```

**After:**
```python
self._execute_with_flood_retry("转发消息", lambda: acc.forward_messages(...))
logger.info("✅ Success")
time.sleep(0.5)
# UnrecoverableError bubbles up and is caught at top level
```

### 4. Enhanced process_message Return Values

Changed from bool to string for better tracking:

**Before:**
- `True`: Success OR skip (couldn't distinguish)
- `False`: Retry

**After:**
- `"success"`: Message processed successfully
- `"skip"`: Message skipped (filters or unrecoverable errors)
- `"retry"`: Message failed but can be retried

### 5. Updated Worker Loop

Added tracking for skipped messages:

```python
if result == "success":
    self.processed_count += 1
elif result == "skip":
    self.skipped_count += 1  # NEW: Track skipped messages
elif result == "retry":
    # Retry logic with exponential backoff
```

### 6. Improved Logging

**Statistics now show:**
```
📊 队列统计: 待处理=0, 已完成=10, 跳过=3, 失败=0, 重试=0
```

**Clear distinction:**
- ✅ 消息处理成功 (success)
- ⏭️ 消息已跳过 (skip - unrecoverable error or filter)
- ⚠️ 消息处理失败（不可恢复），跳过: Invalid Peer ID
- 🔄 消息已重新入队 (retry)

## Changes Made

1. **main.py line 42-44**: Added `UnrecoverableError` exception class
2. **main.py line 70**: Added `skipped_count` tracking
3. **main.py line 93**: Updated periodic stats logging to include skipped count
4. **main.py line 99**: Updated per-message logging to include skipped count
5. **main.py lines 160-207**: Refactored `_execute_with_flood_retry` to raise exceptions
6. **main.py lines 209-215**: Updated `process_message` return type to string
7. **main.py lines 243, 249, 263, 277**: Changed filter returns to `"skip"`
8. **main.py lines 462-468**: Simplified extract mode send operation
9. **main.py lines 480-512**: Simplified forward operations with UnrecoverableError propagation
10. **main.py lines 516-541**: Simplified copy operations with UnrecoverableError propagation
11. **main.py lines 690, 695, 701, 704, 707**: Updated return values in process_message
12. **main.py lines 102-124**: Updated worker loop to handle new return values

## Benefits

1. **No wasted retries**: Invalid Peer ID errors are immediately skipped instead of retried 15 times
2. **Clear error distinction**: Unrecoverable errors are clearly separated from retry-able errors
3. **Better monitoring**: Skipped messages are tracked separately from failures
4. **Accurate statistics**: Can see exactly how many messages succeeded, were skipped, or failed
5. **Continued processing**: One invalid Peer ID doesn't stop the entire batch
6. **Cleaner code**: Exception-based flow is more idiomatic than return value checking

## Expected Behavior

### Before Fix
```
📊 队列统计: 待处理=0, 已完成=3, 失败=5, 重试=15
- 3 messages recorded
- 5 messages failed after multiple retries
- 15 total retry attempts wasted
```

### After Fix
```
📊 队列统计: 待处理=0, 已完成=10, 跳过=2, 失败=0, 重试=0
- 10 messages recorded successfully
- 2 messages skipped (invalid Peer ID)
- 0 wasted retries
```

## Testing

To verify the fix:

1. Send 10+ messages to a monitored channel
2. Check queue statistics in logs
3. Verify all valid messages are recorded (skipped=0 or low)
4. Check web interface for new notes
5. Confirm no excessive retry attempts for invalid Peer IDs

## Related Files

- `main.py`: All changes made here
- `MESSAGE_QUEUE_SYSTEM.md`: Queue system documentation (may need update)
- `FLOODWAIT_HANDLING.md`: FloodWait handling documentation (may need update)
