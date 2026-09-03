# FloodWait and Rate Limiting Implementation

## Overview

This document explains the FloodWait handling and rate limiting mechanisms implemented to fix batch forwarding issues when 10+ messages are sent simultaneously to a monitored channel.

## Problem

Previously, when 10+ messages were sent to a monitored channel:
- Only the first 2 messages were forwarded successfully
- The 3rd and subsequent messages failed with `[420 FLOOD_WAIT_X]` errors
- No retry mechanism existed to handle rate limiting
- Frequent `channels.GetFullChannel` API calls triggered Telegram's rate limits

## Solution

### 1. FloodWait Exception Handling

**Implementation**: `MessageWorker._execute_with_flood_retry()` method

**Features**:
- Catches `FloodWait` exceptions from Pyrogram
- Extracts wait time from `exception.value`
- Automatically sleeps for `wait_time + 1` seconds (extra 1 second for safety)
- Retries up to 3 times specifically for FloodWait errors
- Logs clear information about rate limits and retry attempts

**Usage Example**:
```python
success = self._execute_with_flood_retry(
    "转发消息",
    lambda: acc.forward_messages(dest_id, source_chat_id, message_id)
)
```

**Log Output**:
```
⏳ 转发消息: 遇到限流 FLOOD_WAIT, 需等待 11 秒
   将在 12 秒后重试 (FloodWait 重试 1/3)
```

### 2. Rate Limiting Between Operations

**Implementation**: 0.5 second delay after each successful forward/send operation

**Locations**:
- After sending extracted content
- After forwarding messages
- After copying messages
- After forwarding/copying media groups

**Purpose**: Prevents QPS (queries per second) spikes that trigger rate limits

**Code Example**:
```python
success = self._execute_with_flood_retry(...)
if success:
    logger.info(f"   ✅ 消息已转发")
    time.sleep(0.5)  # Rate limiting delay
```

### 3. Peer Caching

**Implementation**: Pre-cache channel information to reduce API calls

**Caching Points**:

1. **Startup Pre-caching** (`print_startup_config()`):
   - Caches all configured source channels at bot startup
   - Prevents "Peer id invalid" errors

2. **Message Reception** (`auto_forward` handler):
   - Caches source channel when message arrives
   - Caches destination channel before enqueueing message

3. **Reduces API Calls**:
   - Avoids repeated `channels.GetFullChannel` calls
   - Main source of rate limiting in batch scenarios

**Code Example**:
```python
# Pre-cache destination peer
if not record_mode and dest_chat_id and dest_chat_id != "me":
    try:
        acc.get_chat(int(dest_chat_id))
        logger.debug(f"   ✅ 目标频道已缓存: {dest_chat_id}")
    except Exception as e:
        logger.debug(f"   ⚠️ 无法缓存目标频道 {dest_chat_id}: {str(e)}")
```

### 4. Error Isolation

**Implementation**: Queue-based message processing with individual error handling

**Benefits**:
- Each message processed independently in the worker thread
- Single message failure doesn't stop processing of other messages
- Failed messages automatically retry with exponential backoff
- FloodWait errors handled separately from other errors

**Error Types**:

1. **FloodWait (420)**: Auto-retry with wait time from Telegram
2. **Peer ID Invalid**: Skip without retry (not recoverable)
3. **Other Exceptions**: Retry with exponential backoff (1s, 2s, 4s)

## Message Flow with Rate Limiting

```
1. Message arrives → auto_forward handler
2. Cache source channel (if needed)
3. Match watch tasks
4. Cache destination channel (if needed)
5. Enqueue message to queue
   ↓
6. Worker thread picks up message
7. Apply filters
8. Execute forward operation with FloodWait retry:
   a. Try operation
   b. If FloodWait → sleep wait_time + 1 second → retry (up to 3x)
   c. If success → sleep 0.5 seconds (rate limit)
   d. If other error → exponential backoff retry (up to 3x)
9. Next message (automatic 0.5s+ delay)
```

## Configuration

### Default Settings

- **Max FloodWait retries**: 3
- **Rate limit delay**: 0.5 seconds
- **Safety margin**: +1 second added to Telegram's wait time
- **Max general retries**: 3 (with exponential backoff)

### Adjustable Parameters

To modify retry behavior, edit these in `MessageWorker`:

```python
class MessageWorker:
    def __init__(self, message_queue: queue.Queue, max_retries: int = 3):
        self.max_retries = max_retries  # General retry limit
    
    def _execute_with_flood_retry(self, operation_name: str, operation_func, 
                                   max_flood_retries: int = 3):
        # max_flood_retries: FloodWait-specific retry limit
```

To modify rate limit delay, change the `time.sleep(0.5)` calls in `process_message()`.

## Testing

### Manual Testing

1. Create a test monitoring task
2. Send 15 messages rapidly to the monitored channel
3. Verify all messages are forwarded (may take longer due to rate limiting)
4. Check logs for FloodWait handling and retry information

### Expected Log Output

```
📨 收到消息: chat_id=-1001234567890, chat_name=TestChannel, 内容=文本=Message 1...
✅ 频道信息已缓存: -1001234567890
✅ 目标频道已缓存: -1001234567891
📬 消息已入队: user=123456789, source=-1001234567890, 队列大小=1

⚙️ 开始处理消息: user=123456789, source=-1001234567890
📤 转发模式：开始处理
⏳ 转发消息: 遇到限流 FLOOD_WAIT, 需等待 11 秒
   将在 12 秒后重试 (FloodWait 重试 1/3)
✅ 消息已转发
✅ 消息处理成功 (总计: 1)
```

## Performance Impact

### Positive Impacts
- **Zero message loss**: All messages eventually forwarded
- **Automatic recovery**: No manual intervention needed
- **Better API compliance**: Respects Telegram's rate limits

### Trade-offs
- **Slower processing**: 0.5s delay per message + any FloodWait delays
- **Higher latency**: Batch of 10 messages takes ~5+ seconds minimum
- **Acceptable for most use cases**: Real-time forwarding not always critical

### Example Timings

**Without rate limiting** (old behavior):
- Message 1-2: Success (instant)
- Message 3+: Failed (FloodWait, not retried)

**With rate limiting** (new behavior):
- Message 1: Success (0.5s)
- Message 2: Success (1.0s)
- Message 3: FloodWait 11s → Success (12.5s)
- Message 4-10: Success (13s, 13.5s, 14s, ...)

## Troubleshooting

### Issue: Still getting FloodWait errors

**Solution**: 
- Check if max_flood_retries is reached (logs show "FloodWait 重试次数已达上限")
- Increase max_flood_retries or rate limit delay
- Consider reducing message sending rate at source

### Issue: Messages processing too slowly

**Solution**:
- Reduce rate limit delay (but may trigger more FloodWaits)
- This is expected behavior when respecting Telegram limits
- Consider batching or scheduling for non-urgent forwards

### Issue: "Peer id invalid" errors

**Solution**:
- Ensure channels are pre-cached at startup
- Check that bot has access to source/destination channels
- Verify channel IDs are correct in configuration

## Code References

- **FloodWait retry logic**: `main.py` lines 126-153
- **Rate limiting delays**: `main.py` lines 401, 431, 442, 452, 466, 477, 488
- **Peer caching**: `main.py` lines 2475-2476, 2536-2542, 2576-2586
- **Error isolation**: `main.py` lines 91-110, 535-546

## Related Documentation

- [MESSAGE_QUEUE_SYSTEM.md](MESSAGE_QUEUE_SYSTEM.md) - Queue architecture
- Pyrogram FloodWait documentation: https://docs.pyrogram.org/api/errors#floodwait
