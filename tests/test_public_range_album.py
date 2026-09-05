import unittest
from unittest import mock

from bot.handlers import messages


class _PublicMessage:
    def __init__(self, message_id, media_group_id=None, empty=False):
        self.id = message_id
        self.media_group_id = media_group_id
        self.empty = empty
        self.chat = type("_Chat", (), {"id": -1001803856442})()
        self.text = ""
        self.caption = ""
        self.entities = None
        self.caption_entities = None


class _PublicBot:
    def __init__(self, messages_by_id):
        self.messages_by_id = messages_by_id
        self.group_copies = []
        self.message_copies = []
        self.sent = []

    def get_messages(self, chat_id, message_id):
        return self.messages_by_id.get(message_id)

    def get_media_group(self, chat_id, message_id):
        anchor = self.messages_by_id[message_id]
        group_id = anchor.media_group_id
        return [
            message
            for message in self.messages_by_id.values()
            if message.media_group_id == group_id
        ]

    def copy_media_group(self, *args, **kwargs):
        self.group_copies.append((args, kwargs))

    def copy_message(self, *args, **kwargs):
        self.message_copies.append((args, kwargs))

    def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class PublicRangeAlbumTests(unittest.TestCase):
    def test_bot_range_link_copies_each_album_once_and_skips_empty(self):
        first_album = [
            _PublicMessage(message_id, "album-1")
            for message_id in range(48829, 48838)
        ]
        second_album = [
            _PublicMessage(message_id, "album-2")
            for message_id in range(48838, 48844)
        ]
        plain = [
            _PublicMessage(48844),
            _PublicMessage(48845),
            _PublicMessage(48847),
        ]
        empty = [_PublicMessage(48846, empty=True)]
        messages_by_id = {
            message.id: message
            for message in first_album + second_album + plain + empty
        }
        bot = _PublicBot(messages_by_id)
        command = type(
            "_Command",
            (),
            {
                "id": 999,
                "text": "https://t.me/kukutui2/48829-48847",
                "chat": type("_Destination", (), {"id": -1004348673782})(),
                "from_user": type("_User", (), {"id": 1})(),
            },
        )()

        with mock.patch.object(messages, "get_bot_instance", return_value=bot), mock.patch.object(
            messages,
            "get_acc_instance",
            return_value=None,
        ), mock.patch.object(messages.time, "sleep"):
            messages.save(None, command)

        self.assertEqual(len(bot.group_copies), 2)
        self.assertEqual(
            [call[0][2] for call in bot.message_copies],
            [48844, 48845, 48847],
        )
        summary_args, _summary_kwargs = bot.sent[-1]
        summary = summary_args[1]
        self.assertIn("成功: 18/19", summary)
        self.assertIn("跳过: 1", summary)


if __name__ == "__main__":
    unittest.main()
