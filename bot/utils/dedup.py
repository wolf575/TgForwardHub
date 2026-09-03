"""
Message deduplication utilities
Prevents duplicate processing of messages and media groups
"""
import time
import logging
import threading
from typing import Dict
from collections import OrderedDict
from constants import MESSAGE_CACHE_TTL, MAX_MEDIA_GROUP_CACHE, MEDIA_GROUP_CLEANUP_BATCH_SIZE, MESSAGE_CACHE_CLEANUP_THRESHOLD

logger = logging.getLogger(__name__)

# Message deduplication cache
processed_messages: Dict[str, float] = {}
_message_lock = threading.Lock()

# Media group deduplication cache (LRU with OrderedDict for efficient cleanup)
# 改为存储时间戳，支持基于时间的去重
processed_media_groups: OrderedDict[str, float] = OrderedDict()
_media_group_lock = threading.Lock()

# 媒体组去重的时间窗口（秒）- 优化：从2秒降到1秒，减少缓存时间
MEDIA_GROUP_DEDUP_WINDOW = 1.0  # 1秒内的重复媒体组会被过滤

# 消息缓存清理阈值（当缓存超过此大小时触发清理）
MESSAGE_CACHE_MAX_SIZE = MESSAGE_CACHE_CLEANUP_THRESHOLD


def register_processed_media_group(key: str):
    """Register a media group as processed (thread-safe, LRU cache with timestamp)

    Args:
        key: Media group key in format "user_id_watch_key_dest_chat_id_mode_suffix_media_group_id"
    """
    if not key:
        logger.warning("⚠️ register_processed_media_group: 空的key")
        return

    current_time = time.time()

    with _media_group_lock:
        # Move to end if exists (refresh LRU position)
        if key in processed_media_groups:
            processed_media_groups.move_to_end(key)

        # 存储当前时间戳
        processed_media_groups[key] = current_time

        # LRU cleanup: remove oldest entries if cache exceeds limit
        if len(processed_media_groups) > MAX_MEDIA_GROUP_CACHE:
            # Remove oldest entries efficiently with loop protection
            removed_count = 0
            max_iterations = MEDIA_GROUP_CLEANUP_BATCH_SIZE

            for _ in range(max_iterations):
                if len(processed_media_groups) > MAX_MEDIA_GROUP_CACHE:
                    processed_media_groups.popitem(last=False)  # Remove oldest (FIFO)
                    removed_count += 1
                else:
                    break

            if removed_count > 0:
                logger.debug(f"🧹 媒体组缓存清理: 移除最旧的 {removed_count} 个条目，当前大小={len(processed_media_groups)}")


def is_media_group_processed(key: str) -> bool:
    """Check if a media group has been processed within the dedup window (thread-safe)

    Args:
        key: Media group key

    Returns:
        True if already processed within MEDIA_GROUP_DEDUP_WINDOW, False otherwise
    """
    if not key:
        return False

    current_time = time.time()

    with _media_group_lock:
        if key in processed_media_groups:
            timestamp = processed_media_groups[key]
            # 检查是否在去重时间窗口内
            if current_time - timestamp < MEDIA_GROUP_DEDUP_WINDOW:
                return True
            else:
                # 超过时间窗口，删除旧记录
                del processed_media_groups[key]
                return False
        return False


def is_message_processed(message_id: int, chat_id: int) -> bool:
    """Check if a message has been recently processed (thread-safe)
    
    Args:
        message_id: Telegram message ID
        chat_id: Telegram chat ID
        
    Returns:
        True if message was processed within MESSAGE_CACHE_TTL seconds
    """
    key = f"{chat_id}_{message_id}"
    
    with _message_lock:
        if key in processed_messages:
            timestamp = processed_messages[key]
            if time.time() - timestamp < MESSAGE_CACHE_TTL:
                return True
            # Expired, remove it
            del processed_messages[key]
        return False


def mark_message_processed(message_id: int, chat_id: int):
    """Mark a message as processed (thread-safe)
    
    Args:
        message_id: Telegram message ID
        chat_id: Telegram chat ID
    """
    key = f"{chat_id}_{message_id}"
    
    with _message_lock:
        processed_messages[key] = time.time()


def cleanup_old_messages():
    """Clean up expired message records (thread-safe)

    优化：
    1. 清理过期的消息记录
    2. 清理过期的媒体组记录
    3. 如果缓存超过阈值，强制清理最旧的条目
    """
    current_time = time.time()

    with _message_lock:
        # 清理过期条目
        expired_keys = [key for key, timestamp in processed_messages.items()
                        if current_time - timestamp > MESSAGE_CACHE_TTL]
        for key in expired_keys:
            del processed_messages[key]

        if expired_keys:
            logger.debug(f"🧹 消息缓存清理: 移除{len(expired_keys)}个过期条目")

        # 如果缓存仍然过大，强制清理最旧的条目
        if len(processed_messages) > MESSAGE_CACHE_MAX_SIZE:
            # 按时间戳排序，删除最旧的50%
            sorted_items = sorted(processed_messages.items(), key=lambda x: x[1])
            remove_count = len(sorted_items) // 2
            for key, _ in sorted_items[:remove_count]:
                del processed_messages[key]
            logger.info(f"🧹 消息缓存超限，强制清理{remove_count}个最旧条目 (剩余: {len(processed_messages)})")

    # 优化：同时清理过期的媒体组缓存
    with _media_group_lock:
        expired_media_keys = [key for key, timestamp in processed_media_groups.items()
                              if current_time - timestamp > MEDIA_GROUP_DEDUP_WINDOW]
        for key in expired_media_keys:
            del processed_media_groups[key]

        if expired_media_keys:
            logger.debug(f"🧹 媒体组缓存清理: 移除{len(expired_media_keys)}个过期条目")


def get_cache_stats() -> dict:
    """Get cache statistics (for monitoring/debugging)
    
    Returns:
        Dictionary with cache statistics
    """
    with _message_lock:
        message_count = len(processed_messages)
    
    with _media_group_lock:
        media_group_count = len(processed_media_groups)
    
    return {
        'message_cache_size': message_count,
        'media_group_cache_size': media_group_count,
        'message_cache_ttl': MESSAGE_CACHE_TTL,
        'media_group_cache_max': MAX_MEDIA_GROUP_CACHE
    }
