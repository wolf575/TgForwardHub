import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import batch_forward
from pyrogram.enums import MessageEntityType
from pyrogram.types import MessageEntity
from pyrogram.types.messages_and_media.message import Str

try:
    from pyrogram.types import TextQuote
except ImportError:
    TextQuote = None


USER_REGEX = r"(?s)后续内容进会员群查看.*\Z"


class _Photo:
    file_id = "photo-file-id"


class _FakeMessage:
    def __init__(self, message_id, caption=None, text=None, media_group_id=None):
        self.id = message_id
        self.caption = caption
        self.text = text
        self.media_group_id = media_group_id
        self.photo = _Photo() if caption is not None else None
        self.empty = False
        self.chat = None


class _FakeClient:
    def __init__(self):
        self.invocations = []
        self.copied_groups = []
        self.copied_group_kwargs = []
        self.edited_captions = []
        self.copy_result = None
        self._random_id = 100
        self._message_id = 1000

    def rnd_id(self):
        self._random_id += 1
        return self._random_id

    def copy_media_group(self, destination, source, message_id, **kwargs):
        self.copied_groups.append((destination, source, message_id))
        self.copied_group_kwargs.append(kwargs)
        if self.copy_result is not None:
            return self.copy_result
        result = []
        for _ in range(2):
            self._message_id += 1
            result.append(
                SimpleNamespace(id=self._message_id, caption="original")
            )
        return result

    def edit_message_caption(self, destination, message_id, caption):
        self.edited_captions.append((destination, message_id, caption))
        return SimpleNamespace(id=message_id, caption=caption)

    def resolve_peer(self, peer):
        return peer

    def invoke(self, query):
        self.invocations.append(query)
        ids = list(getattr(query, "id", []) or [])
        if not ids:
            return query
        return SimpleNamespace(
            updates=[
                SimpleNamespace(message=SimpleNamespace(id=message_id))
                for message_id in ids
            ]
        )


class _FakeAcc:
    def __init__(self):
        self.batch_calls = []

    def get_messages(self, source_id, message_ids):
        self.batch_calls.append(list(message_ids))
        return [
            _FakeMessage(message_id, text=f"message-{message_id}")
            for message_id in message_ids
        ]


class _FakeWorker:
    def __init__(self, *_args, **_kwargs):
        pass

    def _execute_with_flood_retry(self, _name, operation):
        return operation()


def _task(job_id):
    event = threading.Event()
    event.set()
    return {
        "id": job_id,
        "status": "running",
        "active": True,
        "exitCode": None,
        "cancelled": False,
        "paused": False,
        "resume_event": event,
        "progress": {},
        "stdoutTail": "",
        "stderrTail": "",
        "spec": {},
        "taskName": "filter-progress",
        "sourceId": "source",
        "targetId": "target",
        "createdAt": "2026-11-04T20:00:00+08:00",
        "state": {},
    }


class BatchFilterTests(unittest.TestCase):
    def test_multiline_regex_matches_without_explicit_dotall(self):
        message = _FakeMessage(1, caption="开头\n后续内容进会员群查看\n广告尾部")
        rules = batch_forward._filter_rule_set(
            {
                "remove_regex": "后续内容进会员群查看.*",
            }
        )

        filtered = batch_forward._apply_filter_rules([message], rules)

        self.assertTrue(filtered["text_changed"])
        self.assertEqual(filtered["cleaned_texts"], ["开头\n"])

    def test_media_group_result_ids_preserve_returned_order(self):
        result = [
            SimpleNamespace(id=203),
            SimpleNamespace(id=201),
            SimpleNamespace(id=202),
        ]

        self.assertEqual(
            batch_forward._result_message_ids(result),
            [203, 201, 202],
        )

    def test_no_filter_rules_skip_rich_text_normalization(self):
        message = _FakeMessage(1, caption="普通说明")
        rules = batch_forward._filter_rule_set(
            {
                "range_type": "id",
                "start": 1,
                "end": 1,
            }
        )

        with mock.patch.object(
            batch_forward,
            "_group_filter_texts",
        ) as group_filter_texts:
            filtered = batch_forward._apply_filter_rules([message], rules)

        group_filter_texts.assert_not_called()
        self.assertEqual(filtered["cleaned_texts"], ["普通说明"])
        self.assertFalse(filtered["text_changed"])

    def test_filters_consider_every_media_group_caption(self):
        first = _FakeMessage(1, caption="正常标题", media_group_id="group")
        second = _FakeMessage(
            2,
            caption="正常标题\n后续内容进会员群查看 👉\n广告尾部",
            media_group_id="group",
        )
        texts = batch_forward._group_texts([first, second])
        patterns = batch_forward._compile_regex_patterns(USER_REGEX)

        self.assertEqual(len(texts), 2)
        self.assertTrue(
            any(batch_forward._matches_exclude_regex(text, patterns) for text in texts)
        )
        cleaned = [
            batch_forward._remove_matches(text, [], patterns)
            for text in texts
        ]
        self.assertEqual(cleaned[0], "正常标题")
        self.assertEqual(cleaned[1], "正常标题\n")

    def test_copy_media_group_sends_filtered_captions_before_edit(self):
        messages = [
            _FakeMessage(1, caption="第一条", media_group_id="group"),
            _FakeMessage(2, caption="第二条", media_group_id="group"),
        ]
        client = _FakeClient()
        client.copy_result = [
            SimpleNamespace(id=101, caption="第一条"),
            SimpleNamespace(id=102, caption="第二条"),
        ]

        batch_forward._copy_media_group_and_set_captions(
            _FakeWorker(),
            client,
            -1002,
            -1001,
            messages[0].id,
            ["第一条", ""],
            group_messages=messages,
        )

        self.assertEqual(client.copied_groups, [(-1002, -1001, 1)])
        self.assertEqual(
            client.copied_group_kwargs,
            [{"captions": ["第一条", batch_forward._EMPTY_CAPTION_SENTINEL]}],
        )
        self.assertEqual(
            client.edited_captions,
            [(-1002, 102, "")],
        )

    def test_caption_verification_falls_back_to_post_send_edit(self):
        messages = [
            _FakeMessage(1, caption="原始第一条", media_group_id="group"),
            _FakeMessage(2, caption="原始第二条", media_group_id="group"),
        ]

        class _WrongCaptionClient(_FakeClient):
            def get_messages(self, _destination, message_ids):
                return [
                    SimpleNamespace(id=message_id, caption="原始文本")
                    for message_id in message_ids
                ]

        client = _WrongCaptionClient()
        client.copy_result = [
            SimpleNamespace(id=101, caption="原始文本"),
            SimpleNamespace(id=102, caption="原始文本"),
        ]

        batch_forward._copy_media_group_and_set_captions(
            _FakeWorker(),
            client,
            -1002,
            -1001,
            messages[0].id,
            ["过滤后第一条", "过滤后第二条"],
            group_messages=messages,
        )

        self.assertEqual(
            client.edited_captions,
            [
                (-1002, 101, "过滤后第一条"),
                (-1002, 102, "过滤后第二条"),
            ],
        )

    def test_forwarded_group_uses_cleaned_caption_for_non_first_item(self):
        messages = [
            _FakeMessage(1, caption="第一条", media_group_id="group"),
            _FakeMessage(
                2,
                caption="第二条\n后续内容进会员群查看 👉\n广告尾部",
                media_group_id="group",
            ),
        ]
        client = _FakeClient()
        cleaned = ["第一条", "第二条\n"]

        sent_count, used_fallback = batch_forward._forward_batch_media_group(
            _FakeWorker(),
            client,
            -1001,
            -1002,
            messages,
            cleaned[1],
            True,
            False,
            cleaned_texts=cleaned,
        )

        self.assertEqual(sent_count, 2)
        self.assertFalse(used_fallback)
        self.assertEqual(client.edited_captions, [])
        self.assertEqual(
            client.copied_group_kwargs,
            [{"captions": ["第一条", "第二条\n"]}],
        )

    def test_multi_item_media_group_preserves_source_order(self):
        first = _FakeMessage(1, caption="第一项", media_group_id="group")
        second = _FakeMessage(2, caption="第二项", media_group_id="group")
        second.photo = None
        second.video = SimpleNamespace(file_id="video-file-id")
        third = _FakeMessage(3, caption="第三项", media_group_id="group")
        client = _FakeClient()

        client.copy_result = [
            SimpleNamespace(id=201, caption="第一项"),
            SimpleNamespace(id=202, caption="第二项"),
            SimpleNamespace(id=203, caption="第三项"),
        ]
        batch_forward._copy_media_group_and_set_captions(
            _FakeWorker(),
            client,
            -1002,
            -1001,
            first.id,
            ["第一项", "", "第三项"],
            group_messages=[first, second, third],
        )

        self.assertEqual(
            client.copied_groups,
            [(-1002, -1001, 1)],
        )
        self.assertEqual(
            client.copied_group_kwargs,
            [
                {
                    "captions": [
                        "第一项",
                        batch_forward._EMPTY_CAPTION_SENTINEL,
                        "第三项",
                    ]
                }
            ],
        )
        self.assertEqual(
            [caption for _destination, _message_id, caption in client.edited_captions],
            [""],
        )

    def test_cancelled_fallback_does_not_upload_after_download(self):
        message = _FakeMessage(1, caption="广告", media_group_id="group")
        waits = iter([True, False])

        with mock.patch.object(
            batch_forward,
            "_download_batch_media_group_with_retry",
            return_value=([message], [(message, "fake.jpg", None)], "fake-dir"),
        ), mock.patch.object(
            batch_forward,
            "_send_downloaded_private_media_group",
        ) as send_group:
            with self.assertRaises(batch_forward.BatchTaskStopped):
                batch_forward._reupload_batch_media_group(
                    _FakeWorker(),
                    _FakeClient(),
                    -1001,
                    -1002,
                    [message],
                    "",
                    True,
                    wait_for_active=lambda: next(waits),
                )

        send_group.assert_not_called()

    def test_exclude_rule_sees_quote_and_reply_preview_text(self):
        message = _FakeMessage(1, text="正常正文")
        message.quote_text = USER_REGEX
        rules = batch_forward._filter_rule_set(
            {
                "range_type": "id",
                "start": 1,
                "end": 1,
                "exclude_regex": USER_REGEX,
            }
        )

        filtered = batch_forward._apply_filter_rules([message], rules)

        self.assertTrue(filtered["excluded"])

        quote_object_message = _FakeMessage(1, text="普通正文")
        quote_object_message.quote = SimpleNamespace(text=USER_REGEX)
        filtered_quote_object = batch_forward._apply_filter_rules(
            [quote_object_message],
            rules,
        )

        self.assertTrue(filtered_quote_object["excluded"])
        self.assertTrue(filtered_quote_object["quote_text_present"])

        reply_message = _FakeMessage(1, text="普通回复")
        reply_message.reply_to_message = _FakeMessage(2, text=USER_REGEX)
        filtered_reply = batch_forward._apply_filter_rules(
            [reply_message],
            rules,
        )

        self.assertTrue(filtered_reply["excluded"])

        link_message = _FakeMessage(1, text="链接消息")
        link_message.web_page = SimpleNamespace(
            title=USER_REGEX,
            description=None,
        )
        filtered_link = batch_forward._apply_filter_rules(
            [link_message],
            rules,
        )

        self.assertTrue(filtered_link["excluded"])

    @unittest.skipUnless(TextQuote is not None, "Pyrofork quote support required")
    def test_pyrofork_text_quote_is_filtered_and_removed_as_plain_text(self):
        message = _FakeMessage(1, text="保留正文")
        message.quote = TextQuote(
            text=Str(USER_REGEX).init([]),
            entities=None,
            position=0,
            is_manual=True,
        )
        rules = batch_forward._filter_rule_set(
            {
                "range_type": "id",
                "start": 1,
                "end": 1,
                "remove_regex": USER_REGEX,
            }
        )

        filtered = batch_forward._apply_filter_rules([message], rules)

        self.assertFalse(filtered["excluded"])
        self.assertTrue(filtered["quote_text_present"])
        self.assertTrue(filtered["text_changed"])
        self.assertTrue(filtered["rich_content_changed"])
        self.assertEqual(filtered["cleaned_texts"], ["保留正文"])

    def test_pyrofork_web_page_preview_title_is_filtered(self):
        message = _FakeMessage(1, text="链接消息")
        message.web_page_preview = SimpleNamespace(
            title=USER_REGEX,
            description=None,
        )
        rules = batch_forward._filter_rule_set(
            {
                "range_type": "id",
                "start": 1,
                "end": 1,
                "exclude_regex": USER_REGEX,
            }
        )

        filtered = batch_forward._apply_filter_rules([message], rules)

        self.assertTrue(filtered["excluded"])

    def test_delete_rule_on_quote_preview_removes_the_quote_without_changing_text(self):
        message = _FakeMessage(1, text="保留正文")
        message.reply_to_message = _FakeMessage(2, text=USER_REGEX)
        rules = batch_forward._filter_rule_set(
            {
                "range_type": "id",
                "start": 1,
                "end": 1,
                "remove_regex": USER_REGEX,
            }
        )

        filtered = batch_forward._apply_filter_rules([message], rules)

        self.assertFalse(filtered["excluded"])
        self.assertEqual(filtered["cleaned_texts"], ["保留正文"])
        self.assertTrue(filtered["text_changed"])
        self.assertTrue(filtered["rich_content_changed"])

    def test_blockquote_entity_text_remains_filterable(self):
        message = _FakeMessage(1, text=USER_REGEX)
        message.entities = [
            SimpleNamespace(
                type="blockquote",
                offset=0,
                length=len(USER_REGEX),
            )
        ]
        rules = batch_forward._filter_rule_set(
            {
                "range_type": "id",
                "start": 1,
                "end": 1,
                "exclude_regex": USER_REGEX,
            }
        )

        filtered = batch_forward._apply_filter_rules([message], rules)

        self.assertTrue(filtered["excluded"])

    def test_invisible_format_characters_are_removed_before_filtering(self):
        formatted_text = (
            "保留正文\n后续\u200b内容进会员群查看\ufe0f 👉\n广告尾部"
        )
        formatted = Str(formatted_text).init(
            [
                MessageEntity(
                    type=MessageEntityType.BLOCKQUOTE,
                    offset=0,
                    length=len(formatted_text),
                )
            ]
        )
        message = _FakeMessage(1, text=formatted)
        message.entities = formatted.entities
        rules = batch_forward._filter_rule_set(
            {
                "range_type": "id",
                "start": 1,
                "end": 1,
                "remove_regex": USER_REGEX,
            }
        )

        filtered = batch_forward._apply_filter_rules([message], rules)

        self.assertFalse(filtered["excluded"])
        self.assertTrue(filtered["text_changed"])
        self.assertEqual(filtered["cleaned_texts"], ["保留正文\n"])

    def test_formatted_text_with_fullwidth_characters_uses_plain_filter_view(self):
        message = _FakeMessage(
            1,
            text="后续内容进会员群查看（全角括号）",
        )
        rules = batch_forward._filter_rule_set(
            {
                "range_type": "id",
                "start": 1,
                "end": 1,
                "exclude_regex": r"(?s)后续内容进会员群查看.*\Z",
            }
        )

        filtered = batch_forward._apply_filter_rules([message], rules)

        self.assertTrue(filtered["excluded"])


class BatchProgressTests(unittest.TestCase):
    def test_batch_task_resends_plain_text_when_quote_preview_matches_delete_rule(self):
        job_id = "quote-delete-job"
        task = _task(job_id)
        message = _FakeMessage(1, text="保留正文")
        message.reply_to_message = _FakeMessage(2, text=USER_REGEX)
        acc = mock.Mock()
        acc.get_messages.return_value = [message]
        forwarded = []

        def forward_unit(*args, **_kwargs):
            forwarded.append(args)
            return 1, False

        with mock.patch.dict(batch_forward.TASKS, {job_id: task}, clear=True), \
             mock.patch.object(batch_forward, "get_acc_instance", return_value=acc), \
             mock.patch.object(batch_forward, "get_bot_instance", return_value=None), \
             mock.patch.object(
                 batch_forward,
                 "_resolve_chat",
                 side_effect=lambda _client, ref: int(ref),
             ), \
             mock.patch.object(
                 batch_forward,
                 "_resolve_source_username",
                 return_value=None,
             ), \
             mock.patch.object(
                 batch_forward,
                 "_collect_message_ids",
                 return_value=[1],
             ), \
             mock.patch.object(
                 batch_forward,
                 "_get_private_media_group_messages",
                 side_effect=lambda _client, _source, item: [item],
             ), \
             mock.patch.object(
                 batch_forward,
                 "_forward_batch_unit",
                 side_effect=forward_unit,
             ), \
             mock.patch.object(batch_forward, "MessageWorker", _FakeWorker), \
             mock.patch.object(
                 batch_forward,
                 "_persist_task_history",
                 return_value=None,
             ):
            batch_forward._run_batch_task(
                job_id,
                {
                    "source": "-1001",
                    "target": "-1002",
                    "range_type": "id",
                    "start": 1,
                    "end": 1,
                    "forward_mode": "clone",
                    "exclude_keywords": "",
                    "exclude_regex": "",
                    "remove_keywords": "",
                    "remove_regex": USER_REGEX,
                },
            )

        self.assertEqual(len(forwarded), 1)
        self.assertEqual(forwarded[0][5], "保留正文")
        self.assertTrue(forwarded[0][6])
        self.assertIn("引用、回复或链接预览命中删除规则", task["stdoutTail"])

    def test_large_task_uses_batched_message_reads_and_reports_progress(self):
        job_id = "progress-job"
        task = _task(job_id)
        acc = _FakeAcc()
        forwarded_phases = []

        def forward_unit(*_args, **_kwargs):
            forwarded_phases.append(
                batch_forward.get_task(job_id).get("progress", {}).get("phase")
            )
            return 1, False

        with mock.patch.dict(batch_forward.TASKS, {job_id: task}, clear=True), \
             mock.patch.object(batch_forward, "get_acc_instance", return_value=acc), \
             mock.patch.object(batch_forward, "get_bot_instance", return_value=None), \
             mock.patch.object(
                 batch_forward,
                 "_resolve_chat",
                 side_effect=lambda _client, ref: int(ref),
             ), \
             mock.patch.object(
                 batch_forward,
                 "_resolve_source_username",
                 return_value=None,
             ), \
             mock.patch.object(
                 batch_forward,
                 "_collect_message_ids",
                 return_value=list(range(1, 251)),
             ), \
             mock.patch.object(
                 batch_forward,
                 "_get_private_media_group_messages",
                 side_effect=lambda _client, _source, message: [message],
             ), \
             mock.patch.object(
                 batch_forward,
                 "_forward_batch_unit",
                 side_effect=forward_unit,
             ), \
             mock.patch.object(
                 batch_forward,
                 "MessageWorker",
                 _FakeWorker,
             ), \
             mock.patch.object(
                 batch_forward,
                 "_persist_task_history",
                 return_value=None,
             ):
            batch_forward._run_batch_task(
                job_id,
                {
                    "source": "-1001",
                    "target": "-1002",
                    "range_type": "id",
                    "start": 1,
                    "end": 250,
                    "forward_mode": "clone",
                    "exclude_keywords": "",
                    "exclude_regex": "",
                    "remove_keywords": "",
                    "remove_regex": "",
                },
            )

        self.assertEqual([len(call) for call in acc.batch_calls], [100, 100, 50])
        self.assertIn("forwarding", forwarded_phases)
        progress = task["progress"]
        self.assertEqual(progress["phase"], "done")
        self.assertEqual(progress["total"], 250)
        self.assertEqual(progress["processed"], 250)
        self.assertEqual(progress["percent"], 100.0)


if __name__ == "__main__":
    unittest.main()
