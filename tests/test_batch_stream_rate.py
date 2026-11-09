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
        self.calls = []

    def get_chat_history(
        self,
        _source_id,
        limit=0,
        offset=0,
        offset_id=0,
        offset_date=None,
        reverse=False,
    ):
        self.calls.append(
            {
                "limit": limit,
                "offset": offset,
                "offset_id": offset_id,
                "offset_date": offset_date,
                "reverse": reverse,
            }
        )
        self.reverse = reverse
        ordered = sorted(self.messages, key=lambda message: message.id)
        if reverse:
            candidates = [
                message
                for message in ordered
                if (not offset_id or message.id >= offset_id)
                and (offset_date is None or message.date > offset_date)
            ]
        else:
            candidates = [
                message
                for message in reversed(ordered)
                if (not offset_id or message.id < offset_id)
                and (offset_date is None or message.date < offset_date)
            ]
        page = candidates[: limit or len(candidates)]
        for message in page:
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

    def test_rate_limiter_enforces_spacing_and_rolling_window(self):
        clock = [0.0]
        sleeps = []

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
                jitter_ratio=0,
            )
            limiter.wait()
            limiter.wait()
            limiter.wait()

        self.assertGreaterEqual(clock[0], 59.9)
        self.assertTrue(sleeps)
        self.assertTrue(all(seconds <= 0.5 for seconds in sleeps))

    def test_rate_limiter_live_limit_update_changes_next_interval(self):
        clock = [0.0]
        sleeps = []

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
                1,
                jitter_ratio=0,
            )
            limiter.wait()
            limiter.set_limit(60)
            limiter.wait()

        self.assertGreaterEqual(clock[0], 0.99)
        self.assertLess(clock[0], 1.1)

    def test_rate_limiter_uses_random_jitter_between_sends(self):
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        random_source = mock.Mock()
        random_source.uniform.return_value = 1.2
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
                60,
                jitter_ratio=0.2,
                random_source=random_source,
            )
            limiter.wait()
            limiter.wait()

        self.assertGreaterEqual(clock[0], 1.19)
        self.assertLess(clock[0], 1.25)
        random_source.uniform.assert_called_with(0.8, 1.2)

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

    def test_time_range_forward_pagination_advances_without_replaying_pages(self):
        start = datetime(2026, 11, 9, tzinfo=timezone.utc)
        messages = [
            SimpleNamespace(
                id=index,
                date=datetime.fromtimestamp(start.timestamp() + index, timezone.utc),
                text=f"message {index}",
                caption=None,
                media_group_id=None,
            )
            for index in range(1, 206)
        ]
        acc = _HistoryAcc(messages)
        spec = {
            "range_type": "time",
            "start": str(int(start.timestamp())),
            "end": str(int(start.timestamp()) + 300),
            "reverse": False,
        }

        chunks = list(
            batch_forward._iter_batch_chunks(
                acc,
                None,
                -1001,
                spec,
                {},
            )
        )
        ids = [message_id for chunk in chunks for message_id in chunk[0]]

        self.assertEqual(ids, list(range(1, 206)))
        self.assertEqual(acc.calls[0]["offset"], -100)
        self.assertTrue(acc.calls[0]["reverse"])
        self.assertEqual(acc.calls[0]["offset_id"], 0)
        self.assertEqual(acc.calls[1]["offset_id"], 101)
        self.assertGreaterEqual(len(acc.calls), 3)

    def test_time_range_reverse_pagination_advances_without_replaying_pages(self):
        start = datetime(2026, 11, 9, tzinfo=timezone.utc)
        messages = [
            SimpleNamespace(
                id=index,
                date=datetime.fromtimestamp(start.timestamp() + index, timezone.utc),
                text=f"message {index}",
                caption=None,
                media_group_id=None,
            )
            for index in range(1, 206)
        ]
        acc = _HistoryAcc(messages)
        spec = {
            "range_type": "time",
            "start": str(int(start.timestamp())),
            "end": str(int(start.timestamp()) + 300),
            "reverse": True,
        }

        chunks = list(
            batch_forward._iter_batch_chunks(
                acc,
                None,
                -1001,
                spec,
                {},
            )
        )
        ids = [message_id for chunk in chunks for message_id in chunk[0]]

        self.assertEqual(ids, list(range(205, 0, -1)))
        self.assertFalse(acc.calls[0]["reverse"])
        self.assertEqual(acc.calls[0]["offset_id"], 0)
        self.assertEqual(acc.calls[1]["offset_id"], 106)
        self.assertGreaterEqual(len(acc.calls), 3)

    def test_scan_thread_finishes_before_queue_is_consumed(self):
        start = datetime(2026, 11, 9, tzinfo=timezone.utc)
        messages = [
            SimpleNamespace(
                id=index,
                date=datetime.fromtimestamp(start.timestamp() + index, timezone.utc),
                text=f"message {index}",
                caption=None,
                media_group_id=None,
            )
            for index in range(1, 251)
        ]
        acc = _HistoryAcc(messages)
        progress = []
        completed = []
        spec = {
            "range_type": "time",
            "start": str(int(start.timestamp())),
            "end": str(int(start.timestamp()) + 400),
            "reverse": False,
        }

        scan_queue, thread = batch_forward._start_batch_scan(
            acc,
            None,
            -1001,
            spec,
            {},
            batch_forward.threading.Event(),
            progress_callback=lambda scanned, collected: progress.append(
                (scanned, collected)
            ),
            complete_callback=lambda: completed.append(True),
        )
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(progress[-1], (250, 250))
        self.assertEqual(completed, [True])
        self.assertEqual(scan_queue.qsize(), 4)

    def test_consumed_chunks_never_move_scan_progress_backwards(self):
        state = {
            "scanned": 600,
            "collected": 480,
        }

        batch_forward._advance_stream_state(state, 100, 80)

        self.assertEqual(state["scanned"], 600)
        self.assertEqual(state["collected"], 480)


if __name__ == "__main__":
    unittest.main()
