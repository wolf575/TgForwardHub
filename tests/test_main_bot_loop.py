import asyncio
import inspect
import unittest
from unittest import mock

import main
from bot.handlers.instances import (
    get_bot_command_stats,
    get_bot_update_stats,
    record_bot_command,
    record_bot_update,
)
from bot.core.client import (
    _update_client_options,
    install_client_loop_bridge,
)
from bot.handlers.commands import register_command_handlers


class _FakeLoop:
    def __init__(self):
        self.coroutine = None

    def is_closed(self):
        return False

    def run_until_complete(self, coroutine):
        self.coroutine = coroutine
        coroutine.close()


class MainBotLoopTests(unittest.TestCase):
    def test_enables_pyrofork_update_gap_recovery(self):
        class _PyroforkClient:
            def __init__(
                self,
                name,
                api_id=None,
                api_hash=None,
                bot_token=None,
                no_updates=None,
                skip_updates=None,
            ):
                pass

        with mock.patch("bot.core.client.Client", _PyroforkClient):
            options = _update_client_options()

        self.assertEqual(
            options,
            {"no_updates": False, "skip_updates": False},
        )

    def test_records_bot_update_activity(self):
        before = get_bot_update_stats()
        record_bot_update()
        after = get_bot_update_stats()

        self.assertEqual(after["count"], before["count"] + 1)
        self.assertIsNotNone(after["last_update_at"])

    def test_records_command_activity_without_message_contents(self):
        before = get_bot_command_stats()
        record_bot_command("start")
        after = get_bot_command_stats()

        self.assertEqual(after["count"], before["count"] + 1)
        self.assertEqual(after["last_command"], "start")
        self.assertIsNone(after["last_command_error"])

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

    def test_installs_sync_bridge_for_pyrofork_wrapped_methods(self):
        loop = asyncio.new_event_loop()

        async def original_send(_client, value):
            return value

        class _Client:
            pass

        client = _Client()
        client.loop = loop
        client.send_message = lambda _client, value: value
        client.send_message.__wrapped__ = original_send

        install_client_loop_bridge(client)

        self.assertTrue(client._tgfh_loop_bridge_installed)
        self.assertEqual(client.send_message("ok"), "ok")
        loop.close()

    def test_command_handlers_are_native_async_callbacks(self):
        class _Bot:
            def __init__(self):
                self.callbacks = []

            def on_message(self, *_args, **_kwargs):
                def register(callback):
                    self.callbacks.append(callback)
                    return callback

                return register

        bot = _Bot()
        register_command_handlers(bot, None)

        self.assertEqual(len(bot.callbacks), 3)
        self.assertTrue(
            all(inspect.iscoroutinefunction(callback) for callback in bot.callbacks)
        )


if __name__ == "__main__":
    unittest.main()
