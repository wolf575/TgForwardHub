"""Pyrogram Bot service used by the Cloudflare Worker.

The Worker handles Telegram webhooks, whitelist checks, and range copies through
the Bot API. This service handles one message at a time so Pyrogram can detect
and copy a complete media group.

Pyrogram is used asynchronously on one dedicated event-loop thread. Every
Telegram operation is submitted to that same loop, which avoids the event-loop
affinity problems of Pyrogram's sync wrapper under Waitress worker threads.
"""

import asyncio
import atexit
import logging
import os
import threading
import time
import uuid
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Dict

from flask import Flask, jsonify, request
from pyrogram import Client
from pyrogram.errors import FloodWait
from waitress import serve


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("cf-worker-container")

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

event_loop: asyncio.AbstractEventLoop | None = None
job_queue: asyncio.Queue | None = None
loop_ready = threading.Event()
loop_thread: threading.Thread | None = None
bot: Client | None = None
bot_ready = threading.Event()
bot_error = ""

BOT_READY_TIMEOUT_SECONDS = 90
COPY_TIMEOUT_SECONDS = 90
RANGE_DELAY_SECONDS = 0.2
MAX_RANGE_MESSAGES = 100


def normalize_source_chat(source_chat: Any) -> Any:
    """Keep Telegram numeric IDs numeric and username references as strings."""
    value = str(source_chat or "").strip()
    if value.startswith("-") and value[1:].isdigit():
        return int(value)
    return value


async def copy_single_message(
    client: Client,
    chat_id: int,
    source_chat: Any,
    message_id: int,
) -> Dict[str, Any]:
    """Copy one message, expanding its complete media group when present."""
    source = normalize_source_chat(source_chat)
    message = await client.get_messages(source, message_id)
    if message is None or getattr(message, "empty", False):
        return {"ok": True, "copied_ids": [], "skipped": True}

    if getattr(message, "media_group_id", None):
        try:
            group = await client.get_media_group(source, message_id) or [message]
            group_ids = sorted(
                {
                    int(item.id)
                    for item in group
                    if getattr(item, "id", None) is not None
                }
            )
            if not group_ids:
                group_ids = [int(message_id)]
            await client.copy_media_group(chat_id, source, message_id)
            return {"ok": True, "copied_ids": group_ids, "skipped": False}
        except Exception as exc:
            logger.warning(
                "media group copy failed for %s/%s, falling back to anchor: %s",
                source,
                message_id,
                exc,
            )

    await client.copy_message(chat_id, source, message_id)
    return {
        "ok": True,
        "copied_ids": [int(message_id)],
        "skipped": False,
    }


async def copy_message_range(
    client: Client,
    chat_id: int,
    source_chat: Any,
    start_id: int,
    end_id: int,
) -> Dict[str, Any]:
    """Copy an inclusive message range through the same Pyrogram client.

    The Worker splits larger ranges into bounded chunks. Returning the next
    message ID lets the Worker resume without losing progress after a flood
    wait or transient failure.
    """
    source = normalize_source_chat(source_chat)
    if start_id <= 0 or end_id < start_id:
        raise ValueError("invalid message range")
    if end_id - start_id + 1 > MAX_RANGE_MESSAGES:
        raise ValueError("range chunk is too large")

    success_count = 0
    skipped_count = 0
    failed_ids = []
    handled_groups = set()
    next_id = start_id

    for msgid in range(start_id, end_id + 1):
        try:
            message = await client.get_messages(source, msgid)
            if message is None or getattr(message, "empty", False):
                skipped_count += 1
                next_id = msgid + 1
                continue

            media_group_id = getattr(message, "media_group_id", None)
            if media_group_id:
                if media_group_id in handled_groups:
                    next_id = msgid + 1
                    continue
                try:
                    group = (
                        await client.get_media_group(source, msgid) or [message]
                    )
                    group_ids = sorted(
                        {
                            int(item.id)
                            for item in group
                            if getattr(item, "id", None) is not None
                        }
                    )
                    if not group_ids:
                        group_ids = [msgid]
                    await client.copy_media_group(chat_id, source, msgid)
                    handled_groups.add(media_group_id)
                    success_count += sum(
                        1 for item_id in group_ids if start_id <= item_id <= end_id
                    )
                    # A group may cross a chunk boundary. Mark its complete
                    # extent as handled so the next chunk cannot copy it again.
                    next_id = max(next_id, max(group_ids) + 1)
                except Exception:
                    await client.copy_message(chat_id, source, msgid)
                    success_count += 1
                    next_id = msgid + 1
            else:
                await client.copy_message(chat_id, source, msgid)
                success_count += 1
                next_id = msgid + 1
        except FloodWait as exc:
            return {
                "ok": False,
                "error": "flood_wait",
                "retry_after": int(getattr(exc, "value", 0) or 0),
                "next_id": msgid,
                "success_count": success_count,
                "skipped_count": skipped_count,
                "failed_ids": failed_ids,
            }
        except Exception as exc:
            logger.warning(
                "range copy failed for %s/%s: %s: %s",
                source,
                msgid,
                type(exc).__name__,
                exc,
            )
            failed_ids.append(msgid)
            next_id = msgid + 1

        if msgid < end_id:
            await asyncio.sleep(RANGE_DELAY_SECONDS)

    return {
        "ok": True,
        "next_id": next_id,
        "success_count": success_count,
        "skipped_count": skipped_count,
        "failed_ids": failed_ids,
    }


def format_summary(total, success, skipped, failed_ids):
    failed = len(failed_ids)
    if failed:
        return (
            "📊 批量转发完成\n\n"
            f"✅ 成功: {success}/{total}\n"
            f"❌ 失败: {failed}\n"
            f"⏭️ 跳过: {skipped}\n\n"
            f"失败的消息ID: {', '.join(str(item) for item in failed_ids)}"
        )
    if skipped:
        return (
            "📊 批量转发完成\n\n"
            f"✅ 成功: {success}/{total}\n"
            f"⏭️ 跳过: {skipped}"
        )
    return f"✅ 批量转发完成\n\n成功转发 {success}/{total} 条消息"


async def process_forward_job(client: Client, job: Dict[str, Any]) -> None:
    chat_id = int(job["chat_id"])
    source_chat = str(job["source_chat"])
    start_id = int(job["start_id"])
    end_id = int(job["end_id"])
    notify = bool(job.get("notify", True))
    reply_to = job.get("reply_to_message_id")

    success_count = 0
    skipped_count = 0
    failed_ids = []
    current_id = start_id

    while current_id <= end_id:
        chunk_end = min(current_id + MAX_RANGE_MESSAGES - 1, end_id)
        attempts = 0
        while attempts < 3:
            result = await copy_message_range(
                client,
                chat_id,
                source_chat,
                current_id,
                chunk_end,
            )
            success_count += int(result.get("success_count", 0) or 0)
            skipped_count += int(result.get("skipped_count", 0) or 0)
            failed_ids.extend(result.get("failed_ids", []))
            if result.get("ok"):
                next_id = int(result.get("next_id") or chunk_end + 1)
                current_id = max(current_id + 1, next_id)
                break
            current_id = max(
                current_id,
                int(result.get("next_id") or current_id),
            )
            attempts += 1
            wait_seconds = max(
                1,
                int(result.get("retry_after", 0) or 0),
            )
            logger.warning(
                "forward job retrying source=%s range=%s-%s attempt=%s wait=%ss",
                source_chat,
                current_id,
                chunk_end,
                attempts,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)
        else:
            failed_ids.extend(range(current_id, chunk_end + 1))
            current_id = chunk_end + 1

    if notify:
        text = format_summary(
            end_id - start_id + 1,
            success_count,
            skipped_count,
            failed_ids,
        )
        try:
            if reply_to:
                await client.send_message(
                    chat_id,
                    text,
                    reply_to_message_id=int(reply_to),
                )
            else:
                await client.send_message(chat_id, text)
        except Exception:
            logger.warning("summary reply failed, sending without reply", exc_info=True)
            await client.send_message(chat_id, text)


async def process_forward_jobs() -> None:
    if job_queue is None:
        return
    while True:
        job = await job_queue.get()
        try:
            deadline = time.monotonic() + BOT_READY_TIMEOUT_SECONDS
            while not bot_ready.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.2)
            if not bot_ready.is_set():
                logger.error("forward job skipped: bot is not ready")
                continue
            logger.info(
                "processing forward job source=%s range=%s-%s notify=%s",
                job.get("source_chat"),
                job.get("start_id"),
                job.get("end_id"),
                job.get("notify"),
            )
            await process_forward_job(bot, job)
        except Exception:
            logger.exception("forward job failed")
        finally:
            job_queue.task_done()


def _client_from_env() -> Client:
    token = os.environ.get("BOT_TOKEN", "").strip()
    api_id_raw = os.environ.get("API_ID", "").strip()
    api_hash = os.environ.get("API_HASH", "").strip()

    if not token or not api_id_raw or not api_hash:
        raise RuntimeError("BOT_TOKEN, API_ID and API_HASH are required")
    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise RuntimeError("API_ID must be numeric") from exc

    return Client(
        "cf_worker_bot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=token,
        in_memory=True,
        no_updates=True,
    )


async def initialize_bot_async() -> None:
    global bot, bot_error
    try:
        client = _client_from_env()
        await client.start()
        bot = client
        bot_error = ""
        bot_ready.set()
        logger.info("Pyrogram Bot client connected")
    except Exception as exc:
        bot = None
        bot_error = f"{type(exc).__name__}: {exc}"
        bot_ready.clear()
        logger.exception("Pyrogram initialization failed")


async def stop_bot_async() -> None:
    global bot
    try:
        if bot is not None and bot.is_connected:
            await bot.stop()
    except Exception:
        logger.exception("failed to stop Pyrogram client")
    finally:
        bot = None
        bot_ready.clear()


def run_event_loop() -> None:
    global event_loop, job_queue
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    job_queue = asyncio.Queue()
    loop_ready.set()
    event_loop.create_task(initialize_bot_async())
    event_loop.create_task(process_forward_jobs())
    event_loop.run_forever()


def start_event_loop() -> None:
    global loop_thread
    if loop_thread and loop_thread.is_alive():
        return
    loop_thread = threading.Thread(
        target=run_event_loop,
        name="pyrogram-loop",
        daemon=True,
    )
    loop_thread.start()
    if not loop_ready.wait(timeout=10):
        raise RuntimeError("Pyrogram event loop did not start")


def submit_to_loop(coroutine, timeout: float):
    if event_loop is None or event_loop.is_closed():
        raise RuntimeError("Pyrogram event loop is unavailable")
    future = asyncio.run_coroutine_threadsafe(coroutine, event_loop)
    return future.result(timeout=timeout)


def shutdown() -> None:
    global event_loop
    if event_loop is not None and not event_loop.is_closed():
        try:
            asyncio.run_coroutine_threadsafe(
                stop_bot_async(),
                event_loop,
            ).result(timeout=10)
        except Exception:
            logger.exception("failed to stop container event loop")
        finally:
            event_loop.call_soon_threadsafe(event_loop.stop)
    if loop_thread and loop_thread.is_alive():
        loop_thread.join(timeout=10)
    event_loop = None


def wait_until_bot_ready():
    if bot_ready.is_set():
        return None
    if bot_error:
        return jsonify({"ok": False, "error": bot_error}), 503
    if not bot_ready.wait(timeout=BOT_READY_TIMEOUT_SECONDS):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "bot connection timed out",
                }
            ),
            503,
        )
    return None


@app.get("/healthz")
def healthz():
    # The HTTP server can accept traffic before MTProto finishes connecting.
    # /copy-single waits for bot_ready, so Container port readiness is not
    # blocked by a slow Telegram connection.
    return jsonify(
        {
            "ok": True,
            "bot_ready": bot_ready.is_set(),
            "bot_error": bot_error or None,
        }
    )


@app.post("/forward")
def forward():
    payload = request.get_json(silent=True) or {}
    try:
        chat_id = int(payload["chat_id"])
        start_id = int(payload["start_id"])
        end_id = int(payload["end_id"])
    except (KeyError, TypeError, ValueError):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "chat_id, start_id and end_id must be numeric",
                }
            ),
            400,
        )

    source_chat = str(payload.get("source_chat") or "").strip()
    if not source_chat:
        return jsonify({"ok": False, "error": "source_chat is required"}), 400
    if start_id <= 0 or end_id < start_id:
        return jsonify({"ok": False, "error": "invalid message range"}), 400
    if event_loop is None or job_queue is None:
        return jsonify({"ok": False, "error": "event loop not ready"}), 503

    job = {
        "job_id": uuid.uuid4().hex,
        "chat_id": chat_id,
        "source_chat": source_chat,
        "start_id": start_id,
        "end_id": end_id,
        "reply_to_message_id": payload.get("reply_to_message_id"),
        "notify": bool(payload.get("notify", True)),
    }
    try:
        asyncio.run_coroutine_threadsafe(
            job_queue.put(job),
            event_loop,
        ).result(timeout=5)
    except Exception:
        logger.exception("failed to enqueue forward job")
        return jsonify({"ok": False, "error": "failed to enqueue job"}), 503
    return jsonify({"ok": True, "accepted": True, "job_id": job["job_id"]}), 202


@app.post("/copy-single")
def copy_single():
    payload = request.get_json(silent=True) or {}
    try:
        chat_id = int(payload["chat_id"])
        message_id = int(payload["message_id"])
    except (KeyError, TypeError, ValueError):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "chat_id and message_id must be numeric",
                }
            ),
            400,
        )

    source_chat = str(payload.get("source_chat") or "").strip()
    if not source_chat:
        return jsonify({"ok": False, "error": "source_chat is required"}), 400

    unavailable = wait_until_bot_ready()
    if unavailable is not None:
        return unavailable

    try:
        result = submit_to_loop(
            copy_single_message(
                bot,
                chat_id,
                source_chat,
                message_id,
            ),
            timeout=COPY_TIMEOUT_SECONDS,
        )
        return jsonify(result)
    except FutureTimeoutError:
        return jsonify({"ok": False, "error": "copy timeout"}), 504
    except FloodWait as exc:
        wait_seconds = int(getattr(exc, "value", 0) or 0)
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "flood_wait",
                    "retry_after": wait_seconds,
                }
            ),
            429,
        )
    except Exception as exc:
        logger.exception(
            "copy failed chat_id=%s source=%s message_id=%s",
            chat_id,
            source_chat,
            message_id,
        )
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            ),
            502,
        )


@app.post("/copy-range")
def copy_range():
    payload = request.get_json(silent=True) or {}
    try:
        chat_id = int(payload["chat_id"])
        start_id = int(payload["start_id"])
        end_id = int(payload["end_id"])
    except (KeyError, TypeError, ValueError):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "chat_id, start_id and end_id must be numeric",
                }
            ),
            400,
        )

    source_chat = str(payload.get("source_chat") or "").strip()
    if not source_chat:
        return jsonify({"ok": False, "error": "source_chat is required"}), 400

    unavailable = wait_until_bot_ready()
    if unavailable is not None:
        return unavailable

    try:
        result = submit_to_loop(
            copy_message_range(
                bot,
                chat_id,
                source_chat,
                start_id,
                end_id,
            ),
            timeout=COPY_TIMEOUT_SECONDS,
        )
        return jsonify(result)
    except FutureTimeoutError:
        return jsonify({"ok": False, "error": "copy timeout"}), 504
    except Exception as exc:
        logger.exception(
            "range copy failed chat_id=%s source=%s range=%s-%s",
            chat_id,
            source_chat,
            start_id,
            end_id,
        )
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            ),
            502,
        )


def main() -> int:
    try:
        start_event_loop()
    except Exception:
        logger.exception("container startup failed")
        return 1

    atexit.register(shutdown)
    port = int(os.environ.get("PORT", "8080"))
    logger.info("starting Waitress on 0.0.0.0:%s", port)
    serve(app, host="0.0.0.0", port=port, threads=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
