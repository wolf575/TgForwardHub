import threading
import time
import unittest
from unittest import mock

import batch_forward


USER_SAMPLE = (
    "后续内容进会员群查看 👉\n"
    "🔞2026年7月17日|内部群独家整理合集|自费购买|会员群稳定更新\n"
    "‼️原价288元限时永久会员福利价只需88元‼️，会员群无二次收费持续更新中"
    "会员群资源可转发收藏，且还有内部群专属防走失,先到先得！"
    "过了这个村就没这个店了！！ @zf886bot 扫码拉你入群。"
)
USER_REGEX = r"(?s)后续内容进会员群查看.*\Z"


class _Photo:
    file_id = "photo"
    thumbs = []


class _Message:
    def __init__(
        self,
        message_id,
        text=None,
        caption=None,
        photo=None,
        media_group_id=None,
    ):
        self.id = message_id
        self.text = text
        self.caption = caption
        self.caption_entities = None
        self.entities = None
        self.photo = photo
        self.media_group_id = media_group_id
        self.empty = False
        self.chat = type(
            "Chat",
            (),
            {"id": -1001234567890, "username": "source"},
        )()


class _SendAcc:
    def __init__(self):
        self.sent = []
        self.copied = []
        self.group_copies = []

    def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    def copy_message(self, *args, **kwargs):
        self.copied.append((args, kwargs))

    def copy_media_group(self, *args, **kwargs):
        self.group_copies.append((args, kwargs))


class _RunAcc:
    def __init__(self, messages):
        self.messages = messages

    def get_messages(self, source_id, message_id):
        if isinstance(message_id, (list, tuple)):
            return [self.messages.get(item) for item in message_id]
        return self.messages[message_id]


class _RunWorker:
    def __init__(self, *_args, **_kwargs):
        pass

    def _execute_with_flood_retry(self, _name, operation):
        return operation()


def _task(job_id, spec, status="running"):
    event = threading.Event()
    if status != "paused":
        event.set()
    return {
        "id": job_id,
        "status": status,
        "active": True,
        "exitCode": None,
        "cancelled": False,
        "paused": status == "paused",
        "resume_event": event,
        "progress": {},
        "stdoutTail": "",
        "stderrTail": "",
        "spec": dict(spec),
        "taskName": spec.get("task_name") or "",
        "sourceId": str(spec.get("source") or ""),
        "targetId": str(spec.get("target") or ""),
        "createdAt": "2026-11-04T12:00:00+08:00",
        "state": {
            "taskName": spec.get("task_name") or "",
            "sourceId": spec.get("source") or "",
            "targetId": spec.get("target") or "",
            "excludeKeywords": spec.get("exclude_keywords") or "",
            "excludeRegex": spec.get("exclude_regex") or "",
            "removeKeywords": spec.get("remove_keywords") or "",
            "removeRegex": spec.get("remove_regex") or "",
        },
    }


def _base_spec(**overrides):
    spec = {
        "task_name": "runtime-controls",
        "source": "source",
        "target": "target",
        "range_type": "id",
        "start": 1,
        "end": 2,
        "forward_mode": "clone",
        "exclude_keywords": "",
        "exclude_regex": "",
        "remove_keywords": "",
        "remove_regex": "",
    }
    spec.update(overrides)
    return spec


class BatchRegexForwardingTests(unittest.TestCase):
    def test_user_reported_delete_regex_removes_the_entire_tail(self):
        patterns = batch_forward._compile_regex_patterns(USER_REGEX)

        self.assertEqual(
            batch_forward._remove_matches(USER_SAMPLE, [], patterns),
            "",
        )

    def test_user_reported_exclude_regex_matches_the_sample(self):
        patterns = batch_forward._compile_regex_patterns(
            r"(?s)后续内容进会员群查看"
        )

        self.assertTrue(
            batch_forward._matches_exclude_regex(USER_SAMPLE, patterns)
        )

    def test_text_cleanup_is_used_in_every_forward_mode(self):
        text = f"保留正文\n{USER_SAMPLE}"
        patterns = batch_forward._compile_regex_patterns(USER_REGEX)
        cleaned = batch_forward._remove_matches(text, [], patterns)

        for mode in ("clone", "direct", "cache"):
            with self.subTest(mode=mode):
                message = _Message(1, text=text)
                acc = _SendAcc()
                count, fallback = batch_forward._forward_batch_unit(
                    _RunWorker(),
                    acc,
                    -1001,
                    -1002,
                    [message],
                    cleaned,
                    True,
                    mode == "direct",
                    cache_send=mode == "cache",
                )
                self.assertEqual((count, fallback), (1, False))
                self.assertEqual(acc.sent[0][0], (-1002, "保留正文\n"))
                self.assertEqual(acc.copied, [])
                self.assertEqual(acc.group_copies, [])

    def test_single_media_cleanup_is_used_in_every_forward_mode(self):
        caption = f"保留正文\n{USER_SAMPLE}"
        patterns = batch_forward._compile_regex_patterns(USER_REGEX)
        cleaned = batch_forward._remove_matches(caption, [], patterns)

        for mode in ("clone", "direct", "cache"):
            with self.subTest(mode=mode):
                message = _Message(2, caption=caption, photo=_Photo())
                acc = _SendAcc()
                count, fallback = batch_forward._forward_batch_unit(
                    _RunWorker(),
                    acc,
                    -1001,
                    -1002,
                    [message],
                    cleaned,
                    True,
                    mode == "direct",
                    cache_send=mode == "cache",
                )
                self.assertEqual((count, fallback), (1, False))
                self.assertEqual(acc.copied[0][1]["caption"], "保留正文\n")
                self.assertEqual(acc.sent, [])
                self.assertEqual(acc.group_copies, [])

    def test_media_group_empty_caption_uses_string_override_in_every_mode(self):
        first = _Message(
            3,
            caption=USER_SAMPLE,
            photo=_Photo(),
            media_group_id="album",
        )
        second = _Message(4, photo=_Photo(), media_group_id="album")

        for mode in ("clone", "direct", "cache"):
            with self.subTest(mode=mode):
                acc = _SendAcc()
                count, fallback = batch_forward._forward_batch_unit(
                    _RunWorker(),
                    acc,
                    -1001,
                    -1002,
                    [first, second],
                    "",
                    True,
                    mode == "direct",
                    cache_send=mode == "cache",
                )
                self.assertEqual((count, fallback), (2, False))
                caption_override = acc.group_copies[0][1]["captions"]
                self.assertIsInstance(caption_override, str)
                self.assertEqual(caption_override, "")


class BatchRuntimeControlTests(unittest.TestCase):
    def test_update_rules_changes_only_filter_fields(self):
        job_id = "rules-job"
        spec = _base_spec()
        task = _task(job_id, spec)

        with mock.patch.dict(
            batch_forward.TASKS,
            {job_id: task},
            clear=True,
        ), mock.patch.object(
            batch_forward,
            "_persist_task_history",
        ) as persist:
            updated = batch_forward.update_batch_rules(
                job_id,
                {
                    "remove_regex": USER_REGEX,
                    "exclude_keywords": "广告",
                },
            )

        self.assertEqual(updated["source"], "source")
        self.assertEqual(updated["remove_regex"], USER_REGEX)
        self.assertEqual(updated["exclude_keywords"], "广告")
        self.assertEqual(task["state"]["removeRegex"], USER_REGEX)
        self.assertEqual(task["state"]["excludeKeywords"], "广告")
        persist.assert_called_once_with(job_id)

    def test_invalid_runtime_regex_does_not_change_the_task(self):
        job_id = "invalid-rules-job"
        spec = _base_spec(remove_regex=USER_REGEX)
        task = _task(job_id, spec)

        with mock.patch.dict(
            batch_forward.TASKS,
            {job_id: task},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "删除正则"):
                batch_forward.update_batch_rules(
                    job_id,
                    {"remove_regex": "(?P<broken"},
                )

        self.assertEqual(task["spec"]["remove_regex"], USER_REGEX)

    def test_pause_resume_and_cancel_paused_task(self):
        job_id = "pause-job"
        task = _task(job_id, _base_spec())

        with mock.patch.dict(
            batch_forward.TASKS,
            {job_id: task},
            clear=True,
        ), mock.patch.object(batch_forward, "_persist_task_history"):
            self.assertTrue(batch_forward.pause_batch_task(job_id))
            self.assertEqual(task["status"], "paused")
            self.assertFalse(task["resume_event"].is_set())

            self.assertTrue(batch_forward.resume_batch_task(job_id))
            self.assertEqual(task["status"], "running")
            self.assertTrue(task["resume_event"].is_set())

            self.assertTrue(batch_forward.pause_batch_task(job_id))
            self.assertTrue(batch_forward.cancel_batch_task(job_id))
            self.assertTrue(task["cancelled"])
            self.assertEqual(task["status"], "cancelled")
            self.assertTrue(task["resume_event"].is_set())

    def test_running_task_uses_updated_exclude_rule_for_the_next_message(self):
        job_id = "live-rules-job"
        spec = _base_spec(remove_keywords="广告")
        task = _task(job_id, spec)
        acc = _RunAcc(
            {
                1: _Message(1, text="广告 A"),
                2: _Message(2, text="赞助 B"),
            }
        )
        forwarded = []

        def forward(*args, **_kwargs):
            cleaned_text = args[5]
            forwarded.append(cleaned_text)
            if len(forwarded) == 1:
                batch_forward.update_batch_rules(
                    job_id,
                    {
                        "remove_keywords": "",
                        "exclude_regex": "赞助",
                    },
                )
            return 1, False

        with mock.patch.dict(
            batch_forward.TASKS,
            {job_id: task},
            clear=True,
        ), mock.patch.object(
            batch_forward,
            "get_acc_instance",
            return_value=acc,
        ), mock.patch.object(
            batch_forward,
            "MessageWorker",
            _RunWorker,
        ), mock.patch.object(
            batch_forward,
            "_resolve_chat",
            side_effect=lambda _client, ref: -1001 if ref == "source" else -1002,
        ), mock.patch.object(
            batch_forward,
            "_resolve_source_username",
            return_value="source",
        ), mock.patch.object(
            batch_forward,
            "_collect_message_ids",
            return_value=[1, 2],
        ), mock.patch.object(
            batch_forward,
            "_get_private_media_group_messages",
            side_effect=lambda _acc, _source, message: [message],
        ), mock.patch.object(
            batch_forward,
            "_forward_batch_unit",
            side_effect=forward,
        ), mock.patch.object(
            batch_forward,
            "get_bot_instance",
            return_value=None,
        ), mock.patch.object(
            batch_forward,
            "_persist_task_history",
        ):
            batch_forward._run_batch_task(job_id, spec)

        self.assertEqual(forwarded, [" A"])
        self.assertEqual(task["status"], "done")
        self.assertFalse(task["active"])
        self.assertEqual(task["progress"]["processed"], 2)
        self.assertEqual(task["progress"]["skipped"], 1)

    def test_pause_waits_then_resumes_without_replaying_finished_message(self):
        job_id = "pause-resume-job"
        spec = _base_spec()
        task = _task(job_id, spec)
        acc = _RunAcc(
            {
                1: _Message(1, text="first"),
                2: _Message(2, text="second"),
            }
        )
        forwarded = []
        paused_seen = threading.Event()
        original_wait = batch_forward._wait_until_task_active

        def observed_wait(task_id, log=None):
            if batch_forward.get_task(task_id).get("paused"):
                paused_seen.set()
            return original_wait(task_id, log)

        def resume_after_pause():
            if paused_seen.wait(2):
                time.sleep(0.05)
                batch_forward.resume_batch_task(job_id)

        resume_thread = threading.Thread(
            target=resume_after_pause,
            daemon=True,
        )
        resume_thread.start()

        def forward(*args, **_kwargs):
            forwarded.append(args[4][0].id)
            if len(forwarded) == 1:
                batch_forward.pause_batch_task(job_id)
            return 1, False

        with mock.patch.dict(
            batch_forward.TASKS,
            {job_id: task},
            clear=True,
        ), mock.patch.object(
            batch_forward,
            "get_acc_instance",
            return_value=acc,
        ), mock.patch.object(
            batch_forward,
            "MessageWorker",
            _RunWorker,
        ), mock.patch.object(
            batch_forward,
            "_resolve_chat",
            side_effect=lambda _client, ref: -1001 if ref == "source" else -1002,
        ), mock.patch.object(
            batch_forward,
            "_resolve_source_username",
            return_value="source",
        ), mock.patch.object(
            batch_forward,
            "_collect_message_ids",
            return_value=[1, 2],
        ), mock.patch.object(
            batch_forward,
            "_get_private_media_group_messages",
            side_effect=lambda _acc, _source, message: [message],
        ), mock.patch.object(
            batch_forward,
            "_forward_batch_unit",
            side_effect=forward,
        ), mock.patch.object(
            batch_forward,
            "get_bot_instance",
            return_value=None,
        ), mock.patch.object(
            batch_forward,
            "_persist_task_history",
        ), mock.patch.object(
            batch_forward,
            "_wait_until_task_active",
            side_effect=observed_wait,
        ):
            batch_forward._run_batch_task(job_id, spec)

        resume_thread.join(timeout=2)
        self.assertFalse(resume_thread.is_alive())
        self.assertEqual(forwarded, [1, 2])
        self.assertEqual(task["status"], "done")
        self.assertIn("任务已暂停，等待继续", task["stdoutTail"])
        self.assertIn("任务已继续", task["stdoutTail"])


class BatchRuntimeApiTests(unittest.TestCase):
    def setUp(self):
        from app import app as flask_app

        self.client = flask_app.test_client()
        with self.client.session_transaction() as session:
            session["username"] = "admin"

    def test_rules_endpoint_updates_the_active_task(self):
        with mock.patch.object(
            batch_forward,
            "get_task",
            return_value={"id": "job"},
        ), mock.patch.object(
            batch_forward,
            "update_batch_rules",
            return_value={"source": "source", "remove_regex": USER_REGEX},
        ) as update:
            response = self.client.patch(
                "/api/batch-forward/job/rules",
                json={"remove_regex": USER_REGEX},
            )

        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with("job", {"remove_regex": USER_REGEX})

    def test_pause_and_resume_endpoints(self):
        with mock.patch.object(
            batch_forward,
            "get_task",
            return_value={"id": "job"},
        ), mock.patch.object(
            batch_forward,
            "pause_batch_task",
            return_value=True,
        ), mock.patch.object(
            batch_forward,
            "resume_batch_task",
            return_value=True,
        ):
            paused = self.client.post("/api/batch-forward/job/pause")
            resumed = self.client.post("/api/batch-forward/job/resume")

        self.assertEqual(paused.status_code, 200)
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(paused.get_json()["status"], "paused")
        self.assertEqual(resumed.get_json()["status"], "running")

    def test_single_history_delete_endpoint(self):
        with mock.patch.object(
            batch_forward,
            "get_history_record",
            return_value={"id": "done-job", "status": "done"},
        ), mock.patch.object(
            batch_forward,
            "delete_history_record",
            return_value=True,
        ) as delete:
            response = self.client.delete("/api/history/done-job")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        delete.assert_called_once_with("done-job")

    def test_active_history_delete_is_rejected(self):
        with mock.patch.object(
            batch_forward,
            "get_history_record",
            return_value={"id": "active-job", "status": "running"},
        ), mock.patch.object(
            batch_forward,
            "delete_history_record",
        ) as delete:
            response = self.client.delete("/api/history/active-job")

        self.assertEqual(response.status_code, 409)
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
