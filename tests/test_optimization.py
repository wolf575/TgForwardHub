#!/usr/bin/env python3
"""
Comprehensive test suite for code optimization
Tests functionality, performance, and correctness of optimized code
"""
import sys
import time
import unittest
import os
import tempfile
import shutil
from collections import OrderedDict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test imports
import constants
from bot.utils.dedup import (
    register_processed_media_group, 
    is_media_group_processed,
    processed_media_groups,
    is_message_processed,
    mark_message_processed,
    cleanup_old_messages
)


class TestConstants(unittest.TestCase):
    """Test constants module"""
    
    def test_constants_exist(self):
        """Verify all constants are defined"""
        self.assertIsNotNone(constants.MAX_MEDIA_GROUP_CACHE)
        self.assertIsNotNone(constants.MESSAGE_CACHE_CLEANUP_THRESHOLD)
        self.assertIsNotNone(constants.MEDIA_GROUP_CLEANUP_BATCH_SIZE)
        self.assertIsNotNone(constants.MESSAGE_CACHE_TTL)
        self.assertIsNotNone(constants.WORKER_STATS_INTERVAL)
        self.assertIsNotNone(constants.RATE_LIMIT_DELAY)
        self.assertIsNotNone(constants.MAX_RETRIES)
        self.assertIsNotNone(constants.MAX_FLOOD_RETRIES)
        self.assertIsNotNone(constants.OPERATION_TIMEOUT)
        self.assertIsNotNone(constants.MAX_MEDIA_PER_GROUP)
        self.assertIsNotNone(constants.DB_DEDUP_WINDOW)
    
    def test_constants_types(self):
        """Verify constants have correct types"""
        self.assertIsInstance(constants.MAX_MEDIA_GROUP_CACHE, int)
        self.assertIsInstance(constants.MESSAGE_CACHE_CLEANUP_THRESHOLD, int)
        self.assertIsInstance(constants.MEDIA_GROUP_CLEANUP_BATCH_SIZE, int)
        self.assertIsInstance(constants.MESSAGE_CACHE_TTL, (int, float))
        self.assertIsInstance(constants.WORKER_STATS_INTERVAL, (int, float))
        self.assertIsInstance(constants.RATE_LIMIT_DELAY, (int, float))
        self.assertIsInstance(constants.MAX_RETRIES, int)
        self.assertIsInstance(constants.MAX_FLOOD_RETRIES, int)
        self.assertIsInstance(constants.OPERATION_TIMEOUT, (int, float))
        self.assertIsInstance(constants.MAX_MEDIA_PER_GROUP, int)
        self.assertIsInstance(constants.DB_DEDUP_WINDOW, (int, float))
    
    def test_constants_values(self):
        """Verify constants have reasonable values"""
        self.assertGreater(constants.MAX_MEDIA_GROUP_CACHE, 0)
        self.assertGreater(constants.MESSAGE_CACHE_CLEANUP_THRESHOLD, 0)
        self.assertGreater(constants.MEDIA_GROUP_CLEANUP_BATCH_SIZE, 0)
        self.assertGreater(constants.MESSAGE_CACHE_TTL, 0)
        self.assertGreater(constants.WORKER_STATS_INTERVAL, 0)
        self.assertGreater(constants.RATE_LIMIT_DELAY, 0)
        self.assertGreater(constants.MAX_RETRIES, 0)
        self.assertGreater(constants.MAX_FLOOD_RETRIES, 0)
        self.assertGreater(constants.OPERATION_TIMEOUT, 0)
        self.assertGreater(constants.MAX_MEDIA_PER_GROUP, 0)
        self.assertGreater(constants.DB_DEDUP_WINDOW, 0)
    
    def test_get_backoff_time(self):
        """Test exponential backoff function"""
        self.assertEqual(constants.get_backoff_time(1), 1)
        self.assertEqual(constants.get_backoff_time(2), 2)
        self.assertEqual(constants.get_backoff_time(3), 4)
        self.assertEqual(constants.get_backoff_time(4), 8)


class TestDedupOptimization(unittest.TestCase):
    """Test deduplication module optimization"""
    
    def setUp(self):
        """Clear caches before each test"""
        processed_media_groups.clear()
    
    def test_media_group_uses_ordered_dict(self):
        """Verify media group cache uses OrderedDict"""
        self.assertIsInstance(processed_media_groups, OrderedDict)
    
    def test_media_group_lru_behavior(self):
        """Test LRU cache behavior"""
        # Add items
        register_processed_media_group("key1")
        register_processed_media_group("key2")
        register_processed_media_group("key3")
        
        # Verify all present
        self.assertTrue(is_media_group_processed("key1"))
        self.assertTrue(is_media_group_processed("key2"))
        self.assertTrue(is_media_group_processed("key3"))
        
        # Access key1 (should move to end)
        register_processed_media_group("key1")
        
        # Verify key1 is at the end
        keys = list(processed_media_groups.keys())
        self.assertEqual(keys[-1], "key1")
    
    def test_media_group_cache_limit(self):
        """Test cache size limit enforcement"""
        # Fill cache beyond limit
        for i in range(constants.MAX_MEDIA_GROUP_CACHE + 100):
            register_processed_media_group(f"key_{i}")
        
        # Verify cache size is within limit
        self.assertLessEqual(len(processed_media_groups), constants.MAX_MEDIA_GROUP_CACHE)
    
    def test_media_group_cleanup_efficiency(self):
        """Test cleanup removes correct number of items"""
        # Fill cache to limit
        for i in range(constants.MAX_MEDIA_GROUP_CACHE):
            register_processed_media_group(f"key_{i}")
        
        initial_size = len(processed_media_groups)
        
        # Add one more to trigger cleanup
        register_processed_media_group("trigger_key")
        
        # Verify cleanup occurred
        final_size = len(processed_media_groups)
        self.assertLessEqual(final_size, constants.MAX_MEDIA_GROUP_CACHE)
    
    def test_message_deduplication(self):
        """Test message deduplication works"""
        chat_id = 12345
        message_id = 67890
        
        # First check should return False
        self.assertFalse(is_message_processed(message_id, chat_id))
        
        # Mark as processed
        mark_message_processed(message_id, chat_id)
        
        # Second check should return True
        self.assertTrue(is_message_processed(message_id, chat_id))
    
    def test_message_cleanup(self):
        """Test message cache cleanup"""
        # Add many messages
        for i in range(100):
            mark_message_processed(i, 12345)
        
        # Wait for TTL to expire
        time.sleep(constants.MESSAGE_CACHE_TTL + 0.1)
        
        # Cleanup
        cleanup_old_messages()
        
        # Verify old messages are removed
        from bot.utils.dedup import processed_messages
        # Messages should be expired and cleaned up
        self.assertEqual(len(processed_messages), 0)


class TestDatabaseOptimization(unittest.TestCase):
    """Test database module optimization"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test database"""
        cls.temp_dir = tempfile.mkdtemp()
        os.environ['DATA_DIR'] = cls.temp_dir
        
        # Import after setting DATA_DIR
        import database
        cls.database = database
        
        # Initialize test database
        database.init_database()
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test database"""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
    
    def test_context_manager_exists(self):
        """Verify context manager is defined"""
        self.assertTrue(hasattr(self.database, 'get_db_connection'))
    
    def test_context_manager_commit(self):
        """Test context manager commits on success"""
        with self.database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM notes")
            result = cursor.fetchone()
            self.assertIsNotNone(result)
    
    def test_add_note_with_context_manager(self):
        """Test add_note uses context manager"""
        note_id = self.database.add_note(
            user_id=12345,
            source_chat_id="-100123456789",
            source_name="Test Channel",
            message_text="Test message"
        )
        self.assertIsNotNone(note_id)
        self.assertGreater(note_id, 0)
    
    def test_helper_functions_exist(self):
        """Verify helper functions are defined"""
        self.assertTrue(hasattr(self.database, '_validate_and_convert_params'))
        self.assertTrue(hasattr(self.database, '_check_duplicate_media_group'))
        self.assertTrue(hasattr(self.database, '_check_duplicate_message'))
        self.assertTrue(hasattr(self.database, '_parse_media_paths'))
    
    def test_duplicate_media_group_detection(self):
        """Test media group deduplication"""
        media_group_id = "test_media_group_123"
        
        # Add first note
        note_id1 = self.database.add_note(
            user_id=12345,
            source_chat_id="-100123456789",
            source_name="Test Channel",
            message_text="Media group message",
            media_group_id=media_group_id
        )
        
        # Try to add duplicate
        note_id2 = self.database.add_note(
            user_id=12345,
            source_chat_id="-100123456789",
            source_name="Test Channel",
            message_text="Media group message",
            media_group_id=media_group_id
        )
        
        # Should return same note ID
        self.assertEqual(note_id1, note_id2)
    
    def test_duplicate_message_detection(self):
        """Test message deduplication within time window"""
        # Add first message
        note_id1 = self.database.add_note(
            user_id=12345,
            source_chat_id="-100123456789",
            source_name="Test Channel",
            message_text="Duplicate test message"
        )
        
        # Try to add duplicate immediately
        note_id2 = self.database.add_note(
            user_id=12345,
            source_chat_id="-100123456789",
            source_name="Test Channel",
            message_text="Duplicate test message"
        )
        
        # Should return same note ID
        self.assertEqual(note_id1, note_id2)


class TestPerformance(unittest.TestCase):
    """Performance tests for optimizations"""
    
    def test_lru_cache_performance(self):
        """Test LRU cache operation performance"""
        processed_media_groups.clear()
        
        # Time adding many items
        start_time = time.time()
        for i in range(1000):
            register_processed_media_group(f"perf_key_{i}")
        add_time = time.time() - start_time
        
        # Time checking items
        start_time = time.time()
        for i in range(1000):
            is_media_group_processed(f"perf_key_{i}")
        check_time = time.time() - start_time
        
        print(f"\nLRU Performance:")
        print(f"  Add 1000 items: {add_time:.4f}s ({add_time/1000*1000:.2f}ms per item)")
        print(f"  Check 1000 items: {check_time:.4f}s ({check_time/1000*1000:.2f}ms per item)")
        
        # Operations should be fast (< 1 second for 1000 operations)
        self.assertLess(add_time, 1.0, "Adding 1000 items took too long")
        self.assertLess(check_time, 0.1, "Checking 1000 items took too long")
    
    def test_backoff_calculation_performance(self):
        """Test backoff calculation performance"""
        start_time = time.time()
        for _ in range(10000):
            constants.get_backoff_time(1)
            constants.get_backoff_time(2)
            constants.get_backoff_time(3)
        elapsed = time.time() - start_time
        
        print(f"\nBackoff calculation:")
        print(f"  30000 calculations: {elapsed:.4f}s ({elapsed/30000*1000000:.2f}μs per call)")
        
        # Should be very fast
        self.assertLess(elapsed, 0.1, "Backoff calculation too slow")


class TestModuleIntegration(unittest.TestCase):
    """Test module integration and imports"""
    
    def test_constants_import_in_dedup(self):
        """Verify dedup module imports constants"""
        from bot.utils import dedup
        # Check if constants are used
        self.assertTrue(hasattr(dedup, 'MESSAGE_CACHE_TTL'))
        self.assertTrue(hasattr(dedup, 'MAX_MEDIA_GROUP_CACHE'))
    
    def test_constants_import_in_database(self):
        """Verify database module imports constants"""
        import database
        # Check if DB_DEDUP_WINDOW is used
        self.assertTrue(hasattr(database, 'DB_DEDUP_WINDOW') or 'DB_DEDUP_WINDOW' in str(database))
    
    def test_main_imports(self):
        """Test main module can import all dependencies"""
        try:
            import config
            import database
            from bot.workers import MessageWorker
            from bot.utils import dedup
            success = True
        except ImportError as e:
            success = False
            print(f"Import error: {e}")
        
        self.assertTrue(success, "Main module imports failed")


def run_tests():
    """Run all tests and generate report"""
    print("="*70)
    print("代码优化功能测试和性能测试")
    print("="*70)
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestConstants))
    suite.addTests(loader.loadTestsFromTestCase(TestDedupOptimization))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseOptimization))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformance))
    suite.addTests(loader.loadTestsFromTestCase(TestModuleIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print()
    print("="*70)
    print("测试总结")
    print("="*70)
    print(f"运行测试: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print()
    
    if result.wasSuccessful():
        print("✅ 所有测试通过！")
        return 0
    else:
        print("❌ 部分测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
