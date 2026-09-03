"""
Regex-based filtering
"""
import re
import logging
from typing import List

logger = logging.getLogger(__name__)


def check_whitelist_regex(message_text: str, whitelist_regex: List[str]) -> bool:
    """Check if message matches regex whitelist
    
    Args:
        message_text: Message text to check
        whitelist_regex: List of regex patterns that should match
        
    Returns:
        True if message passes (matches at least one pattern), False otherwise
    """
    if not whitelist_regex:
        return True  # No whitelist means pass all
    
    for pattern in whitelist_regex:
        try:
            if re.search(pattern, message_text):
                return True
        except re.error as e:
            logger.warning(f"   ⚠️ 正则白名单表达式错误 '{pattern}': {e}")
    
    logger.debug(f"   ⏭ 过滤：未匹配正则白名单 {whitelist_regex}")
    return False


def check_blacklist_regex(message_text: str, blacklist_regex: List[str]) -> bool:
    """Check if message matches regex blacklist
    
    Args:
        message_text: Message text to check
        blacklist_regex: List of regex patterns that should NOT match
        
    Returns:
        True if message should be blocked (matches a pattern), False otherwise
    """
    if not blacklist_regex:
        return False  # No blacklist means nothing to block
    
    for pattern in blacklist_regex:
        try:
            if re.search(pattern, message_text):
                logger.debug(f"   ⏭ 过滤：匹配到正则黑名单 '{pattern}'")
                return True
        except re.error as e:
            logger.warning(f"   ⚠️ 正则黑名单表达式错误 '{pattern}': {e}")
    
    return False
