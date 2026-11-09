import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import batch_forward


class _HistoryAcc:
    def __init__(self, messages):
        self.messages = list(messages)
        self.yielded = 0
        self.reverse = None

    def get_chat_history(self, _source_id, offset_date=None, reverse=False):
        self.reverse = reverse
        for message in self.messages:
            self.yielded += 1
            yield message


class BatchStreamRateTests(unittest.TestCase):
    def test_rate_limit_defaults_to_25_and_rejects_zero(self):
        spec = batch_forward._validate_task_spec(
            {
                "source": "-1001",
                "target": "-1002",
                "range_type": "id",
                "start": 1,
                "end": 2,
            }
        )
        self.assertEqual(spec["rate_limit_per_minute"], 25)

        with self.assertRaises(ValueError):
            batch_forward._validate_task_spec(
                {
                    "source": "-1001",
                    "target": "-1002",
                    "range_type": "id",
                    "start": 1,
                    "end": 2,
                    "rate_limit_per_minute": 0,
                }
            )

    def test_rate_limiter_waits_when_window_is_full(self):
        clock = [0.0]
        sleeps = []
        progress = []

        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        with mock.patch.object(
            batch_forward.time,
            "monotonic",
            side_effect=lambda: clock[0],
        ), mock.patch.object(
            batch_forward.time,
            "sleep",
            side_effect=sleep,
        ):
            limiter = batch_forward.BatchRateLimiter(
                2,
                progress_callback=lambda seconds: progress.append(seconds),
            )
            limiter.wait()
            limiter.wait()
            limiter.wait()

        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 59)
        self.assertEqual(len(progress), 1)

    def test_time_range_yields_first_batch_before_scan_finishes(self):
        base = datetime(2026, 11, 9, tzinfo=timezone.utc)
        messages = [
            SimpleNamespace(
                id=index,
                date=datetime(2026, 11, 9, 0, index, tzinfo=timezone.utc),
                text=f"message {index}",
                caption=None,
                media_group_id=None,
            )
            for index in range(1, 4)
        ]
        acc = _HistoryAcc(messages)
        cache = {}
        spec = {
            "range_type": "time",
            "start": str(int(base.timestamp())),
            "end": str(int(base.timestamp()) + 86399),
            "reverse": False,
        }

        with mock.patch.object(batch_forward, "BATCH_FETCH_CHUNK_SIZE", 2):
            chunks = batch_forward._iter_batch_chunks(
                acc,
                None,
                -1001,
                spec,
                cache,
            )
            first = next(chunks)

        self.assertEqual(first[0], [1, 2])
        self.assertEqual(first[2], 2)
        self.assertEqual(acc.yielded, 2)
        self.assertTrue(acc.reverse)
        self.assertIn(1, cache)


if __name__ == "__main__":
    unittest.main()
