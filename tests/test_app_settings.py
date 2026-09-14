import os
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import app_settings


class AppSettingsTests(unittest.TestCase):
    def test_timezone_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = os.path.join(temp_dir, "app_settings.json")
            with mock.patch.object(
                app_settings,
                "SETTINGS_FILE",
                settings_file,
            ):
                app_settings.save_app_timezone("Asia/Tokyo")
                saved = app_settings.get_app_settings()
                timezone = app_settings.get_app_timezone()

            self.assertEqual(saved["timezone"], "Asia/Tokyo")
            self.assertEqual(str(timezone), "Asia/Tokyo")

    def test_invalid_timezone_is_rejected(self):
        with self.assertRaises(ValueError):
            app_settings.save_app_timezone("Not/A_Timezone")

    def test_missing_timezone_falls_back_to_shanghai(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = os.path.join(temp_dir, "app_settings.json")
            with mock.patch.object(
                app_settings,
                "SETTINGS_FILE",
                settings_file,
            ):
                settings = app_settings.get_app_settings()
                timezone = app_settings.get_app_timezone()

            self.assertEqual(settings["timezone"], "Asia/Shanghai")
            self.assertIsInstance(timezone, ZoneInfo)
            self.assertEqual(str(timezone), "Asia/Shanghai")

    def test_batch_notifications_default_to_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = os.path.join(temp_dir, "app_settings.json")
            with mock.patch.object(
                app_settings,
                "SETTINGS_FILE",
                settings_file,
            ):
                settings = app_settings.get_app_settings()

                self.assertTrue(
                    settings["batch_completion_notifications_enabled"]
                )
                self.assertTrue(
                    app_settings.batch_completion_notifications_enabled()
                )

    def test_batch_notifications_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = os.path.join(temp_dir, "app_settings.json")
            with mock.patch.object(
                app_settings,
                "SETTINGS_FILE",
                settings_file,
            ):
                app_settings.save_app_preferences(
                    batch_completion_notifications_enabled=False
                )
                settings = app_settings.get_app_settings()

                self.assertFalse(
                    settings["batch_completion_notifications_enabled"]
                )
                self.assertFalse(
                    app_settings.batch_completion_notifications_enabled()
                )

    def test_preferences_update_does_not_clear_timezone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = os.path.join(temp_dir, "app_settings.json")
            with mock.patch.object(
                app_settings,
                "SETTINGS_FILE",
                settings_file,
            ):
                app_settings.save_app_timezone("Asia/Tokyo")
                app_settings.save_app_preferences(
                    batch_completion_notifications_enabled=False
                )
                settings = app_settings.get_app_settings()

            self.assertEqual(settings["timezone"], "Asia/Tokyo")
            self.assertFalse(
                settings["batch_completion_notifications_enabled"]
            )


if __name__ == "__main__":
    unittest.main()
