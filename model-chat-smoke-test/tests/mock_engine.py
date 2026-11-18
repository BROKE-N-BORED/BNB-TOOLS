#!/usr/bin/env python3
"""mock_engine - TEST FIXTURE ONLY for model-chat-smoke-test.

A fake model engine that replies, hangs, errors, or stays silent on
demand, so the test suite can prove the runner's timeout, empty
reply, and crash handling without a real model. It is NOT part of
the shipped tool: the real tool runs the user's own engine command
and never calls this file. Nothing outside tests/ imports it.

Modes (--mode):

    reply   print a canned reply naming the model and prompt, exit 0.
    hang    sleep for an hour (the runner must kill it on timeout).
    error   print a message to stderr, exit 1.
    empty   print only a blank line, exit 0 (a whitespace-only reply).
    auto    pick the behavior from the prompt or model name: a prompt
            or model name containing HANG hangs, ERROR errors, EMPTY
            stays silent, anything else replies. Lets one run produce
            every verdict.

--delay SECONDS sleeps that long before replying (reply and auto
modes only), for slow-but-working engine tests.
"""

import argparse
import sys
import time


def pick_behavior(mode, model, prompt):
    """What auto mode does for this model and prompt."""
    if mode != "auto":
        return mode
    for text in (prompt, model):
        upper = text.upper()
        if "HANG" in upper:
            return "hang"
        if "ERROR" in upper:
            return "error"
        if "EMPTY" in upper:
            return "empty"
    return "reply"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mock_engine.py")
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--mode",
                        choices=("reply", "hang", "error", "empty",
                                 "auto"),
                        default="reply")
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args(argv)
    behavior = pick_behavior(args.mode, args.model, args.prompt)
    if behavior == "hang":
        time.sleep(3600)
        return 0
    if behavior == "error":
        print("mock engine failed on purpose", file=sys.stderr)
        return 1
    if behavior == "empty":
        print()
        return 0
    if args.delay > 0:
        time.sleep(args.delay)
    print("Mock reply from %s to: %s" % (args.model, args.prompt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
