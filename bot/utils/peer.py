"""
Peer caching and management utilities
"""
import logging
import time
from typing import Dict
from collections import OrderedDict
from pyrogram.errors import FloodWait
from constants import MAX_CACHED_PEERS, MAX_FAILED_PEERS

logger = logging.getLogger(__name__)

# Cached destination peers (LRU cache with max size)
cached_dest_peers: OrderedDict[str, float] = OrderedDict()

# Failed peers that need delayed loading retry (LRU cache with max size)
failed_peers: OrderedDict[str, float] = OrderedDict()

# Retry cooldown in seconds (wait before retrying failed peer)
RETRY_COOLDOWN = 60


def is_dest_cached(dest_id: str) -> bool:
    """Check if destination peer is cached
    
    Args:
        dest_id: Destination chat ID
        
    Returns:
        True if cached, False otherwise
    """
    return dest_id in cached_dest_peers


def mark_dest_cached(dest_id: str):
    """Mark destination peer as cached (LRU mechanism)

    Args:
        dest_id: Destination chat ID
    """
    # Add/update timestamp and move to end (most recently used)
    cached_dest_peers[dest_id] = time.time()
    cached_dest_peers.move_to_end(dest_id)

    # LRU cleanup: remove oldest entries if cache exceeds limit
    if len(cached_dest_peers) > MAX_CACHED_PEERS:
        oldest_peer = cached_dest_peers.popitem(last=False)
        logger.debug(f"🧹 Peer缓存已满，移除最旧的: {oldest_peer[0]}")

    # Remove from failed peers if it was there
    if dest_id in failed_peers:
        del failed_peers[dest_id]


def mark_peer_failed(peer_id: str):
    """Mark peer as failed to cache (LRU mechanism)

    Args:
        peer_id: Peer ID that failed to cache
    """
    # Add/update timestamp and move to end
    failed_peers[peer_id] = time.time()
    failed_peers.move_to_end(peer_id)

    # LRU cleanup: remove oldest entries if cache exceeds limit
    if len(failed_peers) > MAX_FAILED_PEERS:
        oldest_failed = failed_peers.popitem(last=False)
        logger.debug(f"🧹 失败Peer缓存已满，移除最旧的: {oldest_failed[0]}")

    logger.info(f"📋 已标记失败的Peer: {peer_id} (将在 {RETRY_COOLDOWN}s 后重试)")


def should_retry_peer(peer_id: str) -> bool:
    """Check if we should retry caching a failed peer
    
    Args:
        peer_id: Peer ID to check
        
    Returns:
        True if we should retry, False otherwise
    """
    if peer_id not in failed_peers:
        return True
    
    last_attempt = failed_peers[peer_id]
    elapsed = time.time() - last_attempt
    return elapsed >= RETRY_COOLDOWN


def get_failed_peers() -> Dict[str, float]:
    """Get dictionary of failed peers
    
    Returns:
        Dictionary mapping peer_id to last attempt timestamp
    """
    return failed_peers.copy()


def cache_peer(client, peer_id: str, peer_type: str = "peer", force: bool = False) -> bool:
    """Cache a peer by getting its info
    
    Args:
        client: Pyrogram client
        peer_id: Peer ID to cache
        peer_type: Type description for logging
        force: Force retry even if cooldown hasn't expired
        
    Returns:
        True if cached successfully, False otherwise
    """
    # Check if we should retry this peer
    if not force and not should_retry_peer(peer_id):
        elapsed = time.time() - failed_peers.get(peer_id, 0)
        remaining = RETRY_COOLDOWN - elapsed
        logger.debug(f"⏳ 跳过缓存{peer_type} {peer_id}，等待冷却（还需 {remaining:.0f}秒）")
        return False
    
    try:
        chat = client.get_chat(int(peer_id))
        logger.info(f"✅ 已缓存{peer_type}: {peer_id}")
        mark_dest_cached(peer_id)
        return True
    except FloodWait as e:
        logger.warning(f"⚠️ 限流: {peer_type} {peer_id}，等待 {e.value} 秒")
        mark_peer_failed(peer_id)
        return False
    except Exception as e:
        logger.warning(f"⚠️ 无法缓存{peer_type} {peer_id}: {str(e)}")
        mark_peer_failed(peer_id)
        return False
