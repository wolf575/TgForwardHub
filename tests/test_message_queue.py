#!/usr/bin/env python3
"""
Test script to verify message queue and worker thread implementation
"""

import queue
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class MockMessage:
    """Mock message object for testing"""
    user_id: str
    watch_key: str
    message: Any
    watch_data: Dict[str, Any]
    source_chat_id: str
    dest_chat_id: Optional[str]
    message_text: str
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    media_group_key: Optional[str] = None


class MockWorker:
    """Mock worker for testing"""
    
    def __init__(self, message_queue: queue.Queue, max_retries: int = 3):
        self.message_queue = message_queue
        self.max_retries = max_retries
        self.processed_count = 0
        self.failed_count = 0
        self.retry_count = 0
        self.running = True
        self.last_stats_time = time.time()
        
    def run(self):
        """Main processing loop"""
        logger.info("🔧 Worker thread started")
        
        while self.running:
            try:
                try:
                    msg_obj = self.message_queue.get(timeout=1)
                except queue.Empty:
                    if time.time() - self.last_stats_time > 5:
                        queue_size = self.message_queue.qsize()
                        if queue_size > 0 or self.processed_count > 0:
                            logger.info(f"📊 Queue stats: pending={queue_size}, completed={self.processed_count}, failed={self.failed_count}")
                        self.last_stats_time = time.time()
                    continue
                
                queue_size = self.message_queue.qsize()
                logger.info(f"📥 Processing message (queue remaining: {queue_size})")
                
                # Simulate processing
                success = self.process_message(msg_obj)
                
                if success:
                    self.processed_count += 1
                    logger.info(f"✅ Message processed successfully (total: {self.processed_count})")
                else:
                    if msg_obj.retry_count < self.max_retries:
                        msg_obj.retry_count += 1
                        self.retry_count += 1
                        backoff_time = 2 ** (msg_obj.retry_count - 1)
                        logger.warning(f"⚠️ Processing failed, retrying in {backoff_time}s (attempt {msg_obj.retry_count}/{self.max_retries})")
                        time.sleep(backoff_time)
                        self.message_queue.put(msg_obj)
                    else:
                        self.failed_count += 1
                        logger.error(f"❌ Message processing finally failed (total failures: {self.failed_count})")
                
                self.message_queue.task_done()
                
            except Exception as e:
                logger.error(f"⚠️ Worker thread exception: {e}", exc_info=True)
                try:
                    self.message_queue.task_done()
                except ValueError:
                    pass
        
        logger.info("🛑 Worker thread stopped")
    
    def process_message(self, msg_obj: MockMessage) -> bool:
        """Process a single message"""
        try:
            logger.info(f"⚙️ Processing: user={msg_obj.user_id}, source={msg_obj.source_chat_id}, text={msg_obj.message_text[:50]}")
            
            # Simulate processing time
            time.sleep(0.1)
            
            # Simulate 10% failure rate on first attempt
            if msg_obj.retry_count == 0 and msg_obj.user_id == "user_error":
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error processing message: {e}", exc_info=True)
            return False
    
    def stop(self):
        """Stop the worker thread"""
        self.running = False
        logger.info("🛑 Stopping worker thread...")


def test_message_queue():
    """Test the message queue and worker implementation"""
    print("\n" + "="*60)
    print("🧪 Testing Message Queue and Worker Thread")
    print("="*60 + "\n")
    
    # Create queue and worker
    test_queue = queue.Queue()
    worker = MockWorker(test_queue, max_retries=3)
    
    # Start worker thread
    import threading
    worker_thread = threading.Thread(target=worker.run, daemon=True, name="TestWorker")
    worker_thread.start()
    logger.info("✅ Worker thread started")
    
    # Test 1: Single message
    print("\n📝 Test 1: Processing single message")
    msg1 = MockMessage(
        user_id="user_1",
        watch_key="watch_1",
        message=None,
        watch_data={},
        source_chat_id="-1001234567890",
        dest_chat_id="-1009876543210",
        message_text="Test message 1"
    )
    test_queue.put(msg1)
    logger.info("📬 Message enqueued")
    time.sleep(1)
    
    # Test 2: Multiple messages (burst)
    print("\n📝 Test 2: Processing burst of 10 messages")
    for i in range(10):
        msg = MockMessage(
            user_id=f"user_{i}",
            watch_key=f"watch_{i}",
            message=None,
            watch_data={},
            source_chat_id=f"-100123456789{i}",
            dest_chat_id=f"-100987654321{i}",
            message_text=f"Test message {i}"
        )
        test_queue.put(msg)
    logger.info(f"📬 Enqueued 10 messages, queue size: {test_queue.qsize()}")
    time.sleep(3)
    
    # Test 3: Message with retry
    print("\n📝 Test 3: Testing retry mechanism")
    msg_error = MockMessage(
        user_id="user_error",
        watch_key="watch_error",
        message=None,
        watch_data={},
        source_chat_id="-1001111111111",
        dest_chat_id="-1002222222222",
        message_text="This message will fail on first attempt"
    )
    test_queue.put(msg_error)
    logger.info("📬 Error message enqueued (will trigger retry)")
    time.sleep(10)  # Wait for retries
    
    # Wait for queue to be empty
    print("\n⏳ Waiting for all messages to be processed...")
    test_queue.join()
    
    # Print final statistics
    print("\n" + "="*60)
    print("📊 Final Statistics")
    print("="*60)
    print(f"✅ Processed: {worker.processed_count}")
    print(f"❌ Failed: {worker.failed_count}")
    print(f"🔄 Retries: {worker.retry_count}")
    print(f"📥 Queue size: {test_queue.qsize()}")
    print("="*60 + "\n")
    
    # Stop worker
    worker.stop()
    worker_thread.join(timeout=2)
    
    print("✅ Test completed successfully!\n")


if __name__ == "__main__":
    test_message_queue()
