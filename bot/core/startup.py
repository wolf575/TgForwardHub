"""
启动配置打印模块
职责：打印Bot启动信息和配置
"""
import time
from bot.utils.logger import get_logger
from config import load_watch_config, reload_monitored_sources, get_monitored_sources
from bot.services.config_import import import_watch_config_on_startup
from constants import MAX_RETRIES

logger = get_logger(__name__)


def _print_watch_tasks(watch_config):
    """打印配置的监控任务"""
    record_mode_count = sum(
        1 for watches in watch_config.values()
        for watch_data in watches.values()
        if isinstance(watch_data, dict) and watch_data.get("record_mode", False)
    )

    if record_mode_count > 0:
        print(f"🔍 配置的记录模式任务: {record_mode_count} 个\n")

    for user_id, watches in watch_config.items():
        print(f"👤 用户 {user_id}:")
        for watch_key, watch_data in watches.items():
            if isinstance(watch_data, dict):
                source_id = watch_data.get("source", watch_key.split("|")[0] if "|" in watch_key else watch_key)
                dest_id = watch_data.get("dest", "未知")
                record_mode = watch_data.get("record_mode", False)

                source_id = source_id or "未知来源"
                dest_id = dest_id or "未知目标"

                if record_mode:
                    print(f"   📝 {source_id} → 记录模式")
                else:
                    print(f"   📤 {source_id} → {dest_id}")
            else:
                source_display = watch_key or "未知来源"
                dest_display = watch_data or "未知目标"
                print(f"   📤 {source_display} → {dest_display}")
        print()


def print_startup_config(acc):
    """
    打印启动配置信息

    Args:
        acc: User客户端实例（如果为None，部分功能不可用）
    """
    # ⚡ 启动时强制重新加载监控源，确保使用最新配置
    logger.info("🔄 正在加载监控配置...")
    reload_monitored_sources()

    monitored = get_monitored_sources()
    logger.info(f"✅ 启动时已加载 {len(monitored)} 个监控源频道")

    # 配置验证：检查是否有配置但监控源为空
    watch_config = load_watch_config()
    if watch_config and not monitored:
        logger.error("❌ 配置验证失败：watch_config.json 有内容但监控源为空！")
        logger.error("   这可能是配置文件格式错误或数据损坏。")
        logger.error("   建议检查配置文件或重新添加监控任务。")
    elif monitored:
        logger.info(f"📋 监控源列表: {monitored}")

    print("\n" + "=" * 60)
    print("🤖 Telegram Save-Restricted Bot 启动成功")
    print("=" * 60)

    if acc is not None:
        print("\n🔧 消息队列系统已启用")
        print("   - 消息处理模式：队列 + 工作线程")
        print(f"   - 最大重试次数：{MAX_RETRIES} 次")
        print("   - 自动故障恢复：是")

    watch_config = load_watch_config()
    if not watch_config:
        print("\n📋 当前没有监控任务")
    else:
        total_tasks = sum(len(watches) for watches in watch_config.values())
        print(f"\n📋 已加载 {len(watch_config)} 个用户的 {total_tasks} 个监控任务：\n")

        # 打印监控任务
        _print_watch_tasks(watch_config)

        # 启动时自动导入配置 - 复用手动添加的逻辑
        if acc is not None:
            print("")  # 空行分隔
            logger.info("⏳ 等待Session完全建立...")
            time.sleep(8)

            # 使用简化的导入逻辑，复用手动添加的代码路径
            import_watch_config_on_startup(acc)

    print("\n" + "=" * 60)
    print("✅ 机器人已就绪，正在监听消息...")
    print("=" * 60 + "\n")
