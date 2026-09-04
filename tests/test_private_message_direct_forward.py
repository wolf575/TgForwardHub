import os
import unittest

from pyrogram.errors import FileReferenceExpired

from bot.handlers.messages import (
    _forward_private_media_direct,
    _get_bot_peer_id,
)


class _Message:
    def __init__(self, message_id, media_group_id=None):
        self.id = message_id
        self.media_group_id = media_group_id


class _Acc:
    def __init__(
        self,
        copy_error=None,
        forward_error=None,
        media_group_error=None,
        fetched_message=None,
        copy_error_once=False,
    ):
        self.copy_error = copy_error
        self.copy_error_once = copy_error_once
        self.forward_error = forward_error
        self.media_group_error = media_group_error
        self.fetched_message = fetched_message
        self.calls = []
        self.media_group = [_Message(10), _Message(11)]

    def copy_message(self, *args):
        self.calls.append(("copy_message", args))
        copy_attempts = sum(1 for call in self.calls if call[0] == "copy_message")
        if self.copy_error and not (self.copy_error_once and copy_attempts > 1):
            raise self.copy_error

    def forward_messages(self, *args):
        self.calls.append(("forward_messages", args))
        if self.forward_error:
            raise self.forward_error

    def copy_media_group(self, *args):
        self.calls.append(("copy_media_group", args))
        if self.media_group_error:
            raise self.media_group_error

    def get_media_group(self, *args):
        self.calls.append(("get_media_group", args))
        return self.media_group

    def get_messages(self, *args):
        self.calls.append(("get_messages", args))
        return self.fetched_message


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

    def test_forward_is_not_used_when_copy_is_restricted(self):
        acc = _Acc(copy_error=RuntimeError("copy forbidden"))
        message = _Message(55)

        with self.assertRaises(RuntimeError):
            _forward_private_media_direct(
                _Bot(9001), acc, -1004445556667, message
            )

        self.assertNotIn("forward_messages", [call[0] for call in acc.calls])

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
        )

        with self.assertRaises(RuntimeError):
            _forward_private_media_direct(
                _Bot(9001),
                acc,
                -1004445556667,
                _Message(55),
            )

    def test_expired_file_reference_is_refetched_and_copied(self):
        fresh_message = _Message(55)
        acc = _Acc(
            copy_error=FileReferenceExpired(400, "FILE_REFERENCE_EXPIRED"),
            fetched_message=fresh_message,
            copy_error_once=True,
        )

        _forward_private_media_direct(_Bot(9001), acc, -1004445556667, _Message(55))

        self.assertEqual(
            acc.calls,
            [
                ("copy_message", (9001, -1004445556667, 55)),
                ("get_messages", (-1004445556667, 55)),
                ("copy_message", (9001, -1004445556667, 55)),
            ],
        )

    def test_media_group_falls_back_to_cached_copies_not_forwarding(self):
        acc = _Acc(media_group_error=RuntimeError("album copy failed"))
        message = _Message(55, media_group_id="album")

        _forward_private_media_direct(_Bot(9001), acc, -1004445556667, message)

        self.assertEqual(
            acc.calls,
            [
                ("copy_media_group", (9001, -1004445556667, 55)),
                ("get_media_group", (-1004445556667, 55)),
                ("copy_message", (9001, -1004445556667, 10)),
                ("copy_message", (9001, -1004445556667, 11)),
            ],
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
