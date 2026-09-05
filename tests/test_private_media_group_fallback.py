import os
import shutil
import tempfile
import unittest

from pyrogram.enums import MessageMediaType
from pyrogram.types import InputMediaPhoto

from bot.handlers.messages import (
    _build_private_media_group_inputs,
    _download_private_media_group,
    _download_private_media_thumbnail,
    _forward_private_media_group_by_download,
    _get_private_media_group_messages,
    _send_downloaded_private_media_group,
    _should_forward_private_media_group,
)


class _Photo:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []


class _Video:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []
        self.width = 1280
        self.height = 720
        self.duration = 5
        self.supports_streaming = True


class _Document:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []


class _VideoNote:
    def __init__(self, file_id):
        self.file_id = file_id
        self.thumbs = []
        self.duration = 4
        self.length = 512


class _Contact:
    def __init__(self):
        self.phone_number = "123"
        self.first_name = "Contact"
        self.last_name = None
        self.vcard = None


class _Message:
    def __init__(
        self,
        message_id,
        media_group_id=None,
        photo=None,
        video=None,
        document=None,
        video_note=None,
        contact=None,
        caption=None,
        text=None,
    ):
        self.id = message_id
        self.chat = type("Chat", (), {"id": 123456})()
        self.media_group_id = media_group_id
        self.photo = photo
        self.video = video
        self.document = document
        self.video_note = video_note
        self.contact = contact
        self.caption = caption
        self.text = text
        self.caption_entities = None
        self.has_media_spoiler = False


class _StatusMessage:
    def __init__(self, message_id=9001):
        self.id = message_id
        self.chat = type("Chat", (), {"id": 123456})()


class _Acc:
    def __init__(self, media_group):
        self.media_group = media_group
        self.calls = []

    def get_media_group(self, chat_id, message_id):
        self.calls.append(("get_media_group", chat_id, message_id))
        return self.media_group

    def download_media(self, item, file_name, progress=None, progress_args=None):
        self.calls.append(
            (
                "download_media",
                item.id,
                file_name,
                progress is not None,
            )
        )
        if "thumb_" in file_name:
            return file_name
        if getattr(item, "contact", None) is not None:
            raise ValueError(
                "This message doesn't contain any downloadable media"
            )
        return os.path.join(file_name, f"item_{item.id}.jpg")


class _Bot:
    def __init__(self, group_error=None):
        self.group_error = group_error
        self.calls = []
        self.media_groups = []

    def send_message(self, *args, **kwargs):
        self.calls.append(("send_message", args, kwargs))
        return _StatusMessage()

    def edit_message_text(self, *args, **kwargs):
        self.calls.append(("edit_message_text", args, kwargs))

    def send_media_group(self, chat_id, media):
        self.calls.append(("send_media_group", chat_id, media))
        self.media_groups.append(media)
        if self.group_error:
            raise self.group_error
        return [_StatusMessage(9100), _StatusMessage(9101)]

    def send_photo(self, *args, **kwargs):
        self.calls.append(("send_photo", args, kwargs))

    def send_video(self, *args, **kwargs):
        self.calls.append(("send_video", args, kwargs))

    def send_video_note(self, *args, **kwargs):
        self.calls.append(("send_video_note", args, kwargs))

    def send_document(self, *args, **kwargs):
        self.calls.append(("send_document", args, kwargs))

    def delete_messages(self, *args, **kwargs):
        self.calls.append(("delete_messages", args, kwargs))


class _EmptyThumbnailPayload:
    def __init__(self, file_id):
        self.thumbs = [type("_Thumb", (), {"file_id": file_id})()]


class _EmptyThumbnailAcc:
    def __init__(self, file_path):
        self.file_path = file_path

    def download_media(self, _item, file_name=None, **kwargs):
        path = file_name or self.file_path
        open(path, "wb").close()
        return path


class _RetryAlbumBot:
    def __init__(self):
        self.calls = []

    def send_media_group(self, chat_id, media):
        self.calls.append(media)
        if len(self.calls) == 1:
            raise ValueError("File size equals to 0 B")
        return [_StatusMessage(9200), _StatusMessage(9201)]


class PrivateMediaGroupFallbackTests(unittest.TestCase):
    def test_single_query_and_single_id_select_the_album(self):
        self.assertTrue(
            _should_forward_private_media_group(
                _Message(1, text="https://t.me/c/1234567890/45?single")
            )
        )
        self.assertTrue(
            _should_forward_private_media_group(
                _Message(1, text="https://t.me/c/1234567890/45")
            )
        )
        self.assertFalse(
            _should_forward_private_media_group(
                _Message(1, text="https://t.me/c/1234567890/45-48")
            )
        )

    def test_group_resolution_orders_messages_and_keeps_anchor(self):
        first = _Message(10, "album", photo=_Photo("p1"))
        second = _Message(11, "album", photo=_Photo("p2"))
        acc = _Acc([second, first])

        group = _get_private_media_group_messages(acc, -1001234567890, first)

        self.assertEqual([item.id for item in group], [10, 11])

    def test_download_and_upload_sends_every_group_item(self):
        first = _Message(10, "album", photo=_Photo("p1"), caption="album caption")
        second = _Message(11, "album", photo=_Photo("p2"))
        acc = _Acc([first, second])
        bot = _Bot()
        command = _Message(55)

        _forward_private_media_group_by_download(
            command,
            bot,
            acc,
            -1001234567890,
            second,
        )

        downloads = [
            call for call in acc.calls if call[0] == "download_media"
        ]
        self.assertEqual([call[1] for call in downloads], [10, 11])
        self.assertEqual(len(bot.media_groups), 1)
        media = bot.media_groups[0]
        self.assertEqual(len(media), 2)
        self.assertIsInstance(media[0], InputMediaPhoto)
        self.assertIsInstance(media[1], InputMediaPhoto)
        self.assertEqual(media[0].caption, "album caption")
        self.assertEqual(media[1].caption, "")
        self.assertTrue(media[0].media.endswith("item_10.jpg"))
        self.assertTrue(media[1].media.endswith("item_11.jpg"))
        self.assertIn(
            ("delete_messages", (123456, [9001]), {}),
            bot.calls,
        )

    def test_album_failure_falls_back_to_individual_uploads(self):
        first = _Message(20, "album", video=_Video("v1"))
        second = _Message(21, "album", document=_Document("d1"))
        acc = _Acc([first, second])
        bot = _Bot(group_error=RuntimeError("album rejected"))
        command = _Message(66)

        _forward_private_media_group_by_download(
            command,
            bot,
            acc,
            -1001234567890,
            second,
        )

        sent_kinds = [
            call[0]
            for call in bot.calls
            if call[0] in ("send_video", "send_document")
        ]
        self.assertEqual(sent_kinds, ["send_video", "send_document"])

    def test_video_note_album_uses_native_note_when_album_upload_fails(self):
        first = _Message(30, "album", video_note=_VideoNote("vn1"))
        second = _Message(31, "album", document=_Document("d1"))
        acc = _Acc([first, second])
        bot = _Bot(group_error=RuntimeError("album rejected"))
        command = _Message(77)

        _forward_private_media_group_by_download(
            command,
            bot,
            acc,
            -1001234567890,
            second,
        )

        sent_kinds = [
            call[0]
            for call in bot.calls
            if call[0] in ("send_video_note", "send_document")
        ]
        self.assertEqual(sent_kinds, ["send_video_note", "send_document"])

    def test_download_skips_non_downloadable_group_items(self):
        contact = _Message(40, "album", contact=_Contact())
        contact.media = MessageMediaType.CONTACT
        photo = _Message(41, "album", photo=_Photo("p8"))
        acc = _Acc([contact, photo])

        group_messages, downloads, work_dir = _download_private_media_group(
            acc,
            -1001234567890,
            contact,
            group_messages=[contact, photo],
        )
        try:
            self.assertEqual([item.id for item in group_messages], [41])
            self.assertEqual([item.id for item, _path, _thumb in downloads], [41])
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_empty_thumbnail_is_removed_before_album_input_is_built(self):
        item = _Message(50, "album", video=_Video("v3"))
        work_dir = tempfile.mkdtemp()
        try:
            media_path = os.path.join(work_dir, "item_50.mp4")
            thumb_path = os.path.join(work_dir, "thumb_0.jpg")
            with open(media_path, "wb") as media_file:
                media_file.write(b"video")
            open(thumb_path, "wb").close()

            inputs = _build_private_media_group_inputs(
                [item],
                [(item, media_path, thumb_path)],
            )

            self.assertEqual(len(inputs), 1)
            self.assertIsNone(inputs[0].thumb)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_empty_thumbnail_download_is_deleted_and_ignored(self):
        with tempfile.TemporaryDirectory() as work_dir:
            acc = _EmptyThumbnailAcc(os.path.join(work_dir, "thumb_0.jpg"))
            payload = _EmptyThumbnailPayload("thumbnail-file-id")

            thumb = _download_private_media_thumbnail(
                acc,
                payload,
                work_dir,
                0,
            )

            self.assertIsNone(thumb)
            self.assertFalse(os.path.exists(acc.file_path))

    def test_album_retries_without_thumbnails_before_item_fallback(self):
        first = _Message(51, "album", video=_Video("v4"))
        second = _Message(52, "album", video=_Video("v5"))
        bot = _RetryAlbumBot()
        with tempfile.TemporaryDirectory() as work_dir:
            thumb_path = os.path.join(work_dir, "thumb_1.jpg")
            with open(thumb_path, "wb") as thumb_file:
                thumb_file.write(b"thumbnail")
            downloads = [
                (first, os.path.join(work_dir, "item_51.mp4"), thumb_path),
                (second, os.path.join(work_dir, "item_52.mp4"), None),
            ]

            message_id = _send_downloaded_private_media_group(
                bot,
                123456,
                [first, second],
                downloads,
            )

            self.assertEqual(message_id, 9200)
            self.assertEqual(len(bot.calls), 2)
            self.assertIsNotNone(bot.calls[0][0].thumb)
            self.assertIsNone(bot.calls[1][0].thumb)


if __name__ == "__main__":
    unittest.main()
