"""
Progress tracking utilities for downloads/uploads
"""
import os
import time
import pyrogram
import logging

logger = logging.getLogger(__name__)

# Constants
FILE_WAIT_TIMEOUT = 30  # seconds
STATUS_UPDATE_INTERVAL = 10  # seconds


def downstatus(statusfile: str, message: pyrogram.types.messages_and_media.message.Message, bot):
    """Monitor and update download status
    
    Args:
        statusfile: Path to status file
        message: Telegram message to update
        bot: Pyrogram bot client
    """
    # Wait for status file with timeout
    timeout = FILE_WAIT_TIMEOUT
    start_time = time.time()
    
    while True:
        if os.path.exists(statusfile):
            break
        if time.time() - start_time > timeout:
            logger.warning(f"⚠️ 等待下载状态文件超时: {statusfile}")
            return
        time.sleep(0.1)

    time.sleep(3)
    
    try:
        while os.path.exists(statusfile):
            try:
                with open(statusfile, "r", encoding="utf-8") as downread:
                    txt = downread.read().strip()
                
                if txt:  # Only update if file has content
                    try:
                        bot.edit_message_text(
                            message.chat.id, 
                            message.id, 
                            f"__⬇️ 已下载__ : **{txt}**"
                        )
                    except Exception as e:
                        logger.debug(f"更新下载状态消息失败: {e}")
                
                time.sleep(STATUS_UPDATE_INTERVAL)
                
            except IOError as e:
                logger.warning(f"读取下载状态文件失败: {e}")
                time.sleep(5)
            except Exception as e:
                logger.error(f"下载状态更新异常: {e}")
                time.sleep(5)
    finally:
        # Clean up status file
        try:
            if os.path.exists(statusfile):
                os.remove(statusfile)
                logger.debug(f"已清理下载状态文件: {statusfile}")
        except Exception as e:
            logger.warning(f"清理下载状态文件失败: {e}")


def upstatus(statusfile: str, message: pyrogram.types.messages_and_media.message.Message, bot):
    """Monitor and update upload status
    
    Args:
        statusfile: Path to status file
        message: Telegram message to update
        bot: Pyrogram bot client
    """
    # Wait for status file with timeout
    timeout = FILE_WAIT_TIMEOUT
    start_time = time.time()
    
    while True:
        if os.path.exists(statusfile):
            break
        if time.time() - start_time > timeout:
            logger.warning(f"⚠️ 等待上传状态文件超时: {statusfile}")
            return
        time.sleep(0.1)

    time.sleep(3)
    
    try:
        while os.path.exists(statusfile):
            try:
                with open(statusfile, "r", encoding="utf-8") as upread:
                    txt = upread.read().strip()
                
                if txt:  # Only update if file has content
                    try:
                        bot.edit_message_text(
                            message.chat.id, 
                            message.id, 
                            f"__⬆️ 已上传__ : **{txt}**"
                        )
                    except Exception as e:
                        logger.debug(f"更新上传状态消息失败: {e}")
                
                time.sleep(STATUS_UPDATE_INTERVAL)
                
            except IOError as e:
                logger.warning(f"读取上传状态文件失败: {e}")
                time.sleep(5)
            except Exception as e:
                logger.error(f"上传状态更新异常: {e}")
                time.sleep(5)
    finally:
        # Clean up status file
        try:
            if os.path.exists(statusfile):
                os.remove(statusfile)
                logger.debug(f"已清理上传状态文件: {statusfile}")
        except Exception as e:
            logger.warning(f"清理上传状态文件失败: {e}")


def progress(current: int, total: int, message: pyrogram.types.messages_and_media.message.Message, type: str):
    """Write progress to status file
    
    Args:
        current: Current bytes transferred
        total: Total bytes to transfer
        message: Telegram message
        type: Transfer type ('down' or 'up')
        
    Note:
        This function is designed to be called as a callback during file transfers.
        It writes progress percentage to a temporary status file.
    """
    if not message or not hasattr(message, 'chat') or not hasattr(message, 'id'):
        logger.warning("⚠️ progress: 无效的message对象")
        return
    
    statusfile = f'{type}status{str(message.chat.id)}{str(message.id)}.txt'
    
    try:
        # Calculate percentage, handle division by zero
        if total > 0:
            percentage = current * 100 / total
        else:
            percentage = 0.0
        
        # Write to status file
        with open(statusfile, "w", encoding="utf-8") as fileup:
            fileup.write(f"{percentage:.1f}%")
            
    except ZeroDivisionError:
        # Should not happen due to check above, but add as safety net
        logger.error(f"❌ progress: 除零错误 (total={total})")
        with open(statusfile, "w", encoding="utf-8") as fileup:
            fileup.write("0.0%")
            
    except IOError as e:
        logger.error(f"❌ progress: 写入状态文件失败: {e}")
        
    except Exception as e:
        logger.error(f"❌ progress: 未预期的错误: {e}")
