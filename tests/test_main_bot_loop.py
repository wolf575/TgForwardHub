import asyncio
import unittest
from unittest import mock

import main


class _FakeLoop:
    def __init__(self):
        self.coroutine = None

    def is_closed(self):
        return False

    def run_until_complete(self, coroutine):
        self.coroutine = coroutine
        coroutine.close()


class MainBotLoopTests(unittest.TestCase):
    def test_prepares_client_loop(self):
        client_loop = _FakeLoop()
        bot = type("Bot", (), {"loop": client_loop})()

        with mock.patch.object(
            main.asyncio,
            "set_event_loop",
        ) as set_event_loop:
            self.assertIs(main._prepare_bot_loop(bot), client_loop)

        set_event_loop.assert_called_once_with(client_loop)

    def test_uses_client_owned_event_loop_for_dispatcher(self):
        client_loop = _FakeLoop()
        bot = type("Bot", (), {"loop": client_loop})()

        with mock.patch.object(
            main,
            "_idle_without_signals",
            return_value=asyncio.sleep(0),
        ), mock.patch.object(
            main.asyncio,
            "get_event_loop",
        ) as get_event_loop, mock.patch.object(
            main.asyncio,
            "set_event_loop",
        ):
            main._run_bot_loop(bot)

        self.assertIsNotNone(client_loop.coroutine)
        get_event_loop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
