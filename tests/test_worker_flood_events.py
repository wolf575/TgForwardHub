import asyncio
import threading
import unittest
from unittest import mock

from pyrogram.errors import FloodWait

from bot.core.client import _await_on_client_loop, client_sync_timeout
from bot.workers.message_worker import MessageWorker


class WorkerFloodEventTests(unittest.TestCase):
    def test_sync_bridge_timeout_stops_waiting_for_stuck_client_loop(self):
        loop = asyncio.new_event_loop()

        def run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        client = type("_Client", (), {"loop": loop})()

        async def stuck_operation():
            await asyncio.sleep(30)

        try:
            with client_sync_timeout(0.05):
                with self.assertRaises(TimeoutError):
                    _await_on_client_loop(client, stuck_operation())
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()

    def test_flood_wait_emits_progress_events_and_retries(self):
        worker = MessageWorker(None, None, max_retries=2)
        events = []
        worker.set_event_callback(events.append)
        attempts = []

        def operation():
            attempts.append(len(attempts) + 1)
            if len(attempts) == 1:
                raise FloodWait(3)
            return "ok"

        with mock.patch("bot.workers.message_worker.time.sleep"):
            result = worker._execute_with_flood_retry(
                "复制单条媒体",
                operation,
                max_flood_retries=2,
                timeout=1,
            )

        self.assertEqual(result, "ok")
        self.assertEqual(
            [event["type"] for event in events],
            ["flood_wait", "flood_wait_resumed"],
        )
        self.assertEqual(events[0]["wait_seconds"], 3)
        self.assertEqual(events[0]["attempt"], 1)

    def test_flood_wait_exhaustion_emits_failure_event(self):
        worker = MessageWorker(None, None, max_retries=1)
        events = []
        worker.set_event_callback(events.append)

        def operation():
            raise FloodWait(2)

        with self.assertRaises(Exception):
            worker._execute_with_flood_retry(
                "复制单条媒体",
                operation,
                max_flood_retries=1,
                timeout=1,
            )

        self.assertEqual(events[-1]["type"], "flood_wait_exhausted")
        self.assertEqual(events[-1]["wait_seconds"], 2)


if __name__ == "__main__":
    unittest.main()
