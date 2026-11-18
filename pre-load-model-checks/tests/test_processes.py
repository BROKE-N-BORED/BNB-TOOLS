"""Process check tests: fake /proc reads, ranking, formatting.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from preloadchecks import processes  # noqa: E402
import helpers  # noqa: E402


def make_proc(tmp, entries):
    """Build a fake /proc from (pid, name, ppid, rss_kb, uid)."""
    root = os.path.join(tmp, "proc")
    os.makedirs(root, exist_ok=True)
    for pid, name, ppid, rss_kb, uid in entries:
        helpers.write_fake_proc(root, pid, name, ppid=ppid,
                                rss_kb=rss_kb, uid=uid)
    return root


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_proc(self.tmp.name, [
            (1, "systemd", 0, 10240, 0),
            (100, "firefox", 1, 2048000, 1000),
            (200, "my (weird) proc", 1, 512000, 1000),
            (300, "[kworker/0:1]", 2, 0, 0),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_collects_all_visible(self):
        found = processes.collect(proc_root=self.root,
                                  sample_interval=0)
        by_pid = {info["pid"]: info for info in found}
        self.assertEqual(set(by_pid), {1, 100, 200, 300})

    def test_fields(self):
        found = processes.collect(proc_root=self.root,
                                  sample_interval=0)
        firefox = [i for i in found if i["pid"] == 100][0]
        self.assertEqual(firefox["name"], "firefox")
        self.assertEqual(firefox["ppid"], 1)
        self.assertEqual(firefox["uid"], 1000)
        self.assertAlmostEqual(firefox["rss_mb"], 2000.0)

    def test_name_with_parens_and_spaces(self):
        found = processes.collect(proc_root=self.root,
                                  sample_interval=0)
        weird = [i for i in found if i["pid"] == 200][0]
        self.assertEqual(weird["name"], "my (weird) proc")

    def test_cpu_zero_without_sampling(self):
        found = processes.collect(proc_root=self.root,
                                  sample_interval=0)
        for info in found:
            self.assertEqual(info["cpu_percent"], 0.0)

    def test_cpu_measured_between_samples(self):
        # Bump firefox's CPU time when collect() sleeps.
        real_sleep = processes.time.sleep

        def bump(seconds):
            helpers.write_fake_proc(
                self.root, 100, "firefox", ppid=1,
                rss_kb=2048000, uid=1000, utime=100, stime=0)
            real_sleep(0)

        with mock.patch.object(processes.time, "sleep",
                               side_effect=bump):
            with mock.patch.object(processes.os, "cpu_count",
                                   return_value=1):
                found = processes.collect(
                    proc_root=self.root, sample_interval=1.0)
        firefox = [i for i in found if i["pid"] == 100][0]
        # 100 ticks at 100 Hz over 1 second on 1 CPU = 100%.
        self.assertAlmostEqual(firefox["cpu_percent"], 100.0,
                               places=0)

    def test_vanishing_process_skipped(self):
        os.remove(os.path.join(self.root, "200", "status"))
        found = processes.collect(proc_root=self.root,
                                  sample_interval=0)
        self.assertNotIn(200, [i["pid"] for i in found])

    def test_missing_proc_root_is_empty(self):
        found = processes.collect(
            proc_root=os.path.join(self.tmp.name, "nope"),
            sample_interval=0)
        self.assertEqual(found, [])


class KernelThreadTests(unittest.TestCase):
    def test_ppid_2_is_kernel_thread(self):
        self.assertTrue(processes.is_kernel_thread(
            {"ppid": 2, "name": "kworker"}))

    def test_ppid_0_is_kernel_thread(self):
        self.assertTrue(processes.is_kernel_thread(
            {"ppid": 0, "name": "swapper"}))

    def test_bracketed_name_is_kernel_thread(self):
        self.assertTrue(processes.is_kernel_thread(
            {"ppid": 1, "name": "[kthreadd]"}))

    def test_normal_process_is_not(self):
        self.assertFalse(processes.is_kernel_thread(
            {"ppid": 1, "name": "firefox"}))


class TopConflictsTests(unittest.TestCase):
    PROCESSES = [
        {"pid": 1, "name": "systemd", "ppid": 0, "uid": 0,
         "rss_mb": 10000.0, "cpu_percent": 0.0},
        {"pid": 100, "name": "firefox", "ppid": 1, "uid": 1000,
         "rss_mb": 2000.0, "cpu_percent": 5.0},
        {"pid": 200, "name": "compiler", "ppid": 1, "uid": 1000,
         "rss_mb": 100.0, "cpu_percent": 90.0},
        {"pid": 300, "name": "[kworker]", "ppid": 2, "uid": 0,
         "rss_mb": 0.0, "cpu_percent": 50.0},
        {"pid": 400, "name": "other-user-app", "ppid": 1,
         "uid": 2000, "rss_mb": 3000.0, "cpu_percent": 0.0},
        {"pid": 500, "name": "tiny", "ppid": 1, "uid": 1000,
         "rss_mb": 10.0, "cpu_percent": 0.0},
    ]

    def test_pid_1_never_listed(self):
        top = processes.top_conflicts(self.PROCESSES)
        self.assertNotIn(1, [i["pid"] for i in top])

    def test_kernel_threads_never_listed(self):
        top = processes.top_conflicts(self.PROCESSES)
        self.assertNotIn(300, [i["pid"] for i in top])

    def test_excluded_pids_never_listed(self):
        top = processes.top_conflicts(self.PROCESSES,
                                      exclude_pids={100, 200})
        self.assertNotIn(100, [i["pid"] for i in top])
        self.assertNotIn(200, [i["pid"] for i in top])

    def test_limit_honored(self):
        top = processes.top_conflicts(self.PROCESSES, limit=2)
        self.assertEqual(len(top), 2)

    def test_default_limit_is_six(self):
        self.assertEqual(processes.DEFAULT_LIMIT, 6)

    def test_cpu_weight_beats_quiet_ram(self):
        # compiler: 100 MB + 90% CPU = 9100 score.
        # firefox: 2000 MB + 5% CPU = 2500 score.
        top = processes.top_conflicts(self.PROCESSES)
        self.assertEqual(top[0]["pid"], 200)
        self.assertEqual(top[1]["pid"], 400)  # 3000 MB, quiet

    def test_killable_only_filters_other_users(self):
        top = processes.top_conflicts(self.PROCESSES, uid=1000,
                                      killable_only=True)
        self.assertNotIn(400, [i["pid"] for i in top])
        self.assertIn(100, [i["pid"] for i in top])

    def test_score_formula(self):
        info = {"rss_mb": 500.0, "cpu_percent": 10.0}
        self.assertEqual(processes.conflict_score(info), 1500.0)


class FormatTests(unittest.TestCase):
    PROCESSES = [
        {"pid": 100, "name": "firefox", "ppid": 1, "uid": 1000,
         "rss_mb": 2000.0, "cpu_percent": 5.0},
        {"pid": 400, "name": "other-app", "ppid": 1, "uid": 2000,
         "rss_mb": 3000.0, "cpu_percent": 0.0},
    ]

    def test_plain_lists_processes(self):
        text = processes.format_plain(self.PROCESSES, uid=1000)
        self.assertIn("firefox (PID 100)", text)
        self.assertIn("2000 MB RAM", text)
        self.assertIn("5% CPU", text)

    def test_plain_marks_other_user(self):
        text = processes.format_plain(self.PROCESSES, uid=1000)
        self.assertIn("another user", text)

    def test_plain_empty(self):
        text = processes.format_plain([])
        self.assertIn("Nothing heavy is running", text)

    def test_json_shape(self):
        data = json.loads(processes.format_json(self.PROCESSES))
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["pid"], 100)
        self.assertEqual(data[0]["name"], "firefox")
        self.assertEqual(data[0]["rss_mb"], 2000.0)
        self.assertEqual(data[0]["cpu_percent"], 5.0)


if __name__ == "__main__":
    unittest.main()
