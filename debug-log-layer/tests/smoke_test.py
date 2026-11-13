#!/usr/bin/env python3
"""Smoke test for debug_log.py. No network needed (the Ollama check
points at a closed port). Run: python3 tests/smoke_test.py"""

import glob
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import debug_log  # noqa: E402
from debug_log import (  # noqa: E402
    DebugLogger, check_ollama, collect_context, scrub_dict, scrub_text)

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print("%s %s%s" % ("PASS:" if cond else "FAIL:", name,
                       (" — " + detail) if detail and not cond else ""))


# Deliberate FAKE values, not real credentials: key-shaped fixtures that
# prove the scrubber redacts key-shaped values. The test cannot work
# without them — do not remove or reshape them.
FAKE_KEY = "sk-fake-key-1234567890abcdef"
FAKE_TOKEN = "ghp_faketoken1234567890abcd"


def main():
    # --- scrubbing ----------------------------------------------------
    check("scrub_text redacts an api_key assignment",
          FAKE_KEY not in scrub_text("api_key=" + FAKE_KEY)
          and "[REDACTED]" in scrub_text("api_key=" + FAKE_KEY))
    check("scrub_text redacts a Bearer header",
          "abc123secret" not in scrub_text(
              "Authorization: Bearer abc123secret"))
    check("scrub_text redacts a bare sk- key",
          FAKE_KEY not in scrub_text("key is " + FAKE_KEY))
    check("scrub_text redacts a password assignment",
          "hunter2" not in scrub_text("password: hunter2"))
    check("scrub_text leaves normal text alone",
          scrub_text("model qwen3.5:2b loaded in 4.2s")
          == "model qwen3.5:2b loaded in 4.2s")
    scrubbed = scrub_dict({
        "model": "qwen3.5:2b",
        "api_key": FAKE_KEY,
        "token": FAKE_TOKEN,
        "empty_key": "",
        "nested": {"password": "hunter2", "mode": "blind"},
    })
    check("scrub_dict redacts sensitive keys, keeps presence info",
          scrubbed["api_key"] == "[REDACTED] — present"
          and scrubbed["token"] == "[REDACTED] — present"
          and scrubbed["empty_key"] == "[absent]"
          and scrubbed["nested"]["password"] == "[REDACTED] — present",
          str(scrubbed))
    check("scrub_dict passes normal values through",
          scrubbed["model"] == "qwen3.5:2b"
          and scrubbed["nested"]["mode"] == "blind")

    # --- context ------------------------------------------------------
    ctx = collect_context("testapp", "1.0", path=tempfile.gettempdir())
    check("context has app/os/python/ram/disk",
          ctx["app"] == "testapp" and ctx["version"] == "1.0"
          and ctx["os"] and ctx["python"]
          and "ram" in ctx and "disk" in ctx,
          str(sorted(ctx)))
    check("ollama check reports not-reachable on a closed port",
          "not reachable" in check_ollama(
              base_url="http://127.0.0.1:9", timeout=1))

    # --- logger + report ----------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = os.path.join(tmp, "logs")
        log = DebugLogger("testapp", "1.0", log_dir=log_dir,
                          max_bytes=1024, backup_count=2, history=5)
        log.set_setting("model", "qwen3.5:2b")
        log.set_setting("api_key", FAKE_KEY)
        log.register_service("ollama",
                             lambda: check_ollama(
                                 base_url="http://127.0.0.1:9",
                                 timeout=1))
        log.register_dependency("nonexistent-package-xyz")
        log.info("startup ok")
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("relay failed")
        for i in range(8):
            log.action("step %d" % i)
        report_path = log.generate_report()

        check("report filename follows the standard",
              re.match(r"debug-report-testapp-\d{8}-\d{6}\.txt$",
                       os.path.basename(report_path)) is not None,
              report_path)
        with open(report_path, encoding="utf-8") as fh:
            report = fh.read()
        for section in ("== Context ==", "== Settings ==",
                        "== Services ==", "== Recent actions",
                        "== Errors ==", "== Log tail"):
            check("report has section %s" % section,
                  section in report)
        check("report contains the traceback",
              "ValueError: boom" in report
              and "Traceback" in report)
        # The Recent actions section (not the log tail, which holds
        # all 200 lines) must keep only the last 5 records.
        actions_section = report.split("== Recent actions")[1].split(
            "== Errors ==")[0]
        check("report keeps only the last 5 actions",
              "step 7" in actions_section
              and "step 3" in actions_section
              and "step 2" not in actions_section)
        check("report has no secret values anywhere",
              FAKE_KEY not in report and FAKE_TOKEN not in report
              and "[REDACTED]" in report)
        check("report shows the ollama service as not reachable",
              "ollama: not reachable" in report)
        check("report marks the missing dependency",
              "nonexistent-package-xyz: not installed" in report)
        with open(log.log_path, encoding="utf-8") as fh:
            log_text = fh.read()
        check("log lines carry timestamps",
              re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[INFO\]",
                        log_text) is not None)

        # rotation: flood the log, total size must stay capped
        for i in range(200):
            log.info("filler line %03d %s" % (i, "x" * 40))
        import logging
        for handler in log.logger.handlers:
            handler.flush()
        sizes = [os.path.getsize(p)
                 for p in glob.glob(log.log_path + "*")]
        check("rotation caps total log size (3 files x 1 KB)",
              len(sizes) > 1 and sum(sizes) <= 3 * 1024 + 512,
              str(sizes))

        # crash handler: a fake unhandled exception writes a report
        before = set(glob.glob(os.path.join(log_dir,
                                            "debug-report-*.txt")))
        log.install_crash_handler()
        try:
            sys.excepthook(ValueError, ValueError("crash-test"), None)
        finally:
            log.uninstall_crash_handler()
        after = set(glob.glob(os.path.join(log_dir,
                                           "debug-report-*.txt")))
        check("crash handler writes a report on unhandled exception",
              len(after) > len(before))

        # CLI: one command, report in the project folder
        out_path = os.path.join(tmp, "my-report.txt")
        proc = subprocess.run(
            [sys.executable,
             os.path.join(os.path.dirname(__file__), "..",
                          "debug_log.py"),
             "report", "--app", "cliapp", "--version", "2.0",
             "--log-dir", log_dir, "--out", out_path],
            capture_output=True, text=True)
        check("CLI report command exits 0 and writes the file",
              proc.returncode == 0 and os.path.exists(out_path),
              proc.stderr[-300:])
        with open(out_path, encoding="utf-8") as fh:
            cli_report = fh.read()
        check("CLI report names the app and version",
              "DEBUG REPORT — cliapp 2.0" in cli_report)

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
