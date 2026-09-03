#!/usr/bin/env python3
"""
Test script to verify async validation fix in MessageWorker.

This script tests the specific fix for TypeError: An asyncio.Future, a coroutine or an awaitable is required
"""

import asyncio
import logging
from test_async_fix import TestMessageWorker, MockAsyncClient
import queue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_non_coroutine_validation():
    """Test that non-coroutine inputs are properly validated"""
    
    logger.info("=" * 80)
    logger.info("Testing async validation (TypeError prevention)")
    logger.info("=" * 80)
    
    # Create worker
    msg_queue = queue.Queue()
    mock_client = MockAsyncClient()
    worker = TestMessageWorker(msg_queue, mock_client)
    
    # Manually initialize event loop
    worker.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(worker.loop)
    
    test_results = []
    
    # Test 1: Valid coroutine (should succeed)
    logger.info("\n📝 Test 1: Valid coroutine")
    try:
        result = worker._run_async_with_timeout(
            mock_client.slow_operation(1, delay=0.1),
            timeout=5.0
        )
        logger.info(f"✅ Test 1 PASSED: Valid coroutine executed successfully")
        test_results.append(True)
    except Exception as e:
        logger.error(f"❌ Test 1 FAILED: {e}")
        test_results.append(False)
    
    # Test 2: Non-coroutine input (should raise TypeError with clear message)
    logger.info("\n📝 Test 2: Non-coroutine input (should raise TypeError)")
    try:
        result = worker._run_async_with_timeout(
            "not a coroutine",  # This will trigger TypeError
            timeout=5.0
        )
        logger.error(f"❌ Test 2 FAILED: Should have raised TypeError")
        test_results.append(False)
    except TypeError as e:
        if "coroutine" in str(e).lower() or "awaitable" in str(e).lower():
            logger.info(f"✅ Test 2 PASSED: TypeError raised with message: {e}")
            test_results.append(True)
        else:
            logger.error(f"❌ Test 2 FAILED: Wrong TypeError message: {e}")
            test_results.append(False)
    except Exception as e:
        logger.error(f"❌ Test 2 FAILED: Wrong exception type: {type(e).__name__}: {e}")
        test_results.append(False)
    
    # Test 3: None input (should raise TypeError)
    logger.info("\n📝 Test 3: None input (should raise TypeError)")
    try:
        result = worker._run_async_with_timeout(
            None,  # This will trigger TypeError
            timeout=5.0
        )
        logger.error(f"❌ Test 3 FAILED: Should have raised TypeError")
        test_results.append(False)
    except TypeError as e:
        logger.info(f"✅ Test 3 PASSED: TypeError raised for None input: {e}")
        test_results.append(True)
    except Exception as e:
        logger.error(f"❌ Test 3 FAILED: Wrong exception type: {type(e).__name__}: {e}")
        test_results.append(False)
    
    # Test 4: Integer input (should raise TypeError)
    logger.info("\n📝 Test 4: Integer input (should raise TypeError)")
    try:
        result = worker._run_async_with_timeout(
            42,  # This will trigger TypeError
            timeout=5.0
        )
        logger.error(f"❌ Test 4 FAILED: Should have raised TypeError")
        test_results.append(False)
    except TypeError as e:
        logger.info(f"✅ Test 4 PASSED: TypeError raised for integer input: {e}")
        test_results.append(True)
    except Exception as e:
        logger.error(f"❌ Test 4 FAILED: Wrong exception type: {type(e).__name__}: {e}")
        test_results.append(False)
    
    # Test 5: Timeout handling (should raise TimeoutError)
    logger.info("\n📝 Test 5: Timeout handling")
    try:
        result = worker._run_async_with_timeout(
            mock_client.timeout_operation(5),
            timeout=1.0  # Very short timeout
        )
        logger.error(f"❌ Test 5 FAILED: Should have raised TimeoutError")
        test_results.append(False)
    except asyncio.TimeoutError:
        logger.info(f"✅ Test 5 PASSED: TimeoutError raised correctly")
        test_results.append(True)
    except Exception as e:
        logger.error(f"❌ Test 5 FAILED: Wrong exception type: {type(e).__name__}: {e}")
        test_results.append(False)
    
    # Test 6: Closed event loop (should raise RuntimeError)
    logger.info("\n📝 Test 6: Closed event loop (should raise RuntimeError)")
    worker.loop.close()
    try:
        result = worker._run_async_with_timeout(
            mock_client.slow_operation(6, delay=0.1),
            timeout=5.0
        )
        logger.error(f"❌ Test 6 FAILED: Should have raised RuntimeError")
        test_results.append(False)
    except RuntimeError as e:
        if "loop" in str(e).lower():
            logger.info(f"✅ Test 6 PASSED: RuntimeError raised for closed loop: {e}")
            test_results.append(True)
        else:
            logger.error(f"❌ Test 6 FAILED: Wrong RuntimeError message: {e}")
            test_results.append(False)
    except Exception as e:
        logger.error(f"❌ Test 6 FAILED: Wrong exception type: {type(e).__name__}: {e}")
        test_results.append(False)
    
    # Report results
    logger.info("\n" + "=" * 80)
    logger.info("Test Results Summary:")
    logger.info("=" * 80)
    logger.info(f"Total tests: {len(test_results)}")
    logger.info(f"Passed: {sum(test_results)}")
    logger.info(f"Failed: {len(test_results) - sum(test_results)}")
    logger.info("=" * 80)
    
    if all(test_results):
        logger.info("✅ ALL TESTS PASSED: Async validation is working correctly!")
        return True
    else:
        logger.error(f"❌ SOME TESTS FAILED: {len(test_results) - sum(test_results)} test(s) failed")
        return False


if __name__ == "__main__":
    success = test_non_coroutine_validation()
    exit(0 if success else 1)
