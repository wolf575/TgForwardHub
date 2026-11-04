import threading
import unittest
from unittest import mock

import batch_forward


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
        self.group_sends = []

    def send_media_group(self, destination, media):
        self.group_sends.append((destination, media))
        return []


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

    def test_native_media_group_send_keeps_per_item_captions(self):
        messages = [
            _FakeMessage(1, caption="第一条", media_group_id="group"),
            _FakeMessage(2, caption="第二条", media_group_id="group"),
        ]
        client = _FakeClient()

        batch_forward._send_media_group_with_captions(
            client,
            -1001,
            messages,
            ["第一条", ""],
        )

        self.assertEqual(len(client.group_sends), 1)
        media = client.group_sends[0][1]
        self.assertEqual([item.caption for item in media], ["第一条", ""])

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

        batch_forward._forward_batch_media_group(
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

        media = client.group_sends[0][1]
        self.assertEqual([item.caption for item in media], cleaned)


class BatchProgressTests(unittest.TestCase):
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
