# Pyrogram Peer Resolution Error Fix

## Problem
The bot was encountering errors when receiving updates from channels/groups it hasn't joined or doesn't have access to:

```
ValueError: Peer id invalid: -1002169764569
KeyError: 'ID not found: -1002169764569'
```

These errors were occurring in Pyrogram's internal `handle_updates()` method when trying to resolve peer IDs that weren't cached locally or couldn't be fetched from Telegram.

## Solution
Implemented comprehensive error handling in the `auto_forward()` message handler:

### 1. Message Validation
- Added validation checks for message object and its attributes
- Verify chat and chat.id exist before accessing them
- Skip messages with invalid or zero chat IDs

### 2. Peer Resolution Error Handling
- Wrapped `acc.get_chat()` call in try-except blocks
- Specifically catch `ValueError` and `KeyError` exceptions
- Silently skip messages from channels with invalid peer IDs
- Only log errors for unexpected issues (not peer resolution failures)

### 3. Layered Exception Handling
- **Inner try-except**: Catches errors during message processing
  - Silently skips "Peer id invalid" and "ID not found" errors
  - Logs other errors for debugging
  
- **Outer try-except**: Catches errors at the handler level
  - Prevents bot crashes from unhandled exceptions
  - Silently ignores peer resolution errors
  - Logs unexpected errors for investigation

## Benefits
- ✅ Bot no longer crashes when receiving updates from inaccessible channels
- ✅ Reduces console spam from peer resolution errors
- ✅ Maintains functionality for valid channels
- ✅ Better error logging for actual issues
- ✅ More robust and stable operation

## Technical Details
The error was happening because:
1. Pyrogram receives updates from Telegram for channels the bot was previously in
2. When the bot is removed or loses access, the peer ID is no longer cached
3. Pyrogram tries to resolve the peer but fails with ValueError or KeyError
4. The exception was not properly caught, causing "Task exception was never retrieved" errors

The fix ensures all these errors are caught and handled gracefully, allowing the bot to continue processing valid messages without interruption.
