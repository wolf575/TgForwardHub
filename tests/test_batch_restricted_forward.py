import os
import re
import unittest

from pyrogram.errors import ChatForwardsRestricted
from pyrogram.types import InputMediaPhoto

import batch_forward


class _Photo:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []


class _Animation:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []


class _Message:
    def __init__(
        self,
        message_id,
        media_group_id=None,
        photo=None,
        animation=None,
        text=None,
        caption=None,
    ):
        self.id = message_id
        self.chat = type("Chat", (), {"id": -1001234567890})()
        self.media_group_id = media_group_id
        self.photo = photo
        self.animation = animation
        self.text = text
        self.caption = caption
        self.caption_entities = None
        self.entities = None
        self.has_media_spoiler = False


class _Worker:
    def _execute_with_flood_retry(self, name, operation):
        return operation()


class _RestrictedAcc:
    def __init__(self, media_group=None, album_error=None, copy_error=None):
        self.media_group = media_group or []
        self.album_error = album_error
        self.copy_error = copy_error or ChatForwardsRestricted(
            400,
            "CHAT_FORWARDS_RESTRICTED",
        )
        self.downloaded = []
        self.media_groups = []
        self.sent = []
        self.get_media_group_calls = []

    def copy_message(self, *args, **kwargs):
        raise self.copy_error

    def copy_media_group(self, *args, **kwargs):
        raise self.copy_error

    def get_media_group(self, chat_id, message_id):
        self.get_media_group_calls.append((chat_id, message_id))
        return self.media_group

    def download_media(self, item, file_name=None, **kwargs):
        if isinstance(item, _Message):
            path = os.path.join(file_name, f"item_{item.id}.jpg")
        else:
            path = file_name
        self.downloaded.append(path)
        return path

    def send_media_group(self, chat_id, media):
        self.media_groups.append(media)
        if self.album_error:
            raise self.album_error
        return [type("Sent", (), {"id": item_id})() for item_id in (9001, 9002)]

    def send_photo(self, chat_id, file_path, **kwargs):
        self.sent.append(("send_photo", file_path, kwargs))

    def send_video(self, *args, **kwargs):
        self.sent.append(("send_video", args, kwargs))

    def send_document(self, *args, **kwargs):
        self.sent.append(("send_document", args, kwargs))

    def send_audio(self, *args, **kwargs):
        self.sent.append(("send_audio", args, kwargs))


class BatchRestrictedForwardTests(unittest.TestCase):
    def test_restricted_media_group_downloads_and_reuploads_every_item(self):
        first = _Message(10, "album", photo=_Photo("p1"), caption="原始说明")
        second = _Message(11, "album", photo=_Photo("p2"))
        acc = _RestrictedAcc(media_group=[first, second])

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [first, second],
            "清理后的说明",
            True,
            False,
        )

        self.assertEqual((count, used_fallback), (2, True))
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_10.jpg", "item_11.jpg"],
        )
        self.assertEqual(acc.get_media_group_calls, [])
        self.assertEqual(len(acc.media_groups), 1)
        media = acc.media_groups[0]
        self.assertEqual(len(media), 2)
        self.assertIsInstance(media[0], InputMediaPhoto)
        self.assertEqual(media[0].caption, "清理后的说明")
        self.assertEqual(media[1].caption, "")

    def test_unsupported_media_group_type_downloads_and_reuploads(self):
        first = _Message(
            60,
            "album",
            animation=_Animation("a1"),
            caption="GIF 说明",
        )
        second = _Message(61, "album", photo=_Photo("p6"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            copy_error=ValueError("Message with this type can't be copied."),
        )

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [first, second],
            "GIF 说明",
            False,
            False,
        )

        self.assertEqual((count, used_fallback), (2, True))
        self.assertEqual(acc.get_media_group_calls, [])
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_60.jpg", "item_61.jpg"],
        )
        self.assertEqual(len(acc.media_groups), 1)
        self.assertEqual(len(acc.media_groups[0]), 2)

    def test_restricted_single_media_uses_only_user_client_upload(self):
        message = _Message(30, photo=_Photo("p3"), caption="单图说明")
        acc = _RestrictedAcc()

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [message],
            "单图说明",
            False,
            False,
        )

        self.assertEqual((count, used_fallback), (1, True))
        self.assertEqual(len(acc.sent), 1)
        self.assertEqual(acc.sent[0][0], "send_photo")
        self.assertTrue(acc.sent[0][1].endswith("item_30.jpg"))

    def test_album_fallback_keeps_modified_caption_on_first_item_only(self):
        first = _Message(40, "album", photo=_Photo("p4"), caption="原始说明")
        second = _Message(41, "album", photo=_Photo("p5"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            album_error=RuntimeError("album rejected"),
        )

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [first, second],
            "清理后的说明",
            True,
            False,
        )

        self.assertEqual((count, used_fallback), (2, True))
        self.assertEqual(
            [call[0] for call in acc.sent],
            ["send_photo", "send_photo"],
        )
        self.assertEqual(acc.sent[0][2]["caption"], "清理后的说明")
        self.assertNotEqual(acc.sent[1][2]["caption"], "清理后的说明")

    def test_regex_exclusion_and_removal(self):
        patterns = batch_forward._compile_regex_patterns(
            "(?i)广告\n赞助"
        )
        self.assertTrue(batch_forward._matches_exclude_regex("这里有广告", patterns))
        self.assertFalse(batch_forward._matches_exclude_regex("普通内容", patterns))

        cleaned = batch_forward._remove_matches(
            "Hello 广告 world",
            ["Hello"],
            [re.compile(r"\s+")],
        )
        self.assertEqual(cleaned, "广告world")

    def test_invalid_regex_is_rejected_before_task_starts(self):
        with self.assertRaises(ValueError):
            batch_forward._validate_task_spec(
                {
                    "source": "@source",
                    "target": "@target",
                    "range_type": "id",
                    "start": "1",
                    "end": "2",
                    "exclude_regex": "(?P<broken",
                }
            )


if __name__ == "__main__":
    unittest.main()
