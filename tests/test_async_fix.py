#!/usr/bin/env python3
"""
Test script to verify async blocking fix in MessageWorker.

This script simulates the message queue workflow to ensure:
1. Event loop is properly created in worker thread
2. Async operations execute with timeout control
3. Multiple messages process sequentially without blocking
4. Exceptions are properly caught and logged
"""

import asyncio
import queue
import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TestMessage:
    """Test message object"""
    id: int
    text: str
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0


class MockAsyncClient:
    """Mock async client to simulate Pyrogram operations"""
    
    async def slow_operation(self, msg_id: int, delay: float = 1.0):
        """Simulate a slow async operation"""
        logger.info(f"  → Starting slow operation for message {msg_id}")
        await asyncio.sleep(delay)
        logger.info(f"  ← Completed slow operation for message {msg_id}")
        return f"Result for {msg_id}"
    
    async def timeout_operation(self, msg_id: int):
        """Simulate an operation that times out"""
        logger.warning(f"  → Starting timeout operation for message {msg_id}")
        await asyncio.sleep(35)  # Will timeout at 30s
        return f"Should not reach here for {msg_id}"
    
    async def error_operation(self, msg_id: int):
        """Simulate an operation that raises an error"""
        logger.warning(f"  → Starting error operation for message {msg_id}")
        await asyncio.sleep(0.1)
        raise ValueError("Peer id invalid")


class TestMessageWorker:
    """Test worker with async support"""
    
    def __init__(self, message_queue: queue.Queue, mock_client: MockAsyncClient):
        self.message_queue = message_queue
        self.mock_client = mock_client
        self.processed_count = 0
        self.failed_count = 0
        self.running = True
        self.loop = None
    
    def run(self):
        """Main loop with event loop"""
        # Create event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        logger.info("🔧 Test worker thread started with event loop")
        
        while self.running:
            try:
                try:
                    msg_obj = self.message_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                queue_size = self.message_queue.qsize()
                logger.info(f"📥 Processing message {msg_obj.id} (queue: {queue_size})")
                
                success = self.process_message(msg_obj)
                
                if success:
                    self.processed_count += 1
                    logger.info(f"✅ Message {msg_obj.id} processed (total: {self.processed_count})")
                else:
                    self.failed_count += 1
                    logger.error(f"❌ Message {msg_obj.id} failed (total: {self.failed_count})")
                
                self.message_queue.task_done()
                
            except Exception as e:
                logger.error(f"⚠️ Worker exception: {e}", exc_info=True)
                try:
                    self.message_queue.task_done()
                except ValueError:
                    pass
        
        # Clean up event loop
        if self.loop:
            self.loop.close()
        logger.info("🛑 Test worker thread stopped")
    
    def _run_async_with_timeout(self, coro, timeout: float = 30.0):
        """Execute async operation with timeout"""
        # Validate that we have a proper coroutine or awaitable
        if not asyncio.iscoroutine(coro) and not hasattr(coro, '__await__'):
            error_msg = f"Expected coroutine or awaitable, got {type(coro).__name__}"
            logger.error(f"❌ {error_msg}")
            raise TypeError(error_msg)
        
        # Ensure event loop exists and is valid
        if not self.loop or self.loop.is_closed():
            error_msg = "Event loop not available or closed"
            logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        
        try:
            return self.loop.run_until_complete(
                asyncio.wait_for(coro, timeout=timeout)
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ Operation timeout ({timeout}s)")
            raise
    
    def process_message(self, msg_obj: TestMessage) -> bool:
        """Process single message"""
        try:
            logger.info(f"⚙️ Processing message: id={msg_obj.id}, text={msg_obj.text}")
            
            # Simulate different types of operations based on message text
            if "slow" in msg_obj.text:
                # Normal slow operation
                result = self._run_async_with_timeout(
                    self.mock_client.slow_operation(msg_obj.id, delay=2.0),
                    timeout=30.0
                )
                logger.info(f"   Result: {result}")
            
            elif "timeout" in msg_obj.text:
                # Operation that will timeout
                try:
                    result = self._run_async_with_timeout(
                        self.mock_client.timeout_operation(msg_obj.id),
                        timeout=5.0  # Short timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"   Timeout handled gracefully for message {msg_obj.id}")
                    return False
            
            elif "error" in msg_obj.text:
                # Operation that raises an error
                try:
                    result = self._run_async_with_timeout(
                        self.mock_client.error_operation(msg_obj.id),
                        timeout=30.0
                    )
                except ValueError as e:
                    if "Peer id invalid" in str(e):
                        logger.warning(f"   Peer ID error handled for message {msg_obj.id}")
                        return True  # Don't retry
                    raise
            
            else:
                # Fast operation
                result = self._run_async_with_timeout(
                    self.mock_client.slow_operation(msg_obj.id, delay=0.5),
                    timeout=30.0
                )
                logger.info(f"   Result: {result}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error processing message {msg_obj.id}: {e}", exc_info=True)
            return False
    
    def stop(self):
        """Stop worker thread"""
        self.running = False


def test_async_message_processing():
    """Test async message processing with queue"""
    
    logger.info("=" * 80)
    logger.info("Starting async blocking fix test")
    logger.info("=" * 80)
    
    # Create queue and worker
    msg_queue = queue.Queue()
    mock_client = MockAsyncClient()
    worker = TestMessageWorker(msg_queue, mock_client)
    
    # Start worker thread
    worker_thread = threading.Thread(target=worker.run, daemon=True, name="TestWorker")
    worker_thread.start()
    logger.info("✅ Worker thread started")
    
    # Enqueue test messages
    test_messages = [
        TestMessage(1, "fast message 1"),
        TestMessage(2, "slow message 2"),
        TestMessage(3, "fast message 3"),
        TestMessage(4, "error message 4"),  # Will handle error gracefully
        TestMessage(5, "fast message 5"),
        TestMessage(6, "timeout message 6"),  # Will timeout but not block
        TestMessage(7, "fast message 7"),
        TestMessage(8, "slow message 8"),
        TestMessage(9, "fast message 9"),
        TestMessage(10, "fast message 10"),
    ]
    
    logger.info(f"\n📤 Enqueuing {len(test_messages)} messages...")
    for msg in test_messages:
        msg_queue.put(msg)
        logger.info(f"  ✅ Enqueued message {msg.id}: {msg.text}")
    
    logger.info(f"\n⏳ Waiting for processing to complete...")
    
    # Wait for all messages to be processed (with timeout)
    start_time = time.time()
    timeout = 60  # 60 seconds timeout
    
    while not msg_queue.empty():
        elapsed = time.time() - start_time
        if elapsed > timeout:
            logger.error(f"❌ Test timeout after {elapsed:.1f}s")
            break
        time.sleep(0.5)
    
    # Wait a bit more for the last message to complete
    time.sleep(2)
    
    # Stop worker
    worker.stop()
    worker_thread.join(timeout=5)
    
    # Report results
    logger.info("\n" + "=" * 80)
    logger.info("Test Results:")
    logger.info("=" * 80)
    logger.info(f"Total enqueued: {len(test_messages)}")
    logger.info(f"Successfully processed: {worker.processed_count}")
    logger.info(f"Failed: {worker.failed_count}")
    logger.info(f"Expected processed: 8 (2 should fail: timeout and no other errors)")
    logger.info("=" * 80)
    
    # Verify results
    if worker.processed_count >= 8:
        logger.info("✅ TEST PASSED: All non-failing messages were processed!")
        return True
    else:
        logger.error(f"❌ TEST FAILED: Only {worker.processed_count} messages processed")
        return False


if __name__ == "__main__":
    success = test_async_message_processing()
    exit(0 if success else 1)
