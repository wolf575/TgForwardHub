# Auto-Cache Destination Peers on Startup

## Problem
Forwarding to bots and other peers suddenly fails with "Peer id invalid" errors after Docker restarts or session resets because Pyrogram's Peer cache is lost.

## Solution Implemented

### 1. Startup Destination Peer Pre-Caching
**Location**: `main.py` lines ~2786-2844

- Automatically caches all destination peers during bot startup
- Extracts destination peer IDs from `watch_config.json`
- Only caches forward mode destinations (record mode doesn't need caching)
- Displays peer information with bot emoji indicator (🤖)
- Handles FloodWait and other exceptions gracefully
- Provides helpful diagnostic output for failed caching attempts

**Example Output**:
```
🔄 预加载目标Peer信息到缓存...
   ✅ 已缓存目标: 7086222377 (MyBot 🤖)
   ✅ 已缓存目标: -1001234567890 (MyChannel)
📦 成功缓存 2/2 个目标Peer
```

### 2. Global Cached Peers Tracking
**Location**: `main.py` line 2435

- Added `cached_dest_peers = set()` to track which destination peers are already cached
- Prevents redundant API calls to `get_chat()` for already-cached peers
- Persists across message processing

### 3. Improved Handler Destination Caching
**Location**: `main.py` lines ~2630-2642

- Checks `cached_dest_peers` before attempting to cache a destination
- Adds destination to `cached_dest_peers` after successful caching
- Upgraded logging from debug to warning level for FloodWait
- Never interrupts message processing due to cache failures
- Continues with forwarding even if caching fails (might already be cached)

## Benefits

✅ **No more "Peer id invalid" errors after Docker restarts**
- All destination peers are pre-cached on startup
- Session cache is properly populated before any forwarding attempts

✅ **Reduced API calls**
- Tracks cached peers to avoid redundant `get_chat()` calls
- Significantly reduces API rate limiting risks

✅ **Better observability**
- Clear startup logs show which peers are cached
- Bot emoji indicator for easy bot identification
- Helpful diagnostics for failed caching attempts

✅ **Graceful error handling**
- FloodWait during caching doesn't stop bot startup
- Cache failures don't prevent message processing
- Detailed error messages for troubleshooting

## Testing

### Verify Startup Caching
```bash
# Check bot startup logs for destination peer caching
docker logs save-restricted-bot | grep "预加载目标"

# Should show:
# 🔄 预加载目标Peer信息到缓存...
#    ✅ 已缓存目标: <peer_id> (<peer_name>)
# 📦 成功缓存 X/X 个目标Peer
```

### Test Forwarding After Restart
```bash
# Restart bot
docker-compose restart

# Send a test message to source channel
# Verify it forwards to destination bot/peer without errors
```

### Check for Errors
```bash
# Look for "Peer id invalid" errors (should be none)
docker logs save-restricted-bot | grep "Peer id invalid"
```

## Implementation Details

### Peer Cache Logic
1. **Startup Phase**:
   - Parse `watch_config.json` for all destination peer IDs
   - Filter for forward mode only (skip record mode)
   - Exclude "me" destinations (self-chat)
   - Call `acc.get_chat()` for each destination
   - Track successful caches in `cached_dest_peers`

2. **Message Handler Phase**:
   - Check if destination is in `cached_dest_peers`
   - If not cached, attempt to cache with `acc.get_chat()`
   - Add to `cached_dest_peers` on success
   - Continue processing even if caching fails

3. **FloodWait Handling**:
   - Startup: Log warning, skip this peer, continue with others
   - Handler: Log warning, continue with forwarding
   - Never causes message loss or processing interruption

### Code Structure
```python
# Global tracking set
cached_dest_peers = set()

# Startup caching
if acc is not None:
    dest_ids_to_cache = set()
    # Extract dest IDs from watch_config
    # Cache each destination peer
    # Track in cached_dest_peers

# Handler caching
if dest_chat_id not in cached_dest_peers:
    try:
        acc.get_chat(int(dest_chat_id))
        cached_dest_peers.add(dest_chat_id)
    except FloodWait:
        # Log warning, continue
    except Exception:
        # Log warning, continue
```

## Edge Cases Handled

- ✅ Invalid peer ID formats (ValueError, TypeError)
- ✅ FloodWait during caching
- ✅ Bot peers (detected and marked with emoji)
- ✅ "me" destinations (skipped)
- ✅ Record mode destinations (skipped, no forwarding needed)
- ✅ Empty watch_config (no errors)
- ✅ Duplicate destination IDs (set deduplication)

## Related Files
- `main.py` - Core implementation
- `watch_config.json` - Configuration with destination peers
- `AUTO_CACHE_DEST_PEERS.md` - This documentation

## References
- Pyrogram Peer caching: https://docs.pyrogram.org/topics/storage-engines
- Original issue: Bot forwarding to ID 7086222377 failed after restart
