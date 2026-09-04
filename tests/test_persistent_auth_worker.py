import unittest
from unittest.mock import patch

import web_auth_worker as worker


class SentCode:
    phone_code_hash = "test-code-hash"


class FakeClient:
    def __init__(self):
        self.connected = False
        self.disconnected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.sign_in_calls = []
        self.password_checks = []

    def connect(self):
        self.connected = True
        self.connect_calls += 1

    def disconnect(self):
        self.connected = False
        self.disconnected = True
        self.disconnect_calls += 1

    def send_code(self, phone_number):
        self.send_code_phone = phone_number
        return SentCode()

    def sign_in(self, phone_number, phone_code_hash, code):
        self.sign_in_calls.append((phone_number, phone_code_hash, code))

    def check_password(self, password):
        self.password_checks.append(password)

    def export_session_string(self):
        return "test-session-string"


class PersistentAuthWorkerTests(unittest.TestCase):
    def setUp(self):
        self.job = {
            "session_name": "web_auth_test",
            "phone_number": "+8613800138000",
            "api_id": "123456",
            "api_hash": "abc",
            "token": "123:bot",
        }

    def run_start_with_reads(self, client, reads):
        updates = []

        def record_update(setup_id, **fields):
            updates.append((setup_id, dict(fields)))

        with patch.object(worker, "_load_required_job", return_value=dict(self.job)), patch.object(
            worker, "_read_job", side_effect=reads
        ), patch.object(worker, "_update_job", side_effect=record_update), patch.object(
            worker, "time"
        ) as time_patch:
            time_patch.time.return_value = 1000
            time_patch.sleep.return_value = None
            with patch.object(worker, "_new_client", return_value=client), patch.object(
                worker, "_remove_session_files"
            ) as remove_session:
                result = worker.run_start("a" * 32)

        return result, updates, remove_session

    def test_correct_code_uses_the_same_connected_client(self):
        client = FakeClient()
        reads = [
            {"status": "sent", "phone_code_hash": "test-code-hash"},
            {"status": "queued", "login_code": "12345"},
        ]

        result, updates, remove_session = self.run_start_with_reads(client, reads)

        self.assertEqual(result, 0)
        self.assertEqual(client.connect_calls, 1)
        self.assertEqual(client.sign_in_calls, [("+8613800138000", "test-code-hash", "12345")])
        self.assertEqual(client.disconnect_calls, 1)
        self.assertEqual(updates[-1][1].get("status"), "done")
        self.assertEqual(updates[-1][1].get("session_string"), "test-session-string")
        remove_session.assert_not_called()

    def test_invalid_code_fails_and_cleans_session_files(self):
        from pyrogram.errors import PhoneCodeExpired

        client = FakeClient()

        def expire_code(*_args):
            raise PhoneCodeExpired()

        client.sign_in = expire_code
        reads = [
            {"status": "sent", "phone_code_hash": "test-code-hash"},
            {"status": "queued", "login_code": "12345"},
            {"status": "error", "error": "验证码已过期"},
        ]

        result, updates, remove_session = self.run_start_with_reads(client, reads)

        self.assertEqual(result, 1)
        self.assertEqual(updates[-1][1].get("status"), "error")
        self.assertIn("过期", updates[-1][1].get("error", ""))
        remove_session.assert_called_once_with("web_auth_test")

    def test_two_factor_keeps_the_same_client_for_password(self):
        from pyrogram.errors import SessionPasswordNeeded

        client = FakeClient()

        def require_password(*_args):
            raise SessionPasswordNeeded()

        client.sign_in = require_password
        reads = [
            {"status": "sent", "phone_code_hash": "test-code-hash"},
            {"status": "queued", "login_code": "12345"},
            {"status": "ready", "two_factor_password": None},
            {"status": "queued", "two_factor_password": "secret"},
        ]

        result, updates, remove_session = self.run_start_with_reads(client, reads)

        self.assertEqual(result, 0)
        self.assertEqual(client.password_checks, ["secret"])
        self.assertEqual(updates[-1][1].get("status"), "done")
        remove_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
