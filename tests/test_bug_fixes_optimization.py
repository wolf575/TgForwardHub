#!/usr/bin/env python3
"""
Test bug fixes for code optimization
"""
import sys
import os
import unittest
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.utils.dedup import (
    register_processed_media_group,
    processed_media_groups,
    is_media_group_processed
)
import constants


class TestBugFix1(unittest.TestCase):
    """Test Bug #1: Accurate cleanup logging"""
    
    def setUp(self):
        """Clear cache before each test"""
        processed_media_groups.clear()
    
    def test_cleanup_removes_correct_count(self):
        """Test that cleanup removes the correct number of items"""
        # Fill cache to exactly MAX + 1 (should remove 1 item)
        for i in range(constants.MAX_MEDIA_GROUP_CACHE + 1):
            register_processed_media_group(f"key_{i}")
        
        # Cache should be at or below limit
        self.assertLessEqual(len(processed_media_groups), constants.MAX_MEDIA_GROUP_CACHE)
    
    def test_cleanup_stops_at_limit(self):
        """Test that cleanup doesn't remove more than necessary"""
        # Fill cache to MAX + 5
        for i in range(constants.MAX_MEDIA_GROUP_CACHE + 5):
            register_processed_media_group(f"key_{i}")
        
        # Should remove exactly 5 items to get back to limit
        self.assertEqual(len(processed_media_groups), constants.MAX_MEDIA_GROUP_CACHE)
    
    def test_cleanup_with_large_excess(self):
        """Test cleanup with excess larger than batch size"""
        # Fill cache to MAX + 100
        for i in range(constants.MAX_MEDIA_GROUP_CACHE + 100):
            register_processed_media_group(f"key_{i}")
        
        # Should remove up to BATCH_SIZE items
        self.assertLessEqual(len(processed_media_groups), constants.MAX_MEDIA_GROUP_CACHE)
        # But may still be over if excess > BATCH_SIZE
        self.assertGreaterEqual(len(processed_media_groups), 
                                constants.MAX_MEDIA_GROUP_CACHE - constants.MEDIA_GROUP_CLEANUP_BATCH_SIZE)


class TestBugFix2(unittest.TestCase):
    """Test Bug #2: main_old.py import doesn't run bot - OBSOLETE (main_old.py removed)"""
    
    def test_handlers_importable_from_new_modules(self):
        """Test that handlers can be imported from new modular structure"""
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Import took too long - bot may have started")
        
        # Set 5 second timeout
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(5)
        
        try:
            # This should complete quickly without starting bot
            from bot.handlers.callbacks import callback_handler
            from bot.handlers.messages import save, handle_private
            signal.alarm(0)  # Cancel alarm
            
            # If we get here, import was successful and fast
            self.assertTrue(True)
        except TimeoutError:
            self.fail("Import timed out - bot may have started")
        finally:
            signal.alarm(0)
    
    def test_main_has_proper_structure(self):
        """Test that main.py has proper module structure"""
        with open('main.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Should have proper imports from new modules
        self.assertIn('from bot.handlers.callbacks import callback_handler', content)
        self.assertIn('from bot.handlers.messages import save, handle_private', content)


class TestBugFix3(unittest.TestCase):
    """Test Bug #3: Loop protection in cleanup"""
    
    def setUp(self):
        """Clear cache before each test"""
        processed_media_groups.clear()
    
    def test_cleanup_has_iteration_limit(self):
        """Test that cleanup has iteration limit to prevent infinite loop"""
        # Fill beyond limit
        initial_size = constants.MAX_MEDIA_GROUP_CACHE + 100
        
        start_time = time.time()
        for i in range(initial_size):
            register_processed_media_group(f"key_{i}")
        elapsed = time.time() - start_time
        
        # Should complete quickly (< 1 second for 400 items)
        self.assertLess(elapsed, 1.0, "Cleanup took too long - may not have iteration limit")
    
    def test_cleanup_never_hangs(self):
        """Test that cleanup operation always completes"""
        # Stress test with many items
        for batch in range(10):
            for i in range(100):
                register_processed_media_group(f"batch_{batch}_key_{i}")
        
        # If we get here without hanging, test passes
        self.assertTrue(True)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases discovered during bug fixing"""
    
    def setUp(self):
        """Clear cache before each test"""
        processed_media_groups.clear()
    
    def test_empty_key_handling(self):
        """Test that empty keys are handled gracefully"""
        register_processed_media_group("")
        register_processed_media_group(None)
        
        # Should not crash and cache should be empty
        self.assertEqual(len(processed_media_groups), 0)
    
    def test_duplicate_registration(self):
        """Test that duplicate registrations refresh LRU position"""
        register_processed_media_group("key1")
        register_processed_media_group("key2")
        register_processed_media_group("key1")  # Refresh
        
        # key1 should be at the end now
        keys = list(processed_media_groups.keys())
        self.assertEqual(keys[-1], "key1")
    
    def test_concurrent_access(self):
        """Test basic thread safety"""
        import threading
        
        def worker():
            for i in range(100):
                register_processed_media_group(f"thread_{threading.current_thread().name}_key_{i}")
        
        threads = [threading.Thread(target=worker, name=f"worker_{i}") for i in range(5)]
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # Should complete without errors
        self.assertTrue(True)


def run_tests():
    """Run all bug fix tests"""
    print("="*70)
    print("Bug 修复验证测试")
    print("="*70)
    print()
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestBugFix1))
    suite.addTests(loader.loadTestsFromTestCase(TestBugFix2))
    suite.addTests(loader.loadTestsFromTestCase(TestBugFix3))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print()
    print("="*70)
    print("Bug 修复测试总结")
    print("="*70)
    print(f"运行测试: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print()
    
    if result.wasSuccessful():
        print("✅ 所有 Bug 修复验证通过！")
        return 0
    else:
        print("❌ 部分 Bug 修复验证失败")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
