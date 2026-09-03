"""
消息队列管理模块
职责：初始化消息队列和工作线程
"""
import queue
import threading
from bot.utils.logger import get_logger
from bot.workers import MessageWorker
from constants import MAX_RETRIES

logger = get_logger(__name__)


def initialize_message_queue(acc):
    """
    初始化消息队列和工作线程

    Args:
        acc: User客户端实例（如果为None，则不初始化队列）

    Returns:
        tuple: (message_queue, message_worker)
            - message_queue: 消息队列实例
            - message_worker: 消息工作线程实例
            如果acc为None，返回 (None, None)
    """
    if acc is None:
        logger.warning("⚠️ User客户端未初始化，跳过消息队列初始化")
        return None, None

    logger.info("📬 正在初始化消息队列系统...")

    # 创建消息队列
    message_queue = queue.Queue()

    # 创建消息工作线程
    message_worker = MessageWorker(message_queue, acc, max_retries=MAX_RETRIES)
    worker_thread = threading.Thread(
        target=message_worker.run,
        daemon=True,
        name="MessageWorker"
    )

    # 启动工作线程
    worker_thread.start()

    logger.info("✅ 消息队列系统初始化完成")
    logger.info(f"   - 最大重试次数: {MAX_RETRIES}")
    logger.info(f"   - 工作线程: {worker_thread.name}")

    return message_queue, message_worker
