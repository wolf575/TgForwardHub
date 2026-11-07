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
        self.edited_captions = []
        self._message_id = 1000
        self._random_id = 1

    def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    def copy_message(self, *args, **kwargs):
        self.copied.append((args, kwargs))

    def copy_media_group(self, *args, **kwargs):
        self.group_copies.append((args, kwargs))
        result = []
        for _ in range(2):
            self._message_id += 1
            result.append(
                type("Sent", (), {"id": self._message_id})()
            )
        return result

    def forward_messages(self, destination, source, message_ids):
        ids = message_ids if isinstance(message_ids, list) else [message_ids]
        return [
            type("Sent", (), {"id": message_id})()
            for message_id in ids
        ]

    def edit_message_caption(self, destination, message_id, caption):
        self.edited_captions.append((destination, message_id, caption))
        return type(
            "Sent",
            (),
            {"id": message_id, "caption": caption},
        )()

    def resolve_peer(self, peer):
        return peer

    def rnd_id(self):
        self._random_id += 1
        return self._random_id

    def invoke(self, query):
        ids = list(getattr(query, "id", []) or [])
        return type(
            "Result",
            (),
            {
                "updates": [
                    type(
                        "Update",
                        (),
                        {
                            "message": type(
                                "Sent",
                                (),
                                {"id": message_id},
                            )()
                        },
                    )()
                    for message_id in ids
                ]
            },
        )()


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

    def test_media_group_empty_caption_updates_every_item_in_every_mode(self):
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
                self.assertEqual(
                    acc.group_copies[0][1]["captions"],
                    [batch_forward._EMPTY_CAPTION_SENTINEL, None],
                )
                self.assertEqual(
                    [caption for _dest, _msg_id, caption in acc.edited_captions],
                    [""],
                )


class BatchRuntimeControlTests(unittest.TestCase):
    def test_batch_notification_contains_detailed_counts(self):
        title, content = batch_forward._batch_notification_payload(
            "nightly",
            "job-1",
            "done",
            {
                "total": 20,
                "processed": 20,
                "success": 17,
                "failed": 2,
                "skipped": 1,
                "elapsed_seconds": 8.5,
            },
        )

        self.assertIn("执行完成", title)
        self.assertIn("总数: 20", content)
        self.assertIn("已处理: 20", content)
        self.assertIn("成功: 17", content)
        self.assertIn("失败: 2", content)
        self.assertIn("跳过: 1", content)
        self.assertIn("耗时: 8.5 秒", content)

    def test_batch_notification_uses_configured_notifier(self):
        with mock.patch.object(
            batch_forward,
            "client_batch_notifications_enabled",
            return_value=True,
        ), mock.patch.object(
            batch_forward,
            "get_notify_config",
            return_value={"TG_BOT_TOKEN": "token", "TG_USER_ID": "1"},
        ), mock.patch("notify.send_with_config") as send:
            batch_forward._send_batch_notification(
                "nightly",
                "job-1",
                "error",
                {"processed": 1, "failed": 1},
                RuntimeError("boom"),
            )

        send.assert_called_once()
        self.assertIn("错误: boom", send.call_args.args[1])
        self.assertEqual(
            send.call_args.args[2],
            {"TG_BOT_TOKEN": "token", "TG_USER_ID": "1"},
        )

    def test_batch_notification_respects_disabled_setting(self):
        with mock.patch.object(
            batch_forward,
            "client_batch_notifications_enabled",
            return_value=False,
        ), mock.patch("notify.send_with_config") as send:
            batch_forward._send_batch_notification(
                "nightly",
                "job-1",
                "done",
                {"processed": 1},
            )

        send.assert_not_called()

    def test_list_active_tasks_includes_running_and_paused_only(self):
        running = _task("running-job", _base_spec())
        paused = _task("paused-job", _base_spec(), status="paused")
        done = _task("done-job", _base_spec())
        done["status"] = "done"
        done["active"] = False

        with mock.patch.dict(
            batch_forward.TASKS,
            {
                "running-job": running,
                "paused-job": paused,
                "done-job": done,
            },
            clear=True,
        ):
            tasks = batch_forward.list_active_tasks()

        self.assertEqual(
            {item["jobId"] for item in tasks},
            {"running-job", "paused-job"},
        )

    def test_unchanged_filter_rules_compile_once_per_task(self):
        job_id = "compile-once-job"
        spec = _base_spec()
        task = _task(job_id, spec)
        acc = _RunAcc(
            {
                1: _Message(1, text="first"),
                2: _Message(2, text="second"),
            }
        )

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
            return_value=(1, False),
        ), mock.patch.object(
            batch_forward,
            "get_bot_instance",
            return_value=None,
        ), mock.patch.object(
            batch_forward,
            "_persist_task_history",
        ), mock.patch.object(
            batch_forward,
            "_filter_rule_set",
            wraps=batch_forward._filter_rule_set,
        ) as build_rules:
            batch_forward._run_batch_task(job_id, spec)

        self.assertEqual(build_rules.call_count, 1)

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

    def test_cancel_immediately_before_send_prevents_extra_message(self):
        job_id = "cancel-before-send-job"
        spec = _base_spec()
        task = _task(job_id, spec)
        acc = _RunAcc({1: _Message(1, text="must-not-send")})
        wait_calls = 0

        def cancel_before_send(_task_id, _log=None):
            nonlocal wait_calls
            wait_calls += 1
            if wait_calls >= 3:
                task["cancelled"] = True
                task["status"] = "cancelled"
                return False
            return True

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
            return_value=[1],
        ), mock.patch.object(
            batch_forward,
            "_get_private_media_group_messages",
            side_effect=lambda _acc, _source, message: [message],
        ), mock.patch.object(
            batch_forward,
            "_forward_batch_unit",
        ) as forward, mock.patch.object(
            batch_forward,
            "get_bot_instance",
            return_value=None,
        ), mock.patch.object(
            batch_forward,
            "_persist_task_history",
        ), mock.patch.object(
            batch_forward,
            "_wait_until_task_active",
            side_effect=cancel_before_send,
        ):
            batch_forward._run_batch_task(job_id, spec)

        forward.assert_not_called()
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["progress"]["phase"], "cancelled")


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

    def test_active_tasks_endpoint(self):
        with mock.patch.object(
            batch_forward,
            "list_active_tasks",
            return_value=[{"jobId": "job", "status": "running"}],
        ):
            response = self.client.get("/api/batch-forward/active")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()[0]["jobId"], "job")

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
