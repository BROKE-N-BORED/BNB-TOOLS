#!/usr/bin/env python3
"""Scripted dual-model AI-to-AI relay over Ollama.

Runs the DUO relay loop from the command line: a seed message goes to
the starting model, and each reply is handed to the other model, one
generation at a time, until the turn cap, a stop phrase, agreement, or
Ctrl+C. Blind mode (default) delivers the bare reply text as a plain
user message; aware mode frames it so the models know they are talking
to another AI.

The relay semantics mirror DUO's RelaySession exactly
(~/workspace/dual-chat-v03-build/dual_chat.py):

- a "turn" is one generation; the seed turn is turn 1, so a cap of N
  means exactly N generations;
- stop phrases match case-insensitively as substrings, and the stop
  reason names the phrase found;
- agreement uses the fixed list ("i agree", "agreed", "sounds good",
  "that works") — plain string matching, no LLM judge;
- a phrase or agreement stop is reported before the cap when they land
  on the same turn.

Usage:

    python3 relay.py --model-a qwen3.5:2b --model-b lfm3:1.7b \\
        --seed "Should we build the treehouse out of pine or oak?" \\
        --start A --cap 6 --mode blind --out relay.json

    python3 relay.py --model-a A --model-b B --seed "Hi" \\
        --ollama-url http://127.0.0.1:11435 --stop-phrase goodbye \\
        --stop-on-agreement

Each model keeps its own history (like DUO's two panes). The
transcript JSON records every turn, the exact framed message each
model received, and the stop reason. Nothing is sent anywhere except
the configured Ollama server.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_URL_ENV = "DUAL_CHAT_OLLAMA_URL"

AGREEMENT_PHRASES = ("i agree", "agreed", "sounds good", "that works")
AWARE_TEMPLATE = ("You are talking with another AI assistant (Model %s). "
                  "It said: %s")
RELAY_CAP_MIN = 1
RELAY_CAP_MAX = 50
RELAY_CAP_DEFAULT = 10


class RelayError(Exception):
    """A plain-language relay failure (Ollama down, model missing)."""


def clamp_cap(value):
    return max(RELAY_CAP_MIN, min(RELAY_CAP_MAX, int(value)))


def frame(text, from_side, mode):
    """The message the other model receives for a relayed reply.

    Blind: the bare reply text, no framing at all. Aware: framed so
    the models know they are talking to another AI.
    """
    if mode == "aware":
        return AWARE_TEMPLATE % (from_side, text)
    return text


def find_stop_phrase(text, phrases):
    lowered = text.lower()
    for phrase in phrases:
        if phrase.lower() in lowered:
            return phrase
    return None


def find_agreement(text, enabled):
    if not enabled:
        return None
    lowered = text.lower()
    for phrase in AGREEMENT_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def check_stop(reply_text, turns_done, turn_cap, stop_phrases,
               stop_on_agreement):
    """Stop reason for this reply, or None to keep relaying.

    Call after incrementing turns_done. A phrase or agreement stop is
    reported before the cap when they land on the same turn.
    """
    phrase = find_stop_phrase(reply_text, stop_phrases)
    if phrase is not None:
        return "phrase %r found" % phrase
    agreement = find_agreement(reply_text, stop_on_agreement)
    if agreement is not None:
        return "agreement reached (%r)" % agreement
    if turns_done >= turn_cap:
        return "turn cap reached"
    return None


class OllamaClient:
    """Minimal Ollama client. Stdlib only, non-streaming /api/chat."""

    def __init__(self, base_url=None):
        self.base_url = (base_url or os.environ.get(OLLAMA_URL_ENV)
                         or DEFAULT_OLLAMA_URL).rstrip("/")

    def chat(self, model, messages, timeout=300):
        body = json.dumps({"model": model, "messages": messages,
                           "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/api/chat", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")
                                    ).get("error", "")
            except Exception:
                detail = ""
            raise RelayError("model %s failed: %s"
                             % (model, detail or "HTTP %d" % exc.code))
        except Exception:
            raise RelayError("Ollama isn't running at %s. "
                             "Start Ollama and try again." % self.base_url)
        return payload.get("message", {}).get("content", "")


def other(side):
    return "B" if side == "A" else "A"


def run_relay(client, models, seed, start_side="A", turn_cap=10,
              mode="blind", stop_phrases=(), stop_on_agreement=False,
              on_turn=None):
    """Run one relay. Returns (turns, stop_reason).

    turns is a list of dicts: turn number, side, model, the exact
    message that side received (framed per mode), and its reply.
    Each side keeps its own history, like DUO's two panes.
    """
    turn_cap = clamp_cap(turn_cap)
    histories = {"A": [], "B": []}
    turns = []
    current = start_side
    incoming = seed  # the seed is delivered bare in both modes
    turns_done = 0
    stop_reason = None
    while True:
        model = models[current]
        histories[current].append({"role": "user", "content": incoming})
        reply = client.chat(model, histories[current])
        histories[current].append({"role": "assistant", "content": reply})
        turns_done += 1
        record = {"turn": turns_done, "side": current, "model": model,
                  "received": incoming, "reply": reply}
        turns.append(record)
        if on_turn is not None:
            on_turn(record)
        stop_reason = check_stop(reply, turns_done, turn_cap,
                                 stop_phrases, stop_on_agreement)
        if stop_reason is not None:
            break
        incoming = frame(reply, current, mode)
        current = other(current)
    return turns, stop_reason


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a dual-model AI-to-AI relay over Ollama.")
    parser.add_argument("--model-a", required=True,
                        help="Ollama model for side A")
    parser.add_argument("--model-b", required=True,
                        help="Ollama model for side B")
    parser.add_argument("--seed", required=True,
                        help="seed message starting the relay")
    parser.add_argument("--start", choices=["A", "B"], default="A",
                        help="which side speaks first (default A)")
    parser.add_argument("--cap", type=int, default=RELAY_CAP_DEFAULT,
                        help="turn cap, %d-%d (default %d)"
                        % (RELAY_CAP_MIN, RELAY_CAP_MAX,
                           RELAY_CAP_DEFAULT))
    parser.add_argument("--mode", choices=["blind", "aware"],
                        default="blind",
                        help="blind: bare text; aware: framed (default "
                        "blind)")
    parser.add_argument("--stop-phrase", action="append", default=[],
                        help="stop phrase, repeatable")
    parser.add_argument("--stop-on-agreement", action="store_true",
                        help="stop when a reply contains an agreement "
                        "phrase")
    parser.add_argument("--ollama-url", default=None,
                        help="Ollama base URL (default %s or $%s)"
                        % (DEFAULT_OLLAMA_URL, OLLAMA_URL_ENV))
    parser.add_argument("--out", default=None,
                        help="write the transcript JSON to this file")
    args = parser.parse_args(argv)

    client = OllamaClient(args.ollama_url)
    models = {"A": args.model_a, "B": args.model_b}

    def show(record):
        print("\n--- turn %d, Model %s (%s) ---"
              % (record["turn"], record["side"], record["model"]))
        print(record["reply"])

    print("Relay: %s (A) <-> %s (B), start %s, cap %d, mode %s"
          % (args.model_a, args.model_b, args.start,
             clamp_cap(args.cap), args.mode))
    try:
        turns, stop_reason = run_relay(
            client, models, args.seed, start_side=args.start,
            turn_cap=args.cap, mode=args.mode,
            stop_phrases=args.stop_phrase,
            stop_on_agreement=args.stop_on_agreement, on_turn=show)
    except RelayError as exc:
        print("Relay failed: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nRelay stopped by you.")
        return 130
    print("\nRelay stopped: %s (%d turns)" % (stop_reason, len(turns)))
    if args.out:
        transcript = {"model_a": args.model_a, "model_b": args.model_b,
                      "seed": args.seed, "start": args.start,
                      "cap": clamp_cap(args.cap), "mode": args.mode,
                      "stop_reason": stop_reason, "turns": turns}
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(transcript, fh, indent=2)
            fh.write("\n")
        print("Transcript written to %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
