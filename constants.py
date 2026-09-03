"""
Application-wide constants
Centralized configuration for magic numbers and constants
"""

# Cache sizes (优化：进一步降低缓存大小以减少内存占用)
MAX_MEDIA_GROUP_CACHE = 50  # 从100降到50，减少媒体组缓存
MESSAGE_CACHE_CLEANUP_THRESHOLD = 200  # 从300降到200，更早触发清理
MEDIA_GROUP_CLEANUP_BATCH_SIZE = 25  # 从50降到25，减少批量清理开销

# Peer cache limits (优化：降低Peer缓存大小)
MAX_CACHED_PEERS = 30  # 从50降到30，减少Peer缓存
MAX_FAILED_PEERS = 20  # 从30降到20，减少失败Peer记录

# Time constants (seconds)
MESSAGE_CACHE_TTL = 0.2  # 从0.3降到0.2秒，更快过期
WORKER_STATS_INTERVAL = 20  # 从30秒降到20秒，更频繁清理缓存
RATE_LIMIT_DELAY = 1.0  # 保持1秒，平衡速度和稳定性

# Retry configuration
MAX_RETRIES = 3
MAX_FLOOD_RETRIES = 3
OPERATION_TIMEOUT = 30.0

# Backoff configuration
def get_backoff_time(retry_count: int) -> int:
    """Calculate exponential backoff time: 1s, 2s, 4s"""
    return 2 ** (retry_count - 1)

# Media limits
MAX_MEDIA_PER_GROUP = 9

# Database deduplication window (seconds)
DB_DEDUP_WINDOW = 5

# Usage help text
USAGE = """**📌 公开频道/群组**

__直接发送帖子链接即可__

**🔒 私有频道/群组**

__首先发送频道邀请链接（如果 String Session 账号已加入则不需要）
然后发送帖子链接__

**🤖 机器人聊天**

__发送带有 '/b/'、机器人用户名和消息 ID 的链接，你可能需要使用一些非官方客户端来获取 ID，如下所示__

```
https://t.me/b/botusername/4321
```

**📦 批量下载**

__按照上述方式发送公开/私有帖子链接，使用 "from - to" 格式发送多条消息，如下所示__

```
https://t.me/xxxx/1001-1010

https://t.me/c/xxxx/101 - 120
```

__注意：中间的空格无关紧要__
"""
