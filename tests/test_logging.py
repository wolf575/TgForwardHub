#!/usr/bin/env python3
"""
日志系统测试脚本
用于验证日志配置是否正常工作
"""
from bot.utils.logger import setup_logging, get_logger

# 初始化日志系统
setup_logging()
logger = get_logger(__name__)

def test_logging():
    """测试各个日志级别"""
    print("\n" + "="*50)
    print("开始测试日志系统...")
    print("="*50 + "\n")

    # 测试各个级别
    logger.debug("🔍 这是DEBUG级别日志 - 只在文件中可见")
    logger.info("ℹ️  这是INFO级别日志 - 控制台和文件都可见")
    logger.warning("⚠️  这是WARNING级别日志 - 警告信息")
    logger.error("❌ 这是ERROR级别日志 - 错误信息")

    # 测试异常日志
    try:
        result = 1 / 0
    except Exception as e:
        logger.exception("💥 这是EXCEPTION日志 - 包含完整堆栈追踪")

    print("\n" + "="*50)
    print("✅ 日志测试完成！")
    print("="*50)
    print("\n📁 日志文件位置: data/logs/bot.log")
    print("\n请检查：")
    print("  1. 控制台是否显示INFO及以上级别的日志")
    print("  2. data/logs/bot.log 文件是否包含所有级别的日志")
    print("  3. 日志格式是否包含文件名和行号")
    print("\n查看日志文件：")
    print("  cat data/logs/bot.log")
    print("  tail -f data/logs/bot.log")
    print("\n")

if __name__ == "__main__":
    test_logging()
