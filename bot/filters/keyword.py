"""
Keyword-based filtering
"""
import logging
from typing import List

logger = logging.getLogger(__name__)


def check_whitelist(message_text: str, whitelist: List[str]) -> bool:
    """Check if message matches keyword whitelist

    Args:
        message_text: Message text to check
        whitelist: List of keywords that should be present

    Returns:
        True if message passes (matches at least one keyword), False otherwise
    """
    if not whitelist:
        return True  # No whitelist means pass all

    for keyword in whitelist:
        if keyword.lower() in message_text.lower():
            logger.info(f"   ✅ 匹配到白名单关键词: '{keyword}'")
            return True

    logger.warning(f"   ⏭ 过滤：未匹配关键词白名单 {whitelist}")
    logger.warning(f"   消息文本: {message_text[:200] if message_text else '(空)'}")
    return False


def check_blacklist(message_text: str, blacklist: List[str]) -> bool:
    """Check if message matches keyword blacklist
    
    Args:
        message_text: Message text to check
        blacklist: List of keywords that should NOT be present
        
    Returns:
        True if message should be blocked (matches a blacklist keyword), False otherwise
    """
    if not blacklist:
        return False  # No blacklist means nothing to block
    
    for keyword in blacklist:
        if keyword.lower() in message_text.lower():
            logger.debug(f"   ⏭ 过滤：匹配到关键词黑名单 '{keyword}'")
            return True
    
    return False
