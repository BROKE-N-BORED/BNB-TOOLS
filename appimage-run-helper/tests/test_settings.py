"""Settings tests: defaults, round trip, corrupt tolerance, and
the data-dir agreement with logsetup."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from appimagehelper import logsetup, settings  # noqa: E402


class SettingsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="appimage-settings-")
        self.path = os.path.join(self.tmp, "settings.json")

    def test_defaults_when_missing(self):
        store = settings.Settings(self.path)
        self.assertIsNone(store.last_folder)

    def test_round_trip(self):
        store = settings.Settings(self.path)
        store.last_folder = "/home/user/Downloads"
        store.save()
        again = settings.Settings(self.path)
        self.assertEqual(again.last_folder, "/home/user/Downloads")

    def test_atomic_save_leaves_valid_json(self):
        store = settings.Settings(self.path)
        store.last_folder = "/tmp"
        store.save()
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["last_folder"], "/tmp")
        leftovers = [n for n in os.listdir(self.tmp)
                     if n.startswith(".appimage-settings-")]
        self.assertEqual(leftovers, [])

    def test_corrupt_file_tolerated(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        store = settings.Settings(self.path)
        self.assertIsNone(store.last_folder)

    def test_non_dict_tolerated(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump([1, 2, 3], fh)
        store = settings.Settings(self.path)
        self.assertIsNone(store.last_folder)


class DataDirAgreementTests(unittest.TestCase):

    def test_settings_and_logsetup_agree(self):
        self.assertEqual(settings.data_dir(), logsetup.data_dir())
        self.assertEqual(settings.log_dir(), logsetup.log_dir())
        self.assertTrue(settings.data_dir().endswith(
            "appimage-run-helper"))

    def test_xdg_honored(self):
        old = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = "/tmp/xdg-probe"
        try:
            self.assertEqual(
                settings.data_dir(),
                "/tmp/xdg-probe/appimage-run-helper")
            self.assertEqual(
                logsetup.log_dir(),
                "/tmp/xdg-probe/appimage-run-helper/logs")
        finally:
            if old is None:
                os.environ.pop("XDG_DATA_HOME", None)
            else:
                os.environ["XDG_DATA_HOME"] = old


if __name__ == "__main__":
    unittest.main()
