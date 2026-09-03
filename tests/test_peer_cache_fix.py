#!/usr/bin/env python3
"""
Test script for peer cache preload and delayed loading mechanism
"""
import time
import sys
from bot.utils.peer import (
    is_dest_cached, mark_dest_cached, mark_peer_failed, 
    should_retry_peer, get_failed_peers, RETRY_COOLDOWN,
    cached_dest_peers, failed_peers
)

def test_peer_cache_basic():
    """Test basic caching functionality"""
    print("Test 1: Basic peer caching")
    
    # Clear state
    cached_dest_peers.clear()
    failed_peers.clear()
    
    peer_id = "-1001234567890"
    
    # Initially not cached
    assert not is_dest_cached(peer_id), "Peer should not be cached initially"
    print("  ✅ Peer not cached initially")
    
    # Mark as cached
    mark_dest_cached(peer_id)
    assert is_dest_cached(peer_id), "Peer should be cached after marking"
    print("  ✅ Peer cached successfully")
    
    # Check it's in the set
    assert peer_id in cached_dest_peers, "Peer should be in cached_dest_peers set"
    print("  ✅ Peer in cached_dest_peers set")
    
    print("✅ Test 1 passed\n")


def test_failed_peer_tracking():
    """Test failed peer tracking and retry logic"""
    print("Test 2: Failed peer tracking")
    
    # Clear state
    cached_dest_peers.clear()
    failed_peers.clear()
    
    peer_id = "-1001234567890"
    
    # Mark as failed
    mark_peer_failed(peer_id)
    assert peer_id in failed_peers, "Peer should be in failed_peers"
    print("  ✅ Peer marked as failed")
    
    # Should not retry immediately (cooldown)
    assert not should_retry_peer(peer_id), "Should not retry immediately after failure"
    print("  ✅ Retry blocked by cooldown")
    
    # Get failed peers
    failed = get_failed_peers()
    assert peer_id in failed, "Peer should be in failed peers dict"
    print("  ✅ Peer in failed_peers dict")
    
    print("✅ Test 2 passed\n")


def test_successful_cache_after_failure():
    """Test that successful caching removes from failed list"""
    print("Test 3: Successful cache after failure")
    
    # Clear state
    cached_dest_peers.clear()
    failed_peers.clear()
    
    peer_id = "-1001234567890"
    
    # Mark as failed first
    mark_peer_failed(peer_id)
    assert peer_id in failed_peers, "Peer should be in failed_peers"
    print("  ✅ Peer marked as failed")
    
    # Now mark as cached (simulating successful retry)
    mark_dest_cached(peer_id)
    assert is_dest_cached(peer_id), "Peer should be cached"
    assert peer_id not in failed_peers, "Peer should be removed from failed_peers"
    print("  ✅ Peer cached and removed from failed list")
    
    print("✅ Test 3 passed\n")


def test_retry_cooldown_expiry():
    """Test that retry is allowed after cooldown expires"""
    print("Test 4: Retry cooldown expiry (simulated)")
    
    # Clear state
    cached_dest_peers.clear()
    failed_peers.clear()
    
    peer_id = "-1001234567890"
    
    # Mark as failed
    mark_peer_failed(peer_id)
    assert not should_retry_peer(peer_id), "Should not retry immediately"
    print("  ✅ Retry blocked immediately after failure")
    
    # Simulate time passing by directly manipulating the timestamp
    # Move timestamp back by RETRY_COOLDOWN + 1 second
    old_timestamp = failed_peers[peer_id]
    failed_peers[peer_id] = old_timestamp - (RETRY_COOLDOWN + 1)
    
    # Now should be able to retry
    assert should_retry_peer(peer_id), "Should allow retry after cooldown expires"
    print("  ✅ Retry allowed after cooldown expiry")
    
    print("✅ Test 4 passed\n")


def test_multiple_failed_peers():
    """Test tracking multiple failed peers"""
    print("Test 5: Multiple failed peers")
    
    # Clear state
    cached_dest_peers.clear()
    failed_peers.clear()
    
    peer_ids = ["-1001111111111", "-1002222222222", "-1003333333333"]
    
    # Mark all as failed
    for peer_id in peer_ids:
        mark_peer_failed(peer_id)
    
    # Check all are in failed list
    failed = get_failed_peers()
    assert len(failed) == 3, "Should have 3 failed peers"
    for peer_id in peer_ids:
        assert peer_id in failed, f"Peer {peer_id} should be in failed list"
    print("  ✅ All 3 peers marked as failed")
    
    # Mark one as cached
    mark_dest_cached(peer_ids[0])
    assert is_dest_cached(peer_ids[0]), "First peer should be cached"
    assert peer_ids[0] not in get_failed_peers(), "First peer should be removed from failed list"
    assert len(get_failed_peers()) == 2, "Should have 2 failed peers remaining"
    print("  ✅ One peer cached, removed from failed list")
    
    print("✅ Test 5 passed\n")


def main():
    print("="*60)
    print("Testing Peer Cache Preload and Delayed Loading Fix")
    print("="*60 + "\n")
    
    try:
        test_peer_cache_basic()
        test_failed_peer_tracking()
        test_successful_cache_after_failure()
        test_retry_cooldown_expiry()
        test_multiple_failed_peers()
        
        print("="*60)
        print("✅ All tests passed!")
        print("="*60)
        return 0
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
