import asyncio
import threading
import unittest

import app as container_app


class FakeMessage:
    def __init__(self, message_id, media_group_id=None, empty=False):
        self.id = message_id
        self.media_group_id = media_group_id
        self.empty = empty


class FakeBot:
    def __init__(self, message=None, group=None):
        self.message = message
        self.group = group or []
        self.copy_message_calls = []
        self.copy_media_group_calls = []

    async def get_messages(self, source, message_id):
        return self.message

    async def get_media_group(self, source, message_id):
        return self.group

    async def copy_message(self, chat_id, source, message_id):
        self.copy_message_calls.append((chat_id, source, message_id))
        return self.message

    async def copy_media_group(self, chat_id, source, message_id):
        self.copy_media_group_calls.append((chat_id, source, message_id))
        return self.group


class RangeBot(FakeBot):
    def __init__(self, messages):
        super().__init__()
        self.messages = messages
        self.send_message_calls = []

    async def get_messages(self, source, message_id):
        return self.messages.get(message_id)

    async def send_message(self, chat_id, text, reply_to_message_id=None):
        self.send_message_calls.append((chat_id, text, reply_to_message_id))
        return True


class CopySingleTests(unittest.TestCase):
    def test_copies_plain_message(self):
        bot = FakeBot(message=FakeMessage(7))
        result = asyncio.run(
            container_app.copy_single_message(
                bot,
                chat_id=100,
                source_chat="@source",
                message_id=7,
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["copied_ids"], [7])
        self.assertEqual(bot.copy_message_calls, [(100, "@source", 7)])

    def test_expands_album(self):
        bot = FakeBot(
            message=FakeMessage(20, media_group_id="album"),
            group=[FakeMessage(20), FakeMessage(21)],
        )
        result = asyncio.run(
            container_app.copy_single_message(
                bot,
                chat_id=100,
                source_chat="@source",
                message_id=20,
            )
        )
        self.assertEqual(result["copied_ids"], [20, 21])
        self.assertEqual(bot.copy_media_group_calls, [(100, "@source", 20)])
        self.assertEqual(bot.copy_message_calls, [])

    def test_album_falls_back_to_anchor(self):
        class FallbackBot(FakeBot):
            async def copy_media_group(self, chat_id, source, message_id):
                raise RuntimeError("album rejected")

        bot = FallbackBot(
            message=FakeMessage(20, media_group_id="album"),
            group=[FakeMessage(20), FakeMessage(21)],
        )
        result = asyncio.run(
            container_app.copy_single_message(
                bot,
                chat_id=100,
                source_chat="@source",
                message_id=20,
            )
        )
        self.assertEqual(result["copied_ids"], [20])
        self.assertEqual(bot.copy_message_calls, [(100, "@source", 20)])

    def test_missing_message_is_skipped(self):
        bot = FakeBot(message=None)
        result = asyncio.run(
            container_app.copy_single_message(
                bot,
                chat_id=100,
                source_chat="@source",
                message_id=404,
            )
        )
        self.assertTrue(result["skipped"])
        self.assertEqual(result["copied_ids"], [])

    def test_normalizes_numeric_source(self):
        self.assertEqual(container_app.normalize_source_chat("-100123"), -100123)
        self.assertEqual(container_app.normalize_source_chat("@source"), "@source")

    def test_copies_message_range(self):
        bot = RangeBot(
            {
                1: FakeMessage(1),
                2: FakeMessage(2),
                3: None,
            }
        )
        result = asyncio.run(
            container_app.copy_message_range(
                bot,
                chat_id=100,
                source_chat="@source",
                start_id=1,
                end_id=3,
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["next_id"], 4)
        self.assertEqual(
            bot.copy_message_calls,
            [(100, "@source", 1), (100, "@source", 2)],
        )

    def test_processes_forward_job_and_summary(self):
        bot = RangeBot({1: FakeMessage(1), 2: FakeMessage(2)})
        asyncio.run(
            container_app.process_forward_job(
                bot,
                {
                    "chat_id": 100,
                    "source_chat": "@source",
                    "start_id": 1,
                    "end_id": 2,
                    "reply_to_message_id": 10,
                    "notify": True,
                },
            )
        )
        self.assertEqual(len(bot.copy_message_calls), 2)
        self.assertEqual(len(bot.send_message_calls), 1)
        self.assertIn("成功转发 2/2", bot.send_message_calls[0][1])

    def test_range_expands_album_once(self):
        group = [
            FakeMessage(20, media_group_id="album"),
            FakeMessage(21, media_group_id="album"),
        ]
        bot = RangeBot({20: group[0], 21: group[1]})
        bot.group = group
        result = asyncio.run(
            container_app.copy_message_range(
                bot,
                chat_id=100,
                source_chat="@source",
                start_id=20,
                end_id=21,
            )
        )
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["next_id"], 22)
        self.assertEqual(bot.copy_message_calls, [])
        self.assertEqual(bot.copy_media_group_calls, [(100, "@source", 20)])


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.previous_bot = container_app.bot
        self.previous_ready = container_app.bot_ready.is_set()
        self.previous_loop = container_app.event_loop
        self.previous_job_queue = container_app.job_queue
        self.previous_error = container_app.bot_error

        self.loop = asyncio.new_event_loop()
        self.loop_ready = threading.Event()
        self.thread = threading.Thread(
            target=self._run_loop,
            name="test-pyrogram-loop",
            daemon=True,
        )
        self.thread.start()
        self.assertTrue(self.loop_ready.wait(timeout=5))

        container_app.event_loop = self.loop
        container_app.job_queue = asyncio.Queue()
        container_app.bot = None
        container_app.bot_error = ""
        container_app.bot_ready.clear()
        self.client = container_app.app.test_client()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop_ready.set()
        self.loop.run_forever()

    def tearDown(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()
        container_app.event_loop = self.previous_loop
        container_app.job_queue = self.previous_job_queue
        container_app.bot = self.previous_bot
        container_app.bot_error = self.previous_error
        if self.previous_ready:
            container_app.bot_ready.set()
        else:
            container_app.bot_ready.clear()

    def test_health_reports_bot_readiness(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["bot_ready"])

    def test_copy_endpoint_rejects_missing_fields(self):
        container_app.bot = FakeBot(message=FakeMessage(1))
        container_app.bot_ready.set()
        response = self.client.post("/copy-single", json={})
        self.assertEqual(response.status_code, 400)

    def test_copy_endpoint_runs_on_event_loop(self):
        fake_bot = FakeBot(message=FakeMessage(5))
        container_app.bot = fake_bot
        container_app.bot_ready.set()
        response = self.client.post(
            "/copy-single",
            json={
                "chat_id": 100,
                "source_chat": "@source",
                "message_id": 5,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["copied_ids"], [5])
        self.assertEqual(fake_bot.copy_message_calls, [(100, "@source", 5)])

    def test_forward_endpoint_enqueues_job(self):
        response = self.client.post(
            "/forward",
            json={
                "chat_id": 100,
                "source_chat": "@source",
                "start_id": 1,
                "end_id": 3,
                "reply_to_message_id": 9,
                "notify": False,
            },
        )
        self.assertEqual(response.status_code, 202)
        job = asyncio.run_coroutine_threadsafe(
            container_app.job_queue.get(),
            container_app.event_loop,
        ).result(timeout=5)
        self.assertEqual(job["start_id"], 1)
        self.assertEqual(job["end_id"], 3)
        self.assertFalse(job["notify"])


if __name__ == "__main__":
    unittest.main()
