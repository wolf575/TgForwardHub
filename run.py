"""Single-process entrypoint for the merged web service.

The Pyrogram bot and user client run on the main thread so that Pyrogram's
sync handlers can schedule API calls back onto the main event loop.  Flask
runs in a background thread and remains available for the web UI.
"""
import os
import threading
import time

from app import app
import main


def _start_web():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


threading.Thread(target=_start_web, name="FlaskWeb", daemon=True).start()

while True:
    try:
        main.main()
    except Exception:
        from bot.utils.logger import get_logger
        get_logger(__name__).exception("Bot main loop exited unexpectedly")
    time.sleep(10)
