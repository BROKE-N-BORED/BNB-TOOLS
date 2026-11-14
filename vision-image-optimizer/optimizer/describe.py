"""Describe step for Vision Image Optimizer: ask the local vision
model what is in a picture.

One small piece of the chain: it describes the file exactly as
given and never shrinks anything. To describe a shrunken copy,
shrink first and then describe the copy:

    python -m optimizer.shrink photo.png --width 512
    python -m optimizer.describe photo-512w.jpg
"""

import argparse
import json
import os
import sys

from . import tokens
from .cache import ImageCache
from .ollama import (DEFAULT_FAST_MODEL, DEFAULT_SMART_MODEL,
                     DEFAULT_URL, OllamaClient, OllamaError)
from .settings import Settings, cache_dir


class _Parser(argparse.ArgumentParser):
    """Bad arguments exit 1 with a plain message, not 2."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, "%s: error: %s\n" % (self.prog, message))


def add_arguments(parser):
    """The describe flags, shared by this module and the combined CLI."""
    parser.add_argument("file", help="the picture to describe")
    parser.add_argument("--prompt", default=None,
                        help="what to ask the model "
                             "(default: the saved prompt)")
    parser.add_argument("--fast-model", default=None,
                        help="the small model that looks first "
                             "(default: %s)" % DEFAULT_FAST_MODEL)
    parser.add_argument("--smart-model", default=None,
                        help="the careful model that looks second "
                             "(default: %s)" % DEFAULT_SMART_MODEL)
    parser.add_argument("--ollama-url", default=None,
                        help="Ollama address "
                             "(default: %s)" % DEFAULT_URL)
    parser.add_argument("--no-cache", action="store_true",
                        help="skip the cache for this run")
    parser.add_argument("--json", action="store_true",
                        help="print one JSON object instead of "
                             "human-readable lines")


def build_parser():
    parser = _Parser(
        prog="vision-describe",
        description="Describe a picture with the local vision model, "
                    "exactly as given. Shrink it first with "
                    "vision-shrink when the picture is large.")
    add_arguments(parser)
    return parser


def _get_cache(settings, no_cache=False):
    enabled = bool(settings.get("cache_enabled")) and not no_cache
    return ImageCache(cache_dir(), enabled=enabled)


def run(args):
    """Describe one picture. Returns an exit code (0 ok, 1 failed)."""
    settings = Settings()
    cache = _get_cache(settings, args.no_cache)
    if not os.path.isfile(args.file):
        print("No such file: %s" % args.file, file=sys.stderr)
        return 1
    with open(args.file, "rb") as fh:
        image_bytes = fh.read()
    prompt = args.prompt or settings.get("prompt")
    fast_model = args.fast_model or settings.get("fast_model")
    smart_model = args.smart_model or settings.get("smart_model")
    url = args.ollama_url or settings.get("ollama_url")
    # The cache key is the file as given, plus the prompt and models.
    record = cache.get_description(image_bytes, prompt, fast_model,
                                   smart_model)
    from_cache = record is not None
    if record is not None:
        text = record["text"]
        model_used = record["model_used"]
    else:
        client = OllamaClient(url)
        try:
            found = client.describe(image_bytes, prompt, fast_model,
                                    smart_model)
        except OllamaError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        record = found.to_record()
        cache.put_description(image_bytes, prompt, fast_model,
                              smart_model, record)
        text = found.text
        model_used = found.model_used
    # The file is described as given, so before and after match.
    info = tokens.image_info(args.file)
    toks = tokens.vision_tokens(info["width"], info["height"])
    measure = tokens.describe_measurements(
        record.get("fast_seconds"), record.get("smart_seconds"),
        toks, toks, info["bytes"], info["bytes"])
    if args.json:
        print(json.dumps({
            "text": text,
            "model_used": model_used,
            "fast_seconds": record.get("fast_seconds"),
            "smart_seconds": record.get("smart_seconds"),
            "escalated": record.get("escalated", False),
            "fast_tried": record.get("fast_tried", False),
            "from_cache": from_cache,
            "tokens_before": toks,
            "tokens_after": toks,
            "bytes_before": info["bytes"],
            "bytes_after": info["bytes"],
        }))
        return 0
    print(text)
    print()
    cache_note = " (from cache)" if from_cache else ""
    print("Model: %s%s" % (model_used, cache_note))
    print(tokens.format_measurements(measure))
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print("Could not read or write a file: %s" % exc,
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
