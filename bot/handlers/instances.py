"""
Global bot and acc instances management
Separated to avoid circular imports
"""
import asyncio

# Store bot and acc instances for use by handlers
_bot_instance = None
_acc_instance = None


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
