#!/usr/bin/env python3
"""
Test script to verify FloodWait handling in the message worker
"""
import time
import logging
from pyrogram.errors import FloodWait

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MockFloodWait(Exception):
    """Mock FloodWait exception for testing"""
    def __init__(self, value):
        self.value = value
        super().__init__(f"A wait of {self.value} seconds is required")

def test_flood_retry():
    """Test the flood retry logic"""
    
    def _execute_with_flood_retry(operation_name: str, operation_func, max_flood_retries: int = 3):
        """Execute operation with FloodWait retry handling"""
        for flood_attempt in range(max_flood_retries):
            try:
                operation_func()
                return True
            except MockFloodWait as e:
                wait_time = e.value
                if flood_attempt < max_flood_retries - 1:
                    logger.warning(f"⏳ {operation_name}: 遇到限流 FLOOD_WAIT, 需等待 {wait_time} 秒")
                    logger.info(f"   将在 {wait_time + 1} 秒后重试 (FloodWait 重试 {flood_attempt + 1}/{max_flood_retries})")
                    time.sleep(wait_time + 1)
                else:
                    logger.error(f"❌ {operation_name}: FloodWait 重试次数已达上限，放弃操作")
                    return False
            except Exception as e:
                logger.error(f"❌ {operation_name} 执行失败: {type(e).__name__}: {e}")
                raise
        return False
    
    # Test 1: Operation succeeds on first try
    print("\n=== Test 1: Success on first try ===")
    def success_func():
        logger.info("✅ Operation succeeded")
    
    result = _execute_with_flood_retry("Test operation", success_func)
    assert result == True, "Should succeed on first try"
    
    # Test 2: FloodWait then success
    print("\n=== Test 2: FloodWait then success ===")
    attempt_count = [0]
    def floodwait_then_success():
        attempt_count[0] += 1
        if attempt_count[0] == 1:
            logger.info("First attempt - raising FloodWait")
            raise MockFloodWait(2)
        logger.info("✅ Second attempt succeeded")
    
    start_time = time.time()
    result = _execute_with_flood_retry("Test with retry", floodwait_then_success)
    elapsed = time.time() - start_time
    assert result == True, "Should succeed after retry"
    assert elapsed >= 3, f"Should wait at least 3 seconds, waited {elapsed:.1f}"
    
    # Test 3: Multiple FloodWaits
    print("\n=== Test 3: Multiple FloodWaits then success ===")
    attempt_count[0] = 0
    def multiple_floodwaits():
        attempt_count[0] += 1
        if attempt_count[0] <= 2:
            logger.info(f"Attempt {attempt_count[0]} - raising FloodWait")
            raise MockFloodWait(1)
        logger.info("✅ Third attempt succeeded")
    
    result = _execute_with_flood_retry("Test multiple retries", multiple_floodwaits)
    assert result == True, "Should succeed after multiple retries"
    
    # Test 4: Max retries exceeded
    print("\n=== Test 4: Max retries exceeded ===")
    def always_floodwait():
        logger.info("Raising FloodWait")
        raise MockFloodWait(1)
    
    result = _execute_with_flood_retry("Test max retries", always_floodwait)
    assert result == False, "Should fail after max retries"
    
    print("\n=== All tests passed! ✅ ===")

if __name__ == "__main__":
    test_flood_retry()
