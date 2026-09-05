import os
import re
import unittest

from pyrogram.enums import MessageMediaType
from pyrogram.errors import ChatForwardsRestricted
from pyrogram.types import InputMediaPhoto

import batch_forward
from bot.utils.helpers import get_message_type


class _Photo:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []


class _Animation:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []


class _VideoNote:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []
        self.duration = 4
        self.length = 512


class _Message:
    def __init__(
        self,
        message_id,
        media_group_id=None,
        photo=None,
        animation=None,
        video_note=None,
        text=None,
        caption=None,
    ):
        self.id = message_id
        self.chat = type("Chat", (), {"id": -1001234567890})()
        self.media_group_id = media_group_id
        self.photo = photo
        self.animation = animation
        self.video_note = video_note
        self.text = text
        self.caption = caption
        self.caption_entities = None
        self.entities = None
        self.has_media_spoiler = False


class _Worker:
    def _execute_with_flood_retry(self, name, operation):
        return operation()


class _RestrictedAcc:
    def __init__(
        self,
        media_group=None,
        album_error=None,
        copy_error=None,
        item_copy_error="same-as-copy",
        forward_error="same-as-copy",
    ):
        self.media_group = media_group or []
        self.album_error = album_error
        self.copy_error = copy_error or ChatForwardsRestricted(
            400,
            "CHAT_FORWARDS_RESTRICTED",
        )
        self.item_copy_error = (
            self.copy_error
            if item_copy_error == "same-as-copy"
            else item_copy_error
        )
        self.forward_error = (
            self.copy_error if forward_error == "same-as-copy" else forward_error
        )
        self.downloaded = []
        self.media_groups = []
        self.sent = []
        self.copied = []
        self.forwarded = []
        self.get_media_group_calls = []

    def copy_message(self, *args, **kwargs):
        self.copied.append((args, kwargs))
        error = self.item_copy_error
        if callable(error):
            error = error(args, kwargs)
        if error:
            raise error

    def copy_media_group(self, *args, **kwargs):
        raise self.album_error or self.copy_error

    def forward_messages(self, *args, **kwargs):
        self.forwarded.append((args, kwargs))
        error = self.forward_error
        if callable(error):
            error = error(args, kwargs)
        if error:
            raise error

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

    def send_video_note(self, *args, **kwargs):
        self.sent.append(("send_video_note", args, kwargs))

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

    def test_unsupported_media_group_uses_cached_item_copies_not_downloads(self):
        first = _Message(
            80,
            "album",
            animation=_Animation("a2"),
            caption="GIF 说明",
        )
        second = _Message(81, "album", photo=_Photo("p8"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            album_error=ValueError("Message with this type can't be copied."),
            item_copy_error=None,
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

        self.assertEqual((count, used_fallback), (2, False))
        self.assertEqual(acc.downloaded, [])
        self.assertEqual(
            [call[0][2] for call in acc.copied],
            [80, 81],
        )
        self.assertNotIn("caption", acc.copied[0][1])
        self.assertNotIn("caption", acc.copied[1][1])

    def test_clone_group_copy_failure_reuploads_without_forward(self):
        first = _Message(100, "album", photo=_Photo("p10"))
        second = _Message(101, "album", photo=_Photo("p11"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            album_error=ValueError("Message with this type can't be copied."),
            item_copy_error=ValueError("Can't copy this message"),
        )

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [first, second],
            None,
            False,
            False,
        )

        self.assertEqual((count, used_fallback), (2, True))
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_100.jpg", "item_101.jpg"],
        )
        self.assertEqual(acc.forwarded, [])
        self.assertEqual(len(acc.media_groups), 1)
        self.assertEqual(len(acc.media_groups[0]), 2)

    def test_clone_single_copy_failure_reuploads_without_forward(self):
        message = _Message(102, photo=_Photo("p12"))
        acc = _RestrictedAcc(
            copy_error=ValueError("Can't copy this message"),
        )

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [message],
            None,
            False,
            False,
        )

        self.assertEqual((count, used_fallback), (1, True))
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_102.jpg"],
        )
        self.assertEqual(acc.forwarded, [])
        self.assertEqual(len(acc.sent), 1)
        self.assertEqual(acc.sent[0][0], "send_photo")

    def test_mixed_group_clone_reuploads_uncopyable_item_without_forward(self):
        first = _Message(103, "album", photo=_Photo("p13"))
        second = _Message(104, "album", photo=_Photo("p14"))

        def item_copy_error(args, kwargs):
            if args[2] == first.id:
                return ValueError("Can't copy this message")
            return None

        acc = _RestrictedAcc(
            media_group=[first, second],
            album_error=ValueError("Message with this type can't be copied."),
            item_copy_error=item_copy_error,
        )

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [first, second],
            None,
            False,
            False,
        )

        self.assertEqual((count, used_fallback), (2, True))
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_103.jpg"],
        )
        self.assertEqual([call[0][2] for call in acc.copied], [103, 104])
        self.assertEqual(acc.forwarded, [])
        self.assertEqual(len(acc.sent), 1)
        self.assertEqual(acc.sent[0][0], "send_photo")

    def test_direct_group_uses_native_forward_without_copies(self):
        first = _Message(111, "album", photo=_Photo("p19"))
        second = _Message(112, "album", photo=_Photo("p20"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            forward_error=False,
        )

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [first, second],
            None,
            False,
            True,
        )

        self.assertEqual((count, used_fallback), (2, False))
        self.assertEqual(acc.copied, [])
        self.assertEqual(acc.downloaded, [])
        self.assertEqual(len(acc.forwarded), 1)
        self.assertEqual(acc.forwarded[0][0][2], [111, 112])

    def test_direct_group_forward_failure_uses_per_item_forwards(self):
        first = _Message(113, "album", photo=_Photo("p21"))
        second = _Message(114, "album", photo=_Photo("p22"))

        def forward_error(args, kwargs):
            if isinstance(args[2], list):
                return ValueError("album forwarding failed")
            return None

        acc = _RestrictedAcc(
            media_group=[first, second],
            forward_error=forward_error,
        )

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [first, second],
            None,
            False,
            True,
        )

        self.assertEqual((count, used_fallback), (2, False))
        self.assertEqual(acc.copied, [])
        self.assertEqual(acc.downloaded, [])
        self.assertEqual([call[0][2] for call in acc.forwarded], [[113, 114], 113, 114])

    def test_restricted_mixed_group_reuploads_only_uncopyable_item(self):
        first = _Message(109, "album", photo=_Photo("p17"), caption="受限图片")
        second = _Message(110, "album", photo=_Photo("p18"))

        def item_copy_error(args, kwargs):
            if args[2] == first.id:
                return ValueError("Can't copy this message")
            return None

        acc = _RestrictedAcc(
            media_group=[first, second],
            album_error=ValueError("Message with this type can't be copied."),
            item_copy_error=item_copy_error,
        )

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [first, second],
            "受限图片",
            False,
            False,
        )

        self.assertEqual((count, used_fallback), (2, True))
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_109.jpg"],
        )
        self.assertEqual([call[0][2] for call in acc.copied], [109, 110])
        self.assertEqual(acc.forwarded, [])
        self.assertEqual(len(acc.sent), 1)
        self.assertEqual(acc.sent[0][0], "send_photo")

    def test_modified_caption_never_uses_forward_fallback(self):
        first = _Message(105, "album", photo=_Photo("p15"), caption="原始说明")
        second = _Message(106, "album", photo=_Photo("p16"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            album_error=ChatForwardsRestricted(
                400,
                "CHAT_FORWARDS_RESTRICTED",
            ),
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
        self.assertEqual(acc.forwarded, [])
        self.assertEqual(acc.media_groups[0][0].caption, "清理后的说明")

    def test_unsupported_non_downloadable_group_has_clear_error(self):
        first = _Message(107, "album")
        second = _Message(108, "album")
        first.media = MessageMediaType.CONTACT
        second.media = MessageMediaType.CONTACT
        acc = _RestrictedAcc(
            media_group=[first, second],
            album_error=ValueError("Message with this type can't be copied."),
            item_copy_error=ValueError("Can't copy this message"),
        )

        with self.assertRaises(RuntimeError) as raised:
            batch_forward._forward_batch_unit(
                _Worker(),
                acc,
                -1001234567890,
                -1009876543210,
                [first, second],
                None,
                False,
                False,
            )

        self.assertIn("无法缓存复制且不可下载", str(raised.exception))
        self.assertEqual(acc.downloaded, [])

    def test_modified_caption_is_kept_when_group_copy_falls_back(self):
        first = _Message(
            90,
            "album",
            animation=_Animation("a3"),
            caption="原始说明",
        )
        second = _Message(91, "album", photo=_Photo("p9"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            album_error=ValueError("Message with this type can't be copied."),
            item_copy_error=None,
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

        self.assertEqual((count, used_fallback), (2, False))
        self.assertEqual(acc.copied[0][1]["caption"], "清理后的说明")
        self.assertNotIn("caption", acc.copied[1][1])

    def test_media_enum_names_are_recognized(self):
        message = _Message(95, animation=_Animation("a4"))
        message.media = MessageMediaType.ANIMATION
        self.assertEqual(get_message_type(message), "Animation")

    def test_video_note_album_skips_native_copy_and_reuploads_every_item(self):
        first = _Message(
            70,
            "album",
            video_note=_VideoNote("vn1"),
            caption="视频动态说明",
        )
        second = _Message(71, "album", photo=_Photo("p7"))
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
            None,
            False,
            False,
        )

        self.assertEqual((count, used_fallback), (2, True))
        self.assertEqual(acc.get_media_group_calls, [])
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_70.jpg", "item_71.jpg"],
        )
        self.assertEqual(len(acc.media_groups), 1)
        self.assertEqual(len(acc.media_groups[0]), 2)

    def test_single_video_note_uploads_with_original_format_after_copy_failure(self):
        message = _Message(72, video_note=_VideoNote("vn2"))
        acc = _RestrictedAcc()

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [message],
            None,
            False,
            False,
        )

        self.assertEqual((count, used_fallback), (1, True))
        self.assertEqual(len(acc.sent), 1)
        self.assertEqual(acc.sent[0][0], "send_video_note")
        self.assertTrue(acc.sent[0][1][1].endswith("item_72.jpg"))

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
