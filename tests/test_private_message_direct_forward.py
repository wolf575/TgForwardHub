import os
import unittest

from bot.handlers.messages import (
    _forward_private_media_direct,
    _get_bot_peer_id,
)


class _Message:
    def __init__(self, message_id, media_group_id=None):
        self.id = message_id
        self.media_group_id = media_group_id


class _Acc:
    def __init__(self, copy_error=None, forward_error=None):
        self.copy_error = copy_error
        self.forward_error = forward_error
        self.calls = []
        self.media_group = [_Message(10), _Message(11)]

    def copy_message(self, *args):
        self.calls.append(("copy_message", args))
        if self.copy_error:
            raise self.copy_error

    def forward_messages(self, *args):
        self.calls.append(("forward_messages", args))
        if self.forward_error:
            raise self.forward_error

    def copy_media_group(self, *args):
        self.calls.append(("copy_media_group", args))
        if self.copy_error:
            raise self.copy_error

    def get_media_group(self, *args):
        self.calls.append(("get_media_group", args))
        return self.media_group


class _Bot:
    def __init__(self, bot_id=7654321):
        self.me = type("Me", (), {"id": bot_id})()


class PrivateMessageDirectForwardTests(unittest.TestCase):
    def test_get_bot_peer_id_uses_bot_user_id(self):
        self.assertEqual(_get_bot_peer_id(_Bot(123456)), 123456)

    def test_copy_message_targets_bot_chat_not_command_chat(self):
        acc = _Acc()
        message = _Message(55)

        _forward_private_media_direct(_Bot(9001), acc, -1004445556667, message)

        self.assertEqual(
            acc.calls[0],
            ("copy_message", (9001, -1004445556667, 55)),
        )

    def test_forward_is_attempted_when_copy_is_restricted(self):
        acc = _Acc(copy_error=RuntimeError("copy forbidden"))
        message = _Message(55)

        _forward_private_media_direct(_Bot(9001), acc, -1004445556667, message)

        self.assertEqual(
            acc.calls[1],
            ("forward_messages", (9001, -1004445556667, 55)),
        )

    def test_media_group_is_copied_as_a_group(self):
        acc = _Acc()
        message = _Message(55, media_group_id="album")

        _forward_private_media_direct(_Bot(9001), acc, -1004445556667, message)

        self.assertEqual(
            acc.calls[0],
            ("copy_media_group", (9001, -1004445556667, 55)),
        )

    def test_direct_failure_is_reported_for_download_fallback(self):
        acc = _Acc(
            copy_error=RuntimeError("copy forbidden"),
            forward_error=RuntimeError("forward forbidden"),
        )

        with self.assertRaises(RuntimeError):
            _forward_private_media_direct(
                _Bot(9001),
                acc,
                -1004445556667,
                _Message(55),
            )

    def test_old_progress_status_filename_is_not_used(self):
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "bot",
            "handlers",
            "messages.py",
        )
        with open(source_path, "r", encoding="utf-8") as source_file:
            source = source_file.read()

        self.assertNotIn("f'{message.id}downstatus.txt'", source)
        self.assertNotIn("f'{message.id}upstatus.txt'", source)


if __name__ == "__main__":
    unittest.main()
