"""
Bot核心模块
包含客户端初始化、消息队列、启动配置等核心功能
"""
from .client import initialize_clients
from .queue import initialize_message_queue
from .startup import print_startup_config

__all__ = [
    'initialize_clients',
    'initialize_message_queue',
    'print_startup_config',
]
