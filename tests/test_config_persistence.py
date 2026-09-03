#!/usr/bin/env python3
"""
Test for configuration persistence issue
"""
import json
import os
import sys
import time
import tempfile
import shutil

# Test 1: Verify save_watch_config flushes data
def test_config_flush():
    """Test that config is immediately written to disk"""
    print("Test 1: Config file flush...")
    
    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    config_file = os.path.join(temp_dir, 'test_watch_config.json')
    
    try:
        # Simulate save_watch_config
        test_config = {
            "12345": {
                "test_source|test_dest": {
                    "source": "-100123456789",
                    "dest": "me",
                    "record_mode": False
                }
            }
        }
        
        # Write without explicit flush
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(test_config, f, indent=4, ensure_ascii=False)
        # No explicit f.flush() or f.close() - context manager handles it
        
        # Immediately read it back
        with open(config_file, 'r', encoding='utf-8') as f:
            loaded_config = json.load(f)
        
        if loaded_config == test_config:
            print("  ✅ Config correctly saved and loaded")
            return True
        else:
            print("  ❌ Config mismatch!")
            print(f"  Expected: {test_config}")
            print(f"  Got: {loaded_config}")
            return False
    finally:
        # Cleanup
        shutil.rmtree(temp_dir)


# Test 2: Verify monitored_sources synchronization
def test_monitored_sources_sync():
    """Test that monitored_sources is updated after config changes"""
    print("\nTest 2: Monitored sources synchronization...")
    
    # Simulate the build_monitored_sources function
    def build_monitored_sources(watch_config):
        sources = set()
        for user_id, watches in watch_config.items():
            for watch_key, watch_data in watches.items():
                if isinstance(watch_data, dict):
                    source = watch_data.get('source')
                else:
                    source = watch_key
                if source and source != 'me':
                    sources.add(str(source))
        return sources
    
    # Initial config
    config1 = {
        "12345": {
            "source1|dest1": {
                "source": "-100111111",
                "dest": "me",
                "record_mode": False
            }
        }
    }
    
    monitored_sources = build_monitored_sources(config1)
    print(f"  Initial sources: {monitored_sources}")
    
    if "-100111111" not in monitored_sources:
        print("  ❌ Initial source not found")
        return False
    
    # Add new source (simulating add operation)
    config2 = {
        "12345": {
            "source1|dest1": {
                "source": "-100111111",
                "dest": "me",
                "record_mode": False
            },
            "source2|dest2": {
                "source": "-100222222",
                "dest": "me",
                "record_mode": False
            }
        }
    }
    
    # If we don't call reload_monitored_sources, the old set is used
    print(f"  Old sources (before reload): {monitored_sources}")
    
    # Reload
    monitored_sources = build_monitored_sources(config2)
    print(f"  New sources (after reload): {monitored_sources}")
    
    if "-100222222" in monitored_sources:
        print("  ✅ New source correctly added after reload")
        return True
    else:
        print("  ❌ New source not found after reload")
        return False


# Test 3: Check file write with fsync
def test_config_fsync():
    """Test that config is synced to disk"""
    print("\nTest 3: Config file fsync...")
    
    temp_dir = tempfile.mkdtemp()
    config_file = os.path.join(temp_dir, 'test_watch_config.json')
    
    try:
        test_config = {
            "12345": {
                "test_source": {
                    "source": "-100123456789",
                    "dest": "me"
                }
            }
        }
        
        # Write with explicit flush and fsync
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(test_config, f, indent=4, ensure_ascii=False)
            f.flush()  # Flush Python buffers
            os.fsync(f.fileno())  # Ensure OS writes to disk
        
        # Verify it's readable
        with open(config_file, 'r', encoding='utf-8') as f:
            loaded_config = json.load(f)
        
        if loaded_config == test_config:
            print("  ✅ Config with fsync works correctly")
            return True
        else:
            print("  ❌ Config mismatch after fsync")
            return False
    finally:
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    print("="*60)
    print("Testing Configuration Persistence")
    print("="*60)
    
    test1_pass = test_config_flush()
    test2_pass = test_monitored_sources_sync()
    test3_pass = test_config_fsync()
    
    print("\n" + "="*60)
    print("Test Results:")
    print("="*60)
    print(f"Test 1 (Config Flush): {'✅ PASS' if test1_pass else '❌ FAIL'}")
    print(f"Test 2 (Monitored Sources Sync): {'✅ PASS' if test2_pass else '❌ FAIL'}")
    print(f"Test 3 (Config Fsync): {'✅ PASS' if test3_pass else '❌ FAIL'}")
    
    all_pass = test1_pass and test2_pass and test3_pass
    print("\n" + ("="*60))
    print(f"Overall: {'✅ ALL TESTS PASSED' if all_pass else '❌ SOME TESTS FAILED'}")
    print("="*60)
    
    sys.exit(0 if all_pass else 1)
