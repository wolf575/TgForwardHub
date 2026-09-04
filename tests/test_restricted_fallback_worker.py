import os
import unittest
from unittest.mock import patch

from pyrogram.errors import ChatForwardsRestricted
from pyrogram.types import InputMediaPhoto

from bot.handlers.messages import _download_and_reupload_media_fallback
from bot.workers.message_worker import MessageWorker


class _Photo:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []


class _Audio:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []


class _Chat:
    id = -1001234567890


class _Message:
    def __init__(
        self,
        message_id,
        media_group_id=None,
        photo=None,
        audio=None,
        caption=None,
    ):
        self.id = message_id
        self.chat = _Chat()
        self.media_group_id = media_group_id
        self.photo = photo
        self.audio = audio
        self.video = None
        self.animation = None
        self.document = None
        self.voice = None
        self.sticker = None
        self.caption = caption
        self.caption_entities = None
        self.entities = None
        self.text = None
        self.has_media_spoiler = False


class _Sent:
    def __init__(self, message_id):
        self.id = message_id


class _DownloadAcc:
    def __init__(self, media_group):
        self.media_group = media_group
        self.calls = []

    def get_media_group(self, chat_id, message_id):
        self.calls.append(("get_media_group", chat_id, message_id))
        return self.media_group

    def download_media(self, item, file_name=None, **kwargs):
        self.calls.append(("download_media", item.id, file_name))
        return os.path.join(file_name, f"item_{item.id}.jpg")

    def send_media_group(self, chat_id, media):
        self.calls.append(("send_media_group", chat_id, media))
        return [_Sent(9001), _Sent(9002)]


class _RestrictedForwardAcc:
    def __init__(self):
        self.calls = []

    def forward_messages(self, *args, **kwargs):
        self.calls.append(("forward_messages", args, kwargs))
        raise ChatForwardsRestricted(400, "CHAT_FORWARDS_RESTRICTED")


class RestrictedFallbackWorkerTests(unittest.TestCase):
    def test_media_fallback_downloads_and_uploads_the_complete_group(self):
        first = _Message(10, "album", photo=_Photo("p1"), caption="说明")
        second = _Message(11, "album", photo=_Photo("p2"))
        acc = _DownloadAcc([first, second])

        result = _download_and_reupload_media_fallback(
            acc,
            -1009876543210,
            _Chat.id,
            first,
        )

        self.assertEqual(result, 9001)
        upload = next(call for call in acc.calls if call[0] == "send_media_group")
        media = upload[2]
        self.assertEqual(len(media), 2)
        self.assertIsInstance(media[0], InputMediaPhoto)
        self.assertIsInstance(media[1], InputMediaPhoto)
        self.assertFalse(os.path.exists(os.path.dirname(media[0].media)))

    @patch("bot.handlers.messages._download_and_reupload_media_fallback")
    @patch("bot.workers.message_worker.time.sleep")
    def test_restricted_audio_uses_media_upload_fallback(
        self,
        sleep_mock,
        fallback_mock,
    ):
        message = _Message(30, audio=_Audio("a1"))
        acc = _RestrictedForwardAcc()
        fallback_mock.return_value = _Sent(777)
        worker = MessageWorker(None, acc, max_retries=1)

        forwarded_id = worker._forward_with_source(message, -1009876543210)

        self.assertEqual(forwarded_id, 777)
        self.assertEqual(acc.calls[0][0], "forward_messages")
        fallback_mock.assert_called_once()
        sleep_mock.assert_called()


if __name__ == "__main__":
    unittest.main()
