"""
Global bot and acc instances management
Separated to avoid circular imports
"""
import asyncio
import time

# Store bot and acc instances for use by handlers
_bot_instance = None
_acc_instance = None
_bot_update_count = 0
_bot_last_update_at = None
_bot_command_count = 0
_bot_last_command = None
_bot_last_command_at = None
_bot_last_command_error = None
_bot_last_command_chat_id = None
_bot_last_command_reply_id = None


def set_bot_instance(bot):
    """Set the bot instance for handlers"""
    global _bot_instance
    _bot_instance = bot


def set_acc_instance(acc):
    """Set the acc instance for handlers"""
    global _acc_instance
    _acc_instance = acc


def get_bot_instance():
    """Get the bot instance"""
    return _bot_instance


def get_acc_instance():
    """Get the acc instance"""
    return _acc_instance


def record_bot_update():
    """Record that the Bot dispatcher received a Telegram update."""
    global _bot_update_count, _bot_last_update_at
    _bot_update_count += 1
    _bot_last_update_at = time.time()


def get_bot_update_stats():
    """Return non-sensitive Bot update activity for diagnostics."""
    return {
        "count": _bot_update_count,
        "last_update_at": _bot_last_update_at,
    }


def record_bot_command(
    command,
    error=None,
    chat_id=None,
    reply_message_id=None,
):
    """Record command-handler activity without logging message contents."""
    global _bot_command_count, _bot_last_command
    global _bot_last_command_at, _bot_last_command_error
    global _bot_last_command_chat_id, _bot_last_command_reply_id
    _bot_command_count += 1
    _bot_last_command = str(command)
    _bot_last_command_at = time.time()
    _bot_last_command_error = (
        str(error)[:300] if error is not None else None
    )
    _bot_last_command_chat_id = chat_id
    _bot_last_command_reply_id = reply_message_id


def get_bot_command_stats():
    """Return command-handler diagnostics for the health endpoint."""
    return {
        "count": _bot_command_count,
        "last_command": _bot_last_command,
        "last_command_at": _bot_last_command_at,
        "last_command_error": _bot_last_command_error,
        "last_command_chat_id": _bot_last_command_chat_id,
        "last_command_reply_id": _bot_last_command_reply_id,
    }


def stop_and_clear_instances():
    """Request running clients to stop so the background loop can reload config.

    Pyrogram clients must be stopped on their owning event loop.  Schedule the
    stop callback onto each client's loop instead of calling ``client.stop()``
    from an arbitrary Flask request thread, which can deadlock or raise a
    cross-loop error.
    """
    global _bot_instance, _acc_instance

    bot = _bot_instance
    acc = _acc_instance
    _bot_instance = None
    _acc_instance = None

    for client in (bot, acc):
        if client is None:
            continue
        try:
            loop = getattr(client, "loop", None)
            if loop is not None and not loop.is_closed() and loop.is_running():
                raw_stop = getattr(client.stop, "__wrapped__", None)
                if raw_stop is None:
                    loop.call_soon_threadsafe(client.stop)
                else:
                    asyncio.run_coroutine_threadsafe(
                        raw_stop(client, block=True),
                        loop,
                    )
            else:
                client.stop()
        except Exception:
            pass
