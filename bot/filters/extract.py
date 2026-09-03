"""
Content extraction using regex patterns
"""
import re
import logging
from typing import List

logger = logging.getLogger(__name__)


def extract_content(message_text: str, extract_patterns: List[str]) -> str:
    """Extract content from message using regex patterns

    Args:
        message_text: Message text to extract from
        extract_patterns: List of regex patterns for extraction

    Returns:
        Extracted content as newline-separated string, or empty string if nothing extracted
    """
    if not extract_patterns:
        return message_text  # No extraction patterns, return original text

    logger.debug(f"   应用提取模式: {extract_patterns}")
    extracted_content = []

    for pattern in extract_patterns:
        try:
            matches = re.findall(pattern, message_text)
            if matches:
                # Handle both simple matches and groups
                if isinstance(matches[0], tuple):
                    for match_group in matches:
                        extracted_content.extend(match_group)
                else:
                    extracted_content.extend(matches)
                logger.debug(f"   提取到内容: {len(matches)} 个匹配")
        except re.error as e:
            logger.warning(f"   正则表达式错误: {pattern} - {e}")

    if extracted_content:
        # Check if this is magnet link extraction
        is_magnet = any('magnet:' in str(item) for item in extracted_content)

        if is_magnet:
            # 提取基础DN文本（从消息开头到第一个#号）
            hash_pos = message_text.find('#')
            base_dn_text = message_text[:hash_pos].rstrip() if hash_pos != -1 else message_text.rstrip()

            processed = []
            magnet_count = 0

            for item in extracted_content:
                magnet_link = str(item).rstrip()

                # Check if dn parameter is missing
                if '&dn=' not in magnet_link and '?dn=' not in magnet_link:
                    if base_dn_text and base_dn_text != magnet_link:
                        magnet_count += 1

                        # 如果有多条磁力链接，在DN结尾添加序号区分
                        if len(extracted_content) > 1:
                            dn_text = f"{base_dn_text}-{magnet_count}"
                        else:
                            dn_text = base_dn_text

                        # 直接使用原始文字，不进行URL编码
                        magnet_link += f'&dn={dn_text}'
                        logger.debug(f"   补全DN [{magnet_count}]: {dn_text[:30]}...")

                processed.append(magnet_link)

            result = "\n".join(set(processed))
        else:
            result = "\n".join(set(extracted_content))

        logger.debug(f"   提取后内容长度: {len(result)}")
        return result
    else:
        logger.debug(f"   未提取到任何内容")
        return ""
