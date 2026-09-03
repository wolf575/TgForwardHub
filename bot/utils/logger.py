"""
日志配置模块 - 统一管理项目日志
保存日志到 data/logs 目录，支持自动轮转
"""
import os
import logging
from logging.handlers import RotatingFileHandler


def setup_logging(log_level=logging.INFO):
    """
    配置项目日志系统

    功能：
    - 日志保存到 data/logs/bot.log
    - 自动轮转（单文件最大10MB，保留5个备份）
    - 同时输出到控制台和文件
    - 文件记录DEBUG级别，控制台记录INFO级别

    Args:
        log_level: 控制台日志级别，默认INFO

    Returns:
        logger: 配置好的logger实例
    """
    # 确保logs目录存在（使用绝对路径，兼容Docker环境）
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    logs_dir = os.path.join(base_dir, 'data', 'logs')
    os.makedirs(logs_dir, exist_ok=True)

    log_file = os.path.join(logs_dir, 'bot.log')

    # 配置日志格式
    log_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 文件处理器（自动轮转，最大10MB，保留5个备份）
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别

    # 控制台处理器（只显示INFO及以上）
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(log_level)

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 清除已有的handlers（避免重复）
    root_logger.handlers.clear()

    # 添加新的handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 创建模块logger
    logger = logging.getLogger(__name__)
    logger.info(f"📝 日志系统已启动")
    logger.info(f"📁 日志文件: {log_file}")
    logger.info(f"💾 日志轮转: 10MB/文件, 保留5个备份")

    return logger


def get_logger(name):
    """
    获取指定名称的logger

    Args:
        name: logger名称，通常使用 __name__

    Returns:
        logger实例
    """
    return logging.getLogger(name)
