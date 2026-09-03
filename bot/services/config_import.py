"""
配置导入模块
职责：在启动时导入监控配置
"""
import time
from bot.utils.logger import get_logger
from config import load_watch_config
from bot.services.peer_cache import initialize_peer_cache_on_startup_with_retry

logger = get_logger(__name__)


def import_watch_config_on_startup(acc):
    """
    在启动时导入配置，并初始化Peer缓存

    该函数会：
    1. 加载监控配置
    2. 自动初始化所有配置的Peer（包括Bot）
    3. 对于Bot用户，自动发送/start命令建立连接

    Args:
        acc: User客户端实例

    Returns:
        bool: 成功导入至少一个配置返回True，否则返回False
    """
    logger.info("=" * 60)
    logger.info("🔄 开始导入监控配置...")
    logger.info("=" * 60)

    try:
        watch_config = load_watch_config()

        if not watch_config:
            logger.info("📭 没有监控配置需要导入")
            return True

        # 统计配置数量
        total_configs = sum(len(watches) for watches in watch_config.values())
        logger.info(f"📋 找到 {total_configs} 个监控配置")

        success_count = 0
        failed_count = 0

        for user_id, watches in watch_config.items():
            logger.info(f"\n👤 用户 {user_id} 的配置:")

            for watch_key, watch_data in watches.items():
                try:
                    # 解析配置
                    if isinstance(watch_data, dict):
                        source_id = watch_data.get("source")
                        dest_id = watch_data.get("dest")
                        record_mode = watch_data.get("record_mode", False)
                    else:
                        # 旧格式兼容
                        source_id = watch_key
                        dest_id = watch_data
                        record_mode = False

                    # 记录配置信息
                    if source_id and source_id != "me":
                        logger.info(f"   📌 源频道: {source_id}")

                    if not record_mode and dest_id and dest_id != "me":
                        logger.info(f"   📌 目标频道: {dest_id}")
                    elif record_mode:
                        logger.info(f"   📝 目标: 记录模式")

                    success_count += 1

                except Exception as e:
                    logger.error(f"   ❌ 配置导入失败 {watch_key}: {str(e)}")
                    failed_count += 1

                # 避免触发限流，添加小延迟
                time.sleep(0.2)

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"✅ 配置导入完成: {success_count}/{total_configs} 成功")

        if failed_count > 0:
            logger.warning(f"⚠️ {failed_count} 个配置初始化失败")

        logger.info("=" * 60)
        logger.info("")

        # 初始化所有Peer缓存（包括自动处理Bot）
        logger.info("🔧 开始初始化Peer缓存...")
        initialize_peer_cache_on_startup_with_retry(acc, max_retries=3)

        return success_count > 0

    except Exception as e:
        logger.error(f"❌ 导入配置时发生错误: {e}", exc_info=True)
        return False
