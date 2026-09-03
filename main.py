"""
Save-Restricted-Bot - Telegram Bot for Saving Restricted Content
Main entry point - coordinates all modules

职责：
- 初始化日志系统
- 初始化客户端
- 初始化消息队列
- 注册所有处理器
- 初始化数据库
- 打印启动配置
- 启动Bot
"""

# 导入日志配置模块
import time

from bot.utils.logger import setup_logging, get_logger
from config import getenv, load_config

# 初始化日志系统（保存到data/logs目录）
setup_logging()
logger = get_logger(__name__)

# 导入核心模块
from bot.core import (
    initialize_clients,
    initialize_message_queue,
    print_startup_config
)

# 导入处理器注册
from bot.handlers import register_all_handlers

# 导入数据库
from database import init_database

# 导入自动校准调度器
from bot.services.calibration_scheduler import start_scheduler, stop_scheduler


def _has_bot_credentials():
    """检查启动 Bot 所必需的凭据是否已经配置。"""
    data = load_config()
    return bool(
        getenv("TOKEN", data)
        and getenv("ID", data)
        and getenv("HASH", data)
    )


def main():
    """主函数：协调所有模块启动Bot"""
    acc = None

    while not _has_bot_credentials():
        logger.error(
            "Bot Token、API ID 或 API Hash 缺失。请打开 http://服务器IP:10000/setup 完成配置。"
        )
        time.sleep(10)

    try:
        # 1. 初始化客户端
        logger.info("🚀 正在启动 Save-Restricted-Bot...")
        bot, acc = initialize_clients()

        # 2. 初始化消息队列
        message_queue, message_worker = initialize_message_queue(acc)

        # 3. 注册所有处理器
        register_all_handlers(bot, acc, message_queue)

        # 4. 初始化数据库
        logger.info("🔧 正在初始化数据库系统...")
        try:
            init_database()
        except Exception as e:
            logger.error(f"⚠️ 数据库初始化时发生错误: {e}")
            logger.warning("⚠️ 继续启动，但记录模式可能无法工作")

        # 5. 启动自动校准调度器
        logger.info("🔧 正在启动自动校准调度器...")
        try:
            start_scheduler(interval=60)  # 每60秒检查一次
            logger.info("✅ 自动校准调度器已启动")
        except Exception as e:
            logger.error(f"⚠️ 启动校准调度器时出错: {e}")
            logger.warning("⚠️ 继续启动，但自动校准功能可能无法工作")

        # 6. 打印启动配置
        print_startup_config(acc)

        # 7. 启动Bot
        logger.info("🎬 启动Bot主循环...")
        bot.run()

    except KeyboardInterrupt:
        logger.info("\n⚠️ 收到中断信号，正在关闭...")
    except Exception as e:
        logger.error(f"❌ Bot运行时发生错误: {e}", exc_info=True)
    finally:
        # 清理资源
        logger.info("🧹 正在清理资源...")

        # 停止自动校准调度器
        try:
            stop_scheduler()
            logger.info("✅ 自动校准调度器已停止")
        except Exception as e:
            logger.error(f"⚠️ 停止校准调度器时出错: {e}")

        if acc is not None:
            try:
                acc.stop()
                logger.info("✅ User客户端已停止")
            except Exception as e:
                logger.error(f"⚠️ 停止User客户端时出错: {e}")

        logger.info("👋 Bot已关闭")


if __name__ == "__main__":
    main()
