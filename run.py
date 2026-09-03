"""Single-process entrypoint for the merged web service.

The Flask web UI runs on the main thread while the Pyrogram bot and user
client run in a background thread.
"""
import os
import asyncio
import threading
import time

from app import app
import main


def _ensure_bot_thread_event_loop():
    """Give the background bot thread its own asyncio loop.

    Pyrogram's sync API stores and uses the current thread's event loop.
    Python 3.12 no longer creates one implicitly in non-main threads, so the
    very first ``Client(...)`` call would otherwise fail before the bot can
    even attempt to connect to Telegram.
    """
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def start_bot():
    _ensure_bot_thread_event_loop()
    while True:
        try:
            main.main()
        except Exception:
            # Keep the web UI available even if the bot cannot start yet.
            from bot.utils.logger import get_logger
            get_logger(__name__).exception("Bot thread exited unexpectedly")
        time.sleep(10)


threading.Thread(target=start_bot, name="TelegramBot", daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Keep the Flask request thread stable. web_setup stores a Pyrogram auth
    # client between requests, and Pyrogram sync calls are bound to the event
    # loop of the thread that created that client.
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False)
