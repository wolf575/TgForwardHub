#!/usr/bin/env python3
"""
Test script for regex filtering and extraction functionality
"""

import re

def test_keyword_filter():
    print("=== Testing Keyword Filters ===")
    
    message_text = "This is an important announcement about the event"
    
    # Test whitelist
    whitelist = ["important", "urgent"]
    result = any(keyword.lower() in message_text.lower() for keyword in whitelist)
    print(f"Whitelist test (should pass): {result}")
    assert result == True
    
    # Test blacklist
    blacklist = ["spam", "ad"]
    result = any(keyword.lower() in message_text.lower() for keyword in blacklist)
    print(f"Blacklist test (should pass): {result}")
    assert result == False
    
    print("✅ Keyword filter tests passed\n")

def test_regex_filter():
    print("=== Testing Regex Filters ===")
    
    message_text = "Check out https://example.com and call 123456"
    
    # Test regex whitelist
    whitelist_regex = [r"https?://[^\s]+", r"\d{6,}"]
    match_found = False
    for pattern in whitelist_regex:
        if re.search(pattern, message_text):
            match_found = True
            break
    print(f"Regex whitelist test (should find match): {match_found}")
    assert match_found == True
    
    # Test regex blacklist
    blacklist_regex = [r"广告|推广"]
    skip_message = False
    for pattern in blacklist_regex:
        if re.search(pattern, message_text):
            skip_message = True
            break
    print(f"Regex blacklist test (should not match): {skip_message}")
    assert skip_message == False
    
    print("✅ Regex filter tests passed\n")

def test_extract_mode():
    print("=== Testing Extract Mode ===")
    
    message_text = "Visit https://example.com and https://test.org. Code: 123456 and 789012"
    
    # Test extraction with multiple patterns
    extract_patterns = [r"https?://[^\s]+", r"\d{6}"]
    extracted_content = []
    
    for pattern in extract_patterns:
        matches = re.findall(pattern, message_text)
        if matches:
            if isinstance(matches[0], tuple):
                for match_group in matches:
                    extracted_content.extend(match_group)
            else:
                extracted_content.extend(matches)
    
    print(f"Extracted content: {extracted_content}")
    assert "https://example.com" in extracted_content
    assert any("https://test.org" in item for item in extracted_content)
    assert "123456" in extracted_content
    assert "789012" in extracted_content
    
    # Test deduplication
    extracted_text = "\n".join(set(extracted_content))
    print(f"Final extracted text:\n{extracted_text}")
    
    print("✅ Extract mode tests passed\n")

def test_combined_filters():
    print("=== Testing Combined Filters ===")
    
    message_text = "Important: https://example.com - Code 123456"
    
    # All filters
    whitelist = ["important"]
    blacklist = ["spam"]
    whitelist_regex = [r"https?://"]
    blacklist_regex = [r"广告"]
    
    # Check all filters
    passed = True
    
    # Keyword whitelist
    if whitelist:
        if not any(keyword.lower() in message_text.lower() for keyword in whitelist):
            passed = False
            print("Failed keyword whitelist")
    
    # Keyword blacklist
    if blacklist:
        if any(keyword.lower() in message_text.lower() for keyword in blacklist):
            passed = False
            print("Failed keyword blacklist")
    
    # Regex whitelist
    if whitelist_regex:
        match_found = False
        for pattern in whitelist_regex:
            if re.search(pattern, message_text):
                match_found = True
                break
        if not match_found:
            passed = False
            print("Failed regex whitelist")
    
    # Regex blacklist
    if blacklist_regex:
        skip_message = False
        for pattern in blacklist_regex:
            if re.search(pattern, message_text):
                skip_message = True
                break
        if skip_message:
            passed = False
            print("Failed regex blacklist")
    
    print(f"Combined filter test result: {passed}")
    assert passed == True
    
    print("✅ Combined filter tests passed\n")

if __name__ == "__main__":
    print("Starting regex and extraction tests...\n")
    
    test_keyword_filter()
    test_regex_filter()
    test_extract_mode()
    test_combined_filters()
    
    print("=" * 50)
    print("✅ All tests passed successfully!")
    print("=" * 50)
