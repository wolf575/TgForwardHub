"""Single-process entrypoint for the merged web service.

The Flask web UI runs on the main thread while the Pyrogram bot and user
client run in a background thread.
"""
import os
import threading

from app import app
import main


def start_bot():
    try:
        main.main()
    except Exception:
        # Keep the web UI available even if the bot cannot start yet.
        from bot.utils.logger import get_logger
        get_logger(__name__).exception("Bot thread exited unexpectedly")


threading.Thread(target=start_bot, name="TelegramBot", daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
