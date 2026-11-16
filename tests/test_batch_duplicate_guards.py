import unittest
from types import SimpleNamespace
from unittest import mock

import batch_forward


class _Worker:
    def _execute_with_flood_retry(self, _name, operation):
        return operation()


class _CopyFailingAcc:
    def __init__(self, target_messages):
        self.target_messages = target_messages

    def copy_media_group(self, *_args, **_kwargs):
        raise TypeError("post-send parse failure")

    def get_chat_history(self, _chat_id, limit=50):
        return list(self.target_messages[:limit])


def _photo_message(message_id, group_id, unique_id, caption=""):
    return SimpleNamespace(
        id=message_id,
        media_group_id=group_id,
        photo=SimpleNamespace(
            file_id=f"file-{unique_id}",
            file_unique_id=unique_id,
        ),
        video=None,
        document=None,
        audio=None,
        animation=None,
        voice=None,
        video_note=None,
        sticker=None,
        caption=caption,
        text=None,
    )


class BatchDuplicateGuardTests(unittest.TestCase):
    def tearDown(self):
        with batch_forward.RUNNING_BATCH_JOBS_LOCK:
            batch_forward.RUNNING_BATCH_JOBS.clear()
        with batch_forward.DELIVERY_LEDGER_LOCK:
            batch_forward.DELIVERY_LEDGER.clear()

    def test_batch_runner_claim_is_exclusive(self):
        self.assertTrue(batch_forward._claim_batch_runner("job"))
        self.assertFalse(batch_forward._claim_batch_runner("job"))
        batch_forward._release_batch_runner("job")
        self.assertTrue(batch_forward._claim_batch_runner("job"))

    def test_run_batch_task_rejects_second_runner_for_same_job(self):
        self.assertTrue(batch_forward._claim_batch_runner("job"))

        with mock.patch.object(
            batch_forward,
            "_run_batch_task_impl",
        ) as implementation:
            result = batch_forward._run_batch_task("job", {})

        self.assertIsNone(result)
        implementation.assert_not_called()

    def test_delivery_ledger_rejects_duplicate_unit(self):
        key = ("group", (10, 11))

        self.assertTrue(batch_forward._claim_delivery_unit("job", key))
        self.assertFalse(batch_forward._claim_delivery_unit("job", key))

    def test_target_group_detection_matches_copied_file_ids(self):
        source = [
            _photo_message(10, "source-group", "unique-1"),
            _photo_message(11, "source-group", "unique-2"),
        ]
        target = [
            _photo_message(110, "target-group", "unique-2"),
            _photo_message(109, "target-group", "unique-1"),
        ]
        acc = _CopyFailingAcc(target)

        self.assertTrue(
            batch_forward._target_contains_media_group(
                _Worker(),
                acc,
                -1002,
                source,
                attempts=1,
            )
        )

    def test_ambiguous_copy_error_is_success_when_target_has_group(self):
        source = [
            _photo_message(10, "source-group", "unique-1", "one"),
            _photo_message(11, "source-group", "unique-2", "two"),
        ]
        target = [
            _photo_message(110, "target-group", "unique-2", "two"),
            _photo_message(109, "target-group", "unique-1", "one"),
        ]
        acc = _CopyFailingAcc(target)

        with mock.patch.object(
            batch_forward,
            "_reupload_batch_media_group",
        ) as reupload:
            count, used_fallback = batch_forward._forward_batch_media_group(
                _Worker(),
                acc,
                -1001,
                -1002,
                source,
                "one",
                False,
                False,
            )

        self.assertEqual(count, 2)
        self.assertFalse(used_fallback)
        reupload.assert_not_called()

    def test_caption_cleanup_failure_does_not_escape_after_send(self):
        source = [
            _photo_message(10, "source-group", "unique-1", "广告一"),
            _photo_message(11, "source-group", "unique-2", "广告二"),
        ]
        client = mock.Mock()
        client.copy_media_group.return_value = object()
        worker = _Worker()

        result = batch_forward._copy_media_group_and_set_captions(
            worker,
            client,
            -1002,
            -1001,
            10,
            ["", ""],
            group_messages=source,
        )

        self.assertIsNotNone(result)
        client.edit_message_caption.assert_not_called()


if __name__ == "__main__":
    unittest.main()
