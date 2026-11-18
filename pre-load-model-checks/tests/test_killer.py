"""Kill tests: every guard, dry-run, and real kills of
throwaway processes the suite spawns itself and nothing else.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from preloadchecks import killer  # noqa: E402
import helpers  # noqa: E402

MY_UID = os.getuid()
OTHER_UID = 1000 if MY_UID != 1000 else 2000


def make_proc(tmp, entries):
    """Build a fake /proc from (pid, name, ppid, rss_kb, uid)."""
    root = os.path.join(tmp, "proc")
    os.makedirs(root, exist_ok=True)
    for pid, name, ppid, rss_kb, uid in entries:
        helpers.write_fake_proc(root, pid, name, ppid=ppid,
                                rss_kb=rss_kb, uid=uid)
    return root


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_proc(self.tmp.name, [
            (100, "firefox", 1, 2048000, MY_UID),
            (200, "systemd", 1, 10240, 0),
            (300, "[kworker/0:1]", 2, 0, 0),
            (400, "other-app", 1, 1024000, OTHER_UID),
            (500, "cinnamon", 1, 512000, MY_UID),
            (600, "Xorg", 1, 256000, 0),
            (700, "sshd", 1, 10240, 0),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_pid_1_refused(self):
        reason = killer.refusal_reason(1, proc_root=self.root)
        self.assertIsNotNone(reason)
        self.assertIn("PID 1", reason)

    def test_own_process_refused(self):
        # The real process table: our own PID is in our tree.
        reason = killer.refusal_reason(os.getpid())
        self.assertIsNotNone(reason)
        self.assertIn("this tool", reason)

    def test_parent_process_refused(self):
        reason = killer.refusal_reason(os.getppid())
        self.assertIsNotNone(reason)

    def test_kernel_thread_refused(self):
        reason = killer.refusal_reason(300, proc_root=self.root)
        self.assertIsNotNone(reason)
        self.assertIn("kernel thread", reason)

    def test_protected_names_refused(self):
        for pid, name in ((200, "systemd"), (500, "cinnamon"),
                          (600, "Xorg"), (700, "sshd")):
            with self.subTest(name=name):
                reason = killer.refusal_reason(
                    pid, proc_root=self.root)
                self.assertIsNotNone(reason)
                self.assertIn("system process", reason)

    def test_other_user_refused(self):
        reason = killer.refusal_reason(400, proc_root=self.root)
        self.assertIsNotNone(reason)
        self.assertIn("another user", reason)

    def test_killable_process_allowed(self):
        reason = killer.refusal_reason(100, proc_root=self.root)
        self.assertIsNone(reason)

    def test_gone_process_not_a_refusal(self):
        reason = killer.refusal_reason(9999, proc_root=self.root)
        self.assertIsNone(reason)


class OwnTreeTests(unittest.TestCase):
    def test_own_tree_holds_self_and_parent(self):
        tree = killer.own_tree_pids()
        self.assertIn(os.getpid(), tree)
        self.assertIn(os.getppid(), tree)

    def test_pid_1_is_not_in_the_tree(self):
        # The ancestor walk stops before PID 1 (PID 1 has its
        # own refusal rule instead).
        tree = killer.own_tree_pids()
        self.assertNotIn(1, tree)


class KillPidsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_proc(self.tmp.name, [
            (100, "firefox", 1, 2048000, MY_UID),
        ])
        self.victims = []

    def tearDown(self):
        for pid in self.victims:
            helpers.stop_pid(pid)
        self.tmp.cleanup()

    def test_no_confirm_refuses_everything(self):
        results = killer.kill_pids([100], confirm=False,
                                   dry_run=False,
                                   proc_root=self.root)
        self.assertEqual(results[0]["outcome"], "refused")
        self.assertIn("confirmation", results[0]["reason"])

    def test_dry_run_touches_nothing(self):
        pid = helpers.spawn_detached_victim(seconds=30)
        self.victims.append(pid)
        results = killer.kill_pids([pid], confirm=False,
                                   dry_run=True, term_wait=0.2)
        self.assertEqual(results[0]["outcome"], "would stop")
        # Still running: dry-run stopped nothing.
        self.assertTrue(helpers._pid_exists(pid))

    def test_dry_run_still_refuses_pid_1(self):
        results = killer.kill_pids([1], confirm=False,
                                   dry_run=True,
                                   proc_root=self.root)
        self.assertEqual(results[0]["outcome"], "refused")

    def test_already_stopped_pid_reports_honestly(self):
        results = killer.kill_pids([999999], confirm=True,
                                   proc_root=self.root)
        self.assertEqual(results[0]["outcome"], "already stopped")

    def test_real_kill_stops_a_throwaway_process(self):
        pid = helpers.spawn_detached_victim(seconds=60)
        self.victims.append(pid)
        results = killer.kill_pids([pid], confirm=True,
                                   term_wait=2.0)
        self.assertEqual(results[0]["outcome"], "stopped")
        helpers.assert_stopped(self, pid)
        self.victims.remove(pid)

    def test_term_ignoring_process_gets_sigkill(self):
        pid = helpers.spawn_detached_victim(seconds=60,
                                            ignore_term=True)
        self.victims.append(pid)
        results = killer.kill_pids([pid], confirm=True,
                                   term_wait=0.5)
        self.assertEqual(results[0]["outcome"], "stopped")
        helpers.assert_stopped(self, pid)
        self.victims.remove(pid)

    def test_refusals_do_not_stop_the_rest(self):
        pid = helpers.spawn_detached_victim(seconds=60)
        self.victims.append(pid)
        results = killer.kill_pids([1, pid], confirm=True,
                                   term_wait=2.0)
        by_pid = {r["pid"]: r for r in results}
        self.assertEqual(by_pid[1]["outcome"], "refused")
        self.assertEqual(by_pid[pid]["outcome"], "stopped")
        helpers.assert_stopped(self, pid)
        self.victims.remove(pid)


class ReportTests(unittest.TestCase):
    def test_all_outcomes_in_plain_words(self):
        results = [
            {"pid": 100, "name": "firefox", "outcome": "stopped",
             "reason": ""},
            {"pid": 101, "name": "editor", "outcome": "would stop",
             "reason": ""},
            {"pid": 102, "name": "PID 102",
             "outcome": "already stopped", "reason": ""},
            {"pid": 1, "name": "systemd", "outcome": "refused",
             "reason": "PID 1 runs the whole system"},
            {"pid": 103, "name": "stuck", "outcome": "failed",
             "reason": "it would not stop"},
        ]
        text = killer.plain_report(results)
        self.assertIn("Stopped firefox (PID 100).", text)
        self.assertIn("Would stop editor (PID 101).", text)
        self.assertIn("had already stopped", text)
        self.assertIn("Did not stop systemd (PID 1)", text)
        self.assertIn("Could not stop stuck (PID 103)", text)


if __name__ == "__main__":
    unittest.main()
