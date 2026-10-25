import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import batch_forward
from app_settings import get_app_timezone


class _HistoryAcc:
    def __init__(self, messages):
        self.messages = messages
        self.offset_date = None

    def get_chat_history(self, source_id, offset_date=None):
        self.offset_date = offset_date
        return iter(self.messages)


def _history_record(record_id, task_name, created_at, status="done"):
    return {
        "id": record_id,
        "taskName": task_name,
        "targetId": "@target",
        "sourceId": "@source",
        "outputPath": "",
        "task_spec": {"task_name": task_name},
        "createdAt": created_at,
        "state": {"taskName": task_name},
        "jobId": record_id,
        "status": status,
        "exitCode": 0,
        "progress": {"processed": 1},
        "stdoutTail": "",
        "stderrTail": "",
    }


class BatchHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "history.db")
        self.db_patch = mock.patch.object(
            batch_forward,
            "HISTORY_DB",
            self.db_path,
        )
        self.db_patch.start()
        batch_forward.init_history_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_same_task_name_replaces_previous_history(self):
        batch_forward.save_history(
            _history_record("old-job", " Daily Sync ", "2026-10-24T10:00:00+08:00")
        )
        batch_forward.save_history(
            _history_record("new-job", "daily sync", "2026-10-25T10:00:00+08:00")
        )

        history = batch_forward.list_history()

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["id"], "new-job")
        self.assertEqual(history[0]["taskName"], "daily sync")

    def test_init_history_db_removes_legacy_duplicate_names(self):
        with batch_forward._history_conn() as conn:
            conn.execute("DROP INDEX idx_history_unique_task_name")
            for record in (
                _history_record("older", "Daily", "2026-10-23T10:00:00+08:00"),
                _history_record("newer", " daily ", "2026-10-24T10:00:00+08:00"),
            ):
                conn.execute(
                    """
                    INSERT INTO history (
                        id, taskName, targetId, sourceId, outputPath, task_spec,
                        createdAt, state, jobId, status, exitCode, progress,
                        stdoutTail, stderrTail
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        record["taskName"],
                        record["targetId"],
                        record["sourceId"],
                        record["outputPath"],
                        json.dumps(record["task_spec"]),
                        record["createdAt"],
                        json.dumps(record["state"]),
                        record["jobId"],
                        record["status"],
                        record["exitCode"],
                        json.dumps(record["progress"]),
                        record["stdoutTail"],
                        record["stderrTail"],
                    ),
                )

        batch_forward.init_history_db()
        history = batch_forward.list_history()

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["id"], "newer")

    def test_time_range_includes_the_end_date(self):
        start = int(
            datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc).timestamp()
        )
        end = int(
            datetime(2026, 10, 24, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        )
        messages = [
            type(
                "Message",
                (),
                {
                    "id": 3,
                    "date": datetime(
                        2026, 10, 24, 23, 0, tzinfo=timezone.utc
                    ),
                },
            )(),
            type(
                "Message",
                (),
                {
                    "id": 2,
                    "date": datetime(
                        2026, 10, 24, 12, 0, tzinfo=timezone.utc
                    ),
                },
            )(),
            type(
                "Message",
                (),
                {
                    "id": 1,
                    "date": datetime(
                        2026, 10, 23, 23, 0, tzinfo=timezone.utc
                    ),
                },
            )(),
        ]
        acc = _HistoryAcc(messages)

        ids = batch_forward._collect_message_ids(
            acc,
            -1001234567890,
            {
                "range_type": "time",
                "start": str(start),
                "end": str(end),
                "reverse": False,
            },
        )

        self.assertEqual(ids, [2, 3])

    def test_date_string_end_boundary_is_end_of_day(self):
        expected = int(
            datetime(
                2026,
                10,
                24,
                23,
                59,
                59,
                tzinfo=get_app_timezone(),
            ).timestamp()
        )

        self.assertEqual(
            batch_forward._parse_timestamp("2026-10-24", end_of_day=True),
            expected,
        )

    def test_duplicate_active_task_name_is_rejected(self):
        active = {
            "id": "active-job",
            "taskName": "Daily Sync",
            "status": "running",
            "active": True,
        }
        spec = {
            "task_name": " daily sync ",
            "source": "@source",
            "target": "@target",
            "range_type": "id",
            "start": 1,
            "end": 1,
        }

        with mock.patch.dict(batch_forward.TASKS, {"active-job": active}, clear=True):
            with self.assertRaisesRegex(ValueError, "同名任务正在运行"):
                batch_forward.submit_batch_task(spec)

    def test_completed_task_cannot_be_cancelled(self):
        completed = {
            "id": "done-job",
            "status": "done",
            "active": False,
            "cancelled": False,
        }

        with mock.patch.dict(batch_forward.TASKS, {"done-job": completed}, clear=True):
            self.assertFalse(batch_forward.cancel_batch_task("done-job"))

        self.assertFalse(completed["cancelled"])
        self.assertEqual(completed["status"], "done")


if __name__ == "__main__":
    unittest.main()
