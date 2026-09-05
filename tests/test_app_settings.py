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


if __name__ == "__main__":
    unittest.main()
