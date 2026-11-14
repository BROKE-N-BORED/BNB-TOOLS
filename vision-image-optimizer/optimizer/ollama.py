"""Ollama client for Vision Image Optimizer.

Fast-first-smart-second: a small model looks first, and the bigger
model only wakes up when the fast look cannot see enough. HTTP via
the standard library only — no extra dependencies.

"Cannot see enough" means: an empty or whitespace-only answer, an
answer under 20 characters, or an answer containing "can't see",
"cannot see", or "unable to see" (case-insensitive).
"""

import base64
import json
import time
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_FAST_MODEL = "minicpm-v"
DEFAULT_SMART_MODEL = "qwen3-vl:2b-instruct"
DEFAULT_PROMPT = ("Describe this image in plain words. Say what is in "
                  "it and what stands out.")
DEFAULT_TIMEOUT = 120

BLIND_PHRASES = ("can't see", "cannot see", "unable to see")
MIN_GOOD_LENGTH = 20


class OllamaError(Exception):
    """Plain-language Ollama failure (shown to the user as-is)."""


class OllamaDownError(OllamaError):
    """Ollama is not answering at all."""


def is_insufficient(text):
    """True when a fast look did not see enough to trust."""
    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) < MIN_GOOD_LENGTH:
        return True
    lowered = stripped.lower()
    return any(phrase in lowered for phrase in BLIND_PHRASES)


class DescribeResult:
    """What a describe call found, with its measurements."""

    def __init__(self, text, model_used, fast_seconds=None,
                 smart_seconds=None, escalated=False, fast_tried=False):
        self.text = text
        self.model_used = model_used
        self.fast_seconds = fast_seconds
        self.smart_seconds = smart_seconds
        self.escalated = escalated
        self.fast_tried = fast_tried

    def to_record(self):
        return {
            "text": self.text,
            "model_used": self.model_used,
            "fast_seconds": self.fast_seconds,
            "smart_seconds": self.smart_seconds,
            "escalated": self.escalated,
            "fast_tried": self.fast_tried,
        }


class OllamaClient:
    """Minimal Ollama HTTP client (urllib only)."""

    def __init__(self, base_url=DEFAULT_URL, timeout=DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- low level ----------------------------------------------------
    def _request(self, method, path, payload=None, timeout=None):
        url = self.base_url + path
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(
                    req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                detail = json.loads(body).get("error", body)
            except Exception:
                detail = "HTTP %s" % exc.code
            raise OllamaError("Ollama answered with an error: %s"
                              % detail)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise OllamaDownError(
                    "Ollama did not answer in time at %s. It may be "
                    "busy or stopped." % self.base_url)
            raise OllamaDownError(
                "Ollama is not running at %s. Start Ollama and try "
                "again. Shrinking pictures still works without it."
                % self.base_url)
        except TimeoutError:
            raise OllamaDownError(
                "Ollama did not answer in time at %s. It may be busy "
                "or stopped." % self.base_url)
        except (json.JSONDecodeError, ValueError):
            raise OllamaError(
                "Ollama answered, but the answer was not readable.")

    # -- API ----------------------------------------------------------
    def list_models(self):
        """Names of the models Ollama has installed."""
        payload = self._request("GET", "/api/tags", timeout=10)
        return [m.get("name", "") for m in payload.get("models", [])]

    def is_running(self):
        """True when Ollama answers /api/tags."""
        try:
            self.list_models()
            return True
        except OllamaError:
            return False

    def generate(self, model, prompt, image_bytes, timeout=None):
        """One vision call. Returns the model's text answer."""
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
            "stream": False,
        }
        result = self._request("POST", "/api/generate", payload,
                               timeout=timeout)
        return result.get("response", "")

    def describe(self, image_bytes, prompt=DEFAULT_PROMPT,
                 fast_model=DEFAULT_FAST_MODEL,
                 smart_model=DEFAULT_SMART_MODEL, timeout=None):
        """Describe a picture: fast look first, careful look if needed.

        Returns a DescribeResult. Raises OllamaDownError when Ollama
        is not reachable, OllamaError for other plain failures.
        """
        installed = self.list_models()
        fast_seconds = None
        smart_seconds = None
        fast_tried = False

        if fast_model in installed:
            fast_tried = True
            started = time.monotonic()
            fast_text = self.generate(fast_model, prompt, image_bytes,
                                      timeout=timeout)
            fast_seconds = time.monotonic() - started
            if not is_insufficient(fast_text):
                return DescribeResult(
                    fast_text, fast_model, fast_seconds=fast_seconds,
                    fast_tried=True)

        started = time.monotonic()
        smart_text = self.generate(smart_model, prompt, image_bytes,
                                   timeout=timeout)
        smart_seconds = time.monotonic() - started
        return DescribeResult(
            smart_text, smart_model, fast_seconds=fast_seconds,
            smart_seconds=smart_seconds, escalated=fast_tried,
            fast_tried=fast_tried)
