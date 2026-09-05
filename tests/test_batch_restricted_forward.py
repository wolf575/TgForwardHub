import os
import re
import tempfile
import unittest
from unittest import mock

from pyrogram import raw
from pyrogram.enums import MessageMediaType
from pyrogram.errors import ChatForwardsRestricted, Timeout as TelegramTimeout
from pyrogram.types import InputMediaPhoto, MessageEntity

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
        hidden_forward_error="restricted",
        cached_send_error="restricted",
    ):
        self.media_group = media_group or []
        self.album_error = album_error
        self.copy_error = (
            ChatForwardsRestricted(
                400,
                "CHAT_FORWARDS_RESTRICTED",
            )
            if copy_error is None
            else copy_error
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
        self.group_copies = []
        self.forwarded = []
        self.get_media_group_calls = []
        self.hidden_forwards = []
        self.resolved_peers = []
        self.invoked_queries = []
        self.cached_media_groups = []
        self._next_rnd_id = 800000000
        self.hidden_forward_error = (
            ChatForwardsRestricted(
                400,
                "CHAT_FORWARDS_RESTRICTED",
            )
            if hidden_forward_error == "restricted"
            else hidden_forward_error
        )
        self.cached_send_error = (
            self.hidden_forward_error
            if cached_send_error == "restricted"
            else cached_send_error
        )

    def copy_message(self, *args, **kwargs):
        self.copied.append((args, kwargs))
        error = self.item_copy_error
        if callable(error):
            error = error(args, kwargs)
        if error:
            raise error

    def copy_media_group(self, *args, **kwargs):
        self.group_copies.append((args, kwargs))
        error = self.album_error or self.copy_error
        if error:
            raise error

    def forward_messages(self, *args, **kwargs):
        self.forwarded.append((args, kwargs))
        error = self.forward_error
        if callable(error):
            error = error(args, kwargs)
        if error:
            raise error

    def resolve_peer(self, peer_id):
        self.resolved_peers.append(peer_id)
        return type("_Peer", (), {"peer_id": peer_id})()

    def rnd_id(self):
        self._next_rnd_id += 1
        return self._next_rnd_id

    def invoke(self, query):
        self.invoked_queries.append((type(query).__name__, query))
        if isinstance(
            query,
            (raw.functions.messages.SendMedia, raw.functions.messages.SendMultiMedia),
        ):
            error = self.cached_send_error
            if isinstance(query, raw.functions.messages.SendMultiMedia):
                self.cached_media_groups.append(query.multi_media)
        elif isinstance(query, raw.functions.messages.ForwardMessages):
            self.hidden_forwards.append(query)
            error = self.hidden_forward_error
        else:
            error = self.hidden_forward_error
        if callable(error):
            error = error(query)
        if error:
            raise error
        if isinstance(query, raw.functions.messages.ForwardMessages):
            return [
                type("_Forwarded", (), {"id": message_id})()
                for message_id in query.id
            ]
        return []

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


class _FlakyDownloadAcc:
    def __init__(self, results, download_error=None):
        self.results = list(results)
        self.download_error = download_error
        self.calls = []

    def download_media(self, item, file_name=None, **kwargs):
        self.calls.append((item.id, file_name))
        if self.download_error is not None:
            raise self.download_error
        return self.results.pop(0)


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

    def test_hidden_forward_failure_can_succeed_with_cached_send_media(self):
        message = _Message(140, photo=_Photo("p40"), caption="缓存说明")
        acc = _RestrictedAcc(
            hidden_forward_error=ValueError("hidden forward rejected"),
            cached_send_error=None,
        )

        with mock.patch.object(
            batch_forward.utils,
            "get_input_media_from_file_id",
            return_value=object(),
        ):
            count, used_fallback = batch_forward._forward_batch_unit(
                _Worker(),
                acc,
                -1001234567890,
                -1009876543210,
                [message],
                "缓存说明",
                False,
                False,
            )

        self.assertEqual((count, used_fallback), (1, False))
        self.assertEqual(acc.downloaded, [])
        self.assertEqual(acc.copied, [])
        self.assertEqual(
            [name for name, _query in acc.invoked_queries],
            ["ForwardMessages", "SendMedia"],
        )

    def test_cached_send_media_group_preserves_order_and_caption(self):
        first = _Message(141, "album", photo=_Photo("p41"), caption="原始说明")
        second = _Message(142, "album", photo=_Photo("p42"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            hidden_forward_error=ValueError("hidden forward rejected"),
            cached_send_error=None,
        )

        with mock.patch.object(
            batch_forward.utils,
            "get_input_media_from_file_id",
            return_value=object(),
        ):
            count, used_fallback = batch_forward._forward_batch_unit(
                _Worker(),
                acc,
                -1001234567890,
                -1009876543210,
                [first, second],
                "原始说明",
                False,
                False,
            )

        self.assertEqual((count, used_fallback), (2, False))
        self.assertEqual(acc.downloaded, [])
        self.assertEqual(acc.copied, [])
        self.assertEqual(len(acc.cached_media_groups), 1)
        media_items = acc.cached_media_groups[0]
        self.assertEqual(len(media_items), 2)
        self.assertEqual(media_items[0].message, "原始说明")
        self.assertEqual(media_items[1].message, "")

    def test_cached_send_media_preserves_real_caption_entities(self):
        message = _Message(
            145,
            photo=_Photo("p45"),
            caption="加粗文本和链接",
        )
        message.caption_entities = [
            MessageEntity(type="bold", offset=0, length=4),
            MessageEntity(
                type="text_link",
                offset=5,
                length=4,
                url="https://example.com",
            ),
        ]
        acc = _RestrictedAcc(
            hidden_forward_error=ValueError("hidden forward rejected"),
            cached_send_error=None,
        )

        with mock.patch.object(
            batch_forward.utils,
            "get_input_media_from_file_id",
            return_value=object(),
        ):
            count, used_fallback = batch_forward._forward_batch_unit(
                _Worker(),
                acc,
                -1001234567890,
                -1009876543210,
                [message],
                "加粗文本和链接",
                False,
                False,
            )

        self.assertEqual((count, used_fallback), (1, False))
        send_media = [
            query
            for name, query in acc.invoked_queries
            if name == "SendMedia"
        ]
        self.assertEqual(len(send_media), 1)
        entities = send_media[0].entities
        self.assertIsNotNone(entities)
        self.assertEqual(
            [type(entity).__name__ for entity in entities],
            ["MessageEntityBold", "MessageEntityTextUrl"],
        )
        self.assertEqual(entities[0].offset, 0)
        self.assertEqual(entities[0].length, 4)
        self.assertEqual(entities[1].offset, 5)
        self.assertEqual(entities[1].length, 4)
        self.assertEqual(entities[1].url, "https://example.com")

    def test_only_cached_send_restriction_downloads_media(self):
        first = _Message(143, "album", photo=_Photo("p43"))
        second = _Message(144, "album", photo=_Photo("p44"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            hidden_forward_error=ValueError("hidden forward rejected"),
            cached_send_error=ChatForwardsRestricted(
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
            None,
            False,
            False,
        )

        self.assertEqual((count, used_fallback), (2, True))
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_143.jpg", "item_144.jpg"],
        )

    def test_batch_status_recovers_from_history(self):
        history = {
            "jobId": "job-history",
            "status": "done",
            "exitCode": 0,
            "progress": {"processed": 7, "success": 7},
            "stdoutTail": "任务完成",
            "stderrTail": "",
            "task_spec": {"source": "@source"},
        }

        with mock.patch.object(
            batch_forward,
            "get_task",
            return_value={},
        ), mock.patch.object(
            batch_forward,
            "get_history_record",
            return_value=history,
        ):
            status = batch_forward.batch_status("job-history")

        self.assertEqual(status["jobId"], "job-history")
        self.assertEqual(status["status"], "done")
        self.assertEqual(status["progress"]["processed"], 7)
        self.assertEqual(status["stdoutTail"], "任务完成")
        self.assertEqual(status["spec"], {"source": "@source"})

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

    def test_clone_single_media_uses_user_hidden_forward_first(self):
        message = _Message(200, photo=_Photo("p28"))
        acc = _RestrictedAcc(
            item_copy_error=False,
            hidden_forward_error=None,
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

        self.assertEqual((count, used_fallback), (1, False))
        self.assertEqual(len(acc.hidden_forwards), 1)
        self.assertEqual(list(acc.hidden_forwards[0].id), [200])
        self.assertIs(acc.hidden_forwards[0].drop_author, True)
        self.assertEqual(acc.copied, [])
        self.assertEqual(acc.downloaded, [])
        self.assertEqual(acc.forwarded, [])

    def test_clone_media_group_uses_user_hidden_forward_first(self):
        first = _Message(201, "album", photo=_Photo("p29"))
        second = _Message(202, "album", photo=_Photo("p30"))
        acc = _RestrictedAcc(
            album_error=False,
            copy_error=False,
            item_copy_error=False,
            hidden_forward_error=None,
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

        self.assertEqual((count, used_fallback), (2, False))
        self.assertEqual(len(acc.hidden_forwards), 1)
        self.assertEqual(list(acc.hidden_forwards[0].id), [201, 202])
        self.assertIs(acc.hidden_forwards[0].drop_author, True)
        self.assertEqual(acc.downloaded, [])
        self.assertEqual(acc.forwarded, [])

    def test_modified_caption_uses_user_cached_copy(self):
        message = _Message(203, photo=_Photo("p31"), caption="原始说明")
        acc = _RestrictedAcc(item_copy_error=False)

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [message],
            "清理后的说明",
            True,
            False,
        )

        self.assertEqual((count, used_fallback), (1, False))
        self.assertEqual(acc.hidden_forwards, [])
        self.assertEqual(acc.copied[0][1]["caption"], "清理后的说明")

    def test_hidden_forward_failure_falls_back_to_user_cached_copy(self):
        message = _Message(204, photo=_Photo("p32"))
        acc = _RestrictedAcc(item_copy_error=False)

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

        self.assertEqual((count, used_fallback), (1, False))
        self.assertEqual(len(acc.hidden_forwards), 1)
        self.assertEqual([call[0][2] for call in acc.copied], [204])
        self.assertEqual(acc.downloaded, [])

    def test_hidden_forward_and_user_copy_failure_reuploads_without_forward(self):
        message = _Message(205, photo=_Photo("p33"))
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
        self.assertEqual(len(acc.hidden_forwards), 1)
        self.assertEqual(len(acc.copied), 1)
        self.assertEqual(acc.forwarded, [])
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_205.jpg"],
        )

    def test_restricted_source_cache_skips_repeated_cached_copy_attempts(self):
        source_id = -1001234567890
        dest_id = -1009876543210
        first = _Message(300, "album", photo=_Photo("p300"))
        second = _Message(301, "album", photo=_Photo("p301"))
        acc = _RestrictedAcc(
            media_group=[first, second],
            album_error=ChatForwardsRestricted(
                400,
                "CHAT_FORWARDS_RESTRICTED",
            ),
        )
        restricted_sources = set()

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            source_id,
            dest_id,
            [first, second],
            None,
            False,
            False,
            restricted_source_ids=restricted_sources,
        )

        self.assertEqual((count, used_fallback), (2, True))
        self.assertEqual(restricted_sources, {source_id})
        self.assertEqual(len(acc.hidden_forwards), 1)
        self.assertEqual(len(acc.group_copies), 1)
        self.assertEqual(acc.copied, [])
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_300.jpg", "item_301.jpg"],
        )

        acc.hidden_forwards.clear()
        acc.group_copies.clear()
        acc.copied.clear()
        acc.downloaded.clear()
        acc.sent.clear()
        next_message = _Message(302, photo=_Photo("p302"))

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            source_id,
            dest_id,
            [next_message],
            None,
            False,
            False,
            restricted_source_ids=restricted_sources,
        )

        self.assertEqual((count, used_fallback), (1, True))
        self.assertEqual(acc.hidden_forwards, [])
        self.assertEqual(acc.group_copies, [])
        self.assertEqual(acc.copied, [])
        self.assertEqual(
            [os.path.basename(path) for path in acc.downloaded],
            ["item_302.jpg"],
        )
        self.assertEqual(len(acc.sent), 1)
        self.assertEqual(acc.sent[0][0], "send_photo")

    def test_direct_mode_does_not_use_hidden_forward_or_copy(self):
        message = _Message(206, photo=_Photo("p34"))
        acc = _RestrictedAcc(forward_error=False)

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [message],
            None,
            False,
            True,
        )

        self.assertEqual((count, used_fallback), (1, False))
        self.assertEqual(acc.hidden_forwards, [])
        self.assertEqual(acc.copied, [])
        self.assertEqual(len(acc.forwarded), 1)
        self.assertEqual(acc.forwarded[0][0][2], 206)

    def test_direct_mode_modified_caption_uses_user_cached_copy(self):
        message = _Message(207, photo=_Photo("p35"), caption="原始说明")
        acc = _RestrictedAcc(item_copy_error=False)

        count, used_fallback = batch_forward._forward_batch_unit(
            _Worker(),
            acc,
            -1001234567890,
            -1009876543210,
            [message],
            "修改后的说明",
            True,
            True,
        )

        self.assertEqual((count, used_fallback), (1, False))
        self.assertEqual(acc.hidden_forwards, [])
        self.assertEqual(acc.copied[0][1]["caption"], "修改后的说明")
        self.assertEqual(acc.forwarded, [])

    def test_batch_module_has_no_bot_instance_import(self):
        self.assertFalse(hasattr(batch_forward, "get_bot_instance"))

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

    def test_download_none_is_retried_until_success(self):
        message = _Message(120, photo=_Photo("p23"))
        acc = _FlakyDownloadAcc(
            [None, None, os.path.join("tmp", "item_120.jpg")]
        )

        with mock.patch.object(batch_forward.time, "sleep"):
            path = batch_forward._download_batch_media_with_retry(
                acc,
                message,
                os.path.join("tmp", ""),
                None,
            )

        self.assertTrue(path.endswith("item_120.jpg"))
        self.assertEqual(len(acc.calls), 3)

    def test_download_telegram_timeout_is_retried(self):
        message = _Message(121, photo=_Photo("p24"))
        acc = _FlakyDownloadAcc([])
        calls = []

        def fail_once(item, file_name=None, **kwargs):
            calls.append(item.id)
            if len(calls) == 1:
                raise TelegramTimeout(
                    503,
                    rpc_name="upload.GetFile",
                )
            return os.path.join("tmp", "item_121.jpg")

        acc.download_media = fail_once

        with mock.patch.object(batch_forward.time, "sleep"):
            path = batch_forward._download_batch_media_with_retry(
                acc,
                message,
                os.path.join("tmp", ""),
                None,
            )

        self.assertTrue(path.endswith("item_121.jpg"))
        self.assertEqual(calls, [121, 121])

    def test_download_none_exhaustion_keeps_clear_error(self):
        message = _Message(122, photo=_Photo("p25"))
        acc = _FlakyDownloadAcc([None, None, None])

        with mock.patch.object(batch_forward.time, "sleep"):
            with self.assertRaises(RuntimeError) as raised:
                batch_forward._download_batch_media_with_retry(
                    acc,
                    message,
                    os.path.join("tmp", ""),
                    None,
                )

        self.assertIn("未返回文件数据", str(raised.exception))
        self.assertEqual(len(acc.calls), 3)

    def test_download_zero_byte_file_is_retried_and_removed(self):
        message = _Message(123, photo=_Photo("p36"))
        with tempfile.TemporaryDirectory() as work_dir:
            empty_path = os.path.join(work_dir, "empty.jpg")
            valid_path = os.path.join(work_dir, "valid.jpg")
            open(empty_path, "wb").close()
            with open(valid_path, "wb") as valid_file:
                valid_file.write(b"photo")
            acc = _FlakyDownloadAcc([empty_path, valid_path])

            with mock.patch.object(batch_forward.time, "sleep"):
                path = batch_forward._download_batch_media_with_retry(
                    acc,
                    message,
                    os.path.join(work_dir, ""),
                    None,
                )

            self.assertEqual(path, valid_path)
            self.assertEqual(len(acc.calls), 2)
            self.assertFalse(os.path.exists(empty_path))

    def test_media_group_retries_one_none_item_without_redownloading_others(self):
        first = _Message(130, "album", photo=_Photo("p26"))
        second = _Message(131, "album", photo=_Photo("p27"))
        acc = _FlakyDownloadAcc(
            [
                None,
                os.path.join("tmp", "item_130.jpg"),
                os.path.join("tmp", "item_131.jpg"),
            ]
        )

        with mock.patch.object(batch_forward.time, "sleep"):
            messages, downloads, work_dir = (
                batch_forward._download_batch_media_group_with_retry(
                    acc,
                    -1001234567890,
                    [first, second],
                    None,
                    attempts=2,
                )
            )

        try:
            self.assertEqual([item.id for item in messages], [130, 131])
            self.assertEqual(
                [os.path.basename(path) for _item, path, _thumb in downloads],
                ["item_130.jpg", "item_131.jpg"],
            )
            self.assertEqual([call[0] for call in acc.calls], [130, 130, 131])
        finally:
            import shutil

            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
