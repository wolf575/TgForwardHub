# Async Blocking Fix for Batch Message Processing

## Problem Summary

When 10+ messages were sent simultaneously to a monitored channel, the message queue system would only process the first 2-3 messages before halting. The remaining messages stayed in the queue without being processed.

### Symptoms
- ✅ All messages enqueued successfully
- ❌ Only 2-3 messages processed
- ❌ Worker thread appeared to hang
- ❌ Logs showed `ValueError: Peer id invalid` not being caught properly
- ❌ Queue statistics showed messages stuck in queue

### Root Cause

The worker thread is a **synchronous Python thread** that needs to execute **async Pyrogram operations** (like `forward_messages()`, `download_media()`, `get_media_group()`). Without proper async handling, these operations were:

1. **Not executing at all** - calling an async function without `await` just returns a coroutine object
2. **Blocking the thread** - incomplete async operations caused the worker to hang
3. **Causing cascading failures** - one blocked operation stopped all subsequent messages

## Solution

### 1. Event Loop in Worker Thread

The worker thread now creates its own asyncio event loop at startup:

```python
def run(self):
    """Main loop with event loop for async operations"""
    # Create event loop for this thread
    self.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(self.loop)
    logger.info("🔧 消息工作线程已启动（带事件循环）")
    
    while self.running:
        # ... process messages ...
    
    # Clean up event loop
    if self.loop:
        self.loop.close()
    logger.info("🛑 消息工作线程已停止")
```

### 2. Async Operation Wrapper with Timeout

All async operations are executed via `_run_async_with_timeout()`:

```python
def _run_async_with_timeout(self, coro, timeout: float = 30.0):
    """Execute async operation with timeout in the worker thread"""
    try:
        return self.loop.run_until_complete(
            asyncio.wait_for(coro, timeout=timeout)
        )
    except asyncio.TimeoutError:
        logger.error(f"❌ 操作超时（{timeout}秒）")
        raise
```

### 3. Updated FloodWait Handler

The `_execute_with_flood_retry()` method now:
- Detects if the operation returns a coroutine
- Automatically executes it with timeout control
- Handles timeouts gracefully without blocking queue
- Catches and properly handles `Peer id invalid` errors

```python
def _execute_with_flood_retry(self, operation_name: str, operation_func, 
                              max_flood_retries: int = 3, timeout: float = 30.0):
    for flood_attempt in range(max_flood_retries):
        try:
            result = operation_func()
            # Check if result is a coroutine (async operation)
            if asyncio.iscoroutine(result):
                self._run_async_with_timeout(result, timeout=timeout)
            return True
        except FloodWait as e:
            # ... handle FloodWait ...
        except asyncio.TimeoutError:
            logger.error(f"❌ {operation_name}: 操作超时（{timeout}秒），跳过此消息")
            return False
        except (ValueError, KeyError) as e:
            if "Peer id invalid" in str(e) or "ID not found" in str(e):
                logger.warning(f"⚠️ {operation_name}: Peer ID 无效，跳过: {e}")
                return False
            raise
```

### 4. All Async Operations Wrapped

Every Pyrogram async call is now wrapped:

```python
# Media group retrieval
media_group = self._run_async_with_timeout(
    acc.get_media_group(message.chat.id, message.id),
    timeout=30.0
)

# Media download
self._run_async_with_timeout(
    acc.download_media(photo.file_id, file_name=file_path),
    timeout=60.0  # Longer timeout for downloads
)

# Forward/copy operations (via _execute_with_flood_retry)
success = self._execute_with_flood_retry(
    "转发消息",
    lambda: acc.forward_messages(dest_id, message.chat.id, message.id),
    timeout=30.0
)
```

## Timeout Values

Different operations have different timeout values based on their expected duration:

- **API calls** (get_chat, get_media_group, forward_messages, etc.): **30 seconds**
- **Media downloads** (download_media): **60 seconds**

## Benefits

1. ✅ **No blocking**: Async operations execute properly without blocking the worker thread
2. ✅ **Timeout control**: Operations that hang are automatically terminated after timeout
3. ✅ **Fault isolation**: One failed/timeout message doesn't stop subsequent messages
4. ✅ **Proper error handling**: All exceptions (FloodWait, Peer invalid, timeout) handled correctly
5. ✅ **Complete processing**: All enqueued messages are processed (unless they individually fail)
6. ✅ **Better logging**: Clear distinction between different failure types

## Verification

Run the test script to verify the fix:

```bash
python test_async_fix.py
```

Expected output:
- All 10 messages enqueued
- 9 messages processed successfully
- 1 message fails due to timeout (expected)
- No blocking or hanging
- Worker processes all messages sequentially

## Real-World Test

1. Send 10+ messages to a monitored channel simultaneously
2. Check logs for:
   - ✅ All messages enqueued: `✅ 消息已入队`
   - ✅ All messages taken from queue: `📥 从队列取出消息`
   - ✅ All messages processed: `✅ 消息处理成功`
   - ✅ Queue statistics show: `待处理=0, 已完成=10+`

## Technical Details

### Why Worker Thread Needs Its Own Event Loop

- The main Pyrogram event loop runs in the main thread
- Worker thread is a separate daemon thread for serial processing
- Calling `await` or `async` functions directly in a sync thread doesn't work
- Solution: Create a dedicated event loop in the worker thread and use `run_until_complete()`

### Why Timeout is Critical

- Network issues or Telegram rate limits can cause operations to hang indefinitely
- Without timeout, one stuck operation blocks the entire queue
- With timeout, failed operations are logged and queue continues processing

### Why Coroutine Detection

- Lambda functions passed to `_execute_with_flood_retry()` return coroutines
- Need to detect and execute them properly in the event loop
- `asyncio.iscoroutine()` check handles this automatically

## Related Files

- `main.py`: MessageWorker class implementation
- `test_async_fix.py`: Test suite for async handling
- `MESSAGE_QUEUE_SYSTEM.md`: Queue system documentation
- `FLOODWAIT_HANDLING.md`: FloodWait handling documentation
