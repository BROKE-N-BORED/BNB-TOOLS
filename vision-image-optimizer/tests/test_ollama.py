"""Ollama client against the fake server: fast-first, escalation,
down handling, tags parsing, timeouts."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import (BLIND_DESCRIPTION, GOOD_DESCRIPTION,  # noqa: E402
                     SHORT_DESCRIPTION, FakeOllama)
from optimizer.ollama import (OllamaClient, OllamaDownError,  # noqa: E402
                              OllamaError, is_insufficient)


class InsufficientTests(unittest.TestCase):
    def test_empty_is_insufficient(self):
        self.assertTrue(is_insufficient(""))
        self.assertTrue(is_insufficient("   "))
        self.assertTrue(is_insufficient(None))

    def test_short_is_insufficient(self):
        self.assertTrue(is_insufficient("A bike."))
        self.assertTrue(is_insufficient("1234567890123456789"))

    def test_blind_phrases_are_insufficient(self):
        self.assertTrue(is_insufficient(
            "Sorry, I cannot see the image at all right now."))
        self.assertTrue(is_insufficient(
            "I can't see anything in this picture, it is dark."))
        self.assertTrue(is_insufficient(
            "I am unable to see what is in this image."))

    def test_good_answer_is_sufficient(self):
        self.assertFalse(is_insufficient(GOOD_DESCRIPTION))


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.stop()

    def _server(self, **kwargs):
        server = FakeOllama(**kwargs).start()
        self.servers.append(server)
        return server

    def test_tags_parsing(self):
        server = self._server(models=["minicpm-v", "other-model"])
        client = OllamaClient(server.base_url)
        self.assertEqual(client.list_models(),
                         ["minicpm-v", "other-model"])
        self.assertTrue(client.is_running())

    def test_describe_returns_fake_description(self):
        server = self._server()
        client = OllamaClient(server.base_url)
        result = client.describe(b"fake-image-bytes")
        self.assertEqual(result.text, GOOD_DESCRIPTION)
        self.assertEqual(result.model_used, "minicpm-v")
        self.assertFalse(result.escalated)
        self.assertTrue(result.fast_tried)

    def test_fast_first_uses_fast_when_installed(self):
        server = self._server(responses={
            "minicpm-v": GOOD_DESCRIPTION,
            "qwen3-vl:2b-instruct": "smart answer " + "x" * 40})
        client = OllamaClient(server.base_url)
        result = client.describe(b"fake-image-bytes")
        self.assertEqual(result.model_used, "minicpm-v")
        self.assertEqual([c[0] for c in server.calls],
                         ["minicpm-v"])

    def test_escalation_on_empty_fast_answer(self):
        server = self._server(responses={
            "minicpm-v": "",
            "qwen3-vl:2b-instruct": GOOD_DESCRIPTION})
        client = OllamaClient(server.base_url)
        result = client.describe(b"fake-image-bytes")
        self.assertTrue(result.escalated)
        self.assertEqual(result.model_used, "qwen3-vl:2b-instruct")
        self.assertEqual(result.text, GOOD_DESCRIPTION)
        self.assertEqual([c[0] for c in server.calls],
                         ["minicpm-v", "qwen3-vl:2b-instruct"])

    def test_escalation_on_short_fast_answer(self):
        server = self._server(responses={
            "minicpm-v": SHORT_DESCRIPTION,
            "qwen3-vl:2b-instruct": GOOD_DESCRIPTION})
        client = OllamaClient(server.base_url)
        result = client.describe(b"fake-image-bytes")
        self.assertTrue(result.escalated)
        self.assertEqual(result.model_used, "qwen3-vl:2b-instruct")

    def test_escalation_on_cannot_see(self):
        server = self._server(responses={
            "minicpm-v": BLIND_DESCRIPTION,
            "qwen3-vl:2b-instruct": GOOD_DESCRIPTION})
        client = OllamaClient(server.base_url)
        result = client.describe(b"fake-image-bytes")
        self.assertTrue(result.escalated)
        self.assertEqual(result.model_used, "qwen3-vl:2b-instruct")

    def test_no_escalation_when_fast_answer_is_good(self):
        server = self._server(responses={
            "minicpm-v": GOOD_DESCRIPTION,
            "qwen3-vl:2b-instruct": "smart answer " + "x" * 40})
        client = OllamaClient(server.base_url)
        result = client.describe(b"fake-image-bytes")
        self.assertFalse(result.escalated)
        self.assertEqual(len(server.calls), 1)

    def test_fast_not_installed_goes_straight_to_smart(self):
        server = self._server(models=["qwen3-vl:2b-instruct"],
                              responses={
                                  "qwen3-vl:2b-instruct":
                                      GOOD_DESCRIPTION})
        client = OllamaClient(server.base_url)
        result = client.describe(b"fake-image-bytes")
        self.assertFalse(result.fast_tried)
        self.assertFalse(result.escalated)
        self.assertEqual(result.model_used, "qwen3-vl:2b-instruct")
        self.assertEqual([c[0] for c in server.calls],
                         ["qwen3-vl:2b-instruct"])

    def test_timings_are_measured(self):
        server = self._server(delay=0.2)
        client = OllamaClient(server.base_url)
        result = client.describe(b"fake-image-bytes")
        self.assertIsNotNone(result.fast_seconds)
        self.assertGreaterEqual(result.fast_seconds, 0.15)
        self.assertIsNone(result.smart_seconds)

    def test_ollama_down_raises_plain_error(self):
        # A port nothing listens on: start a server, stop it, reuse
        # the port number.
        server = FakeOllama().start()
        url = server.base_url
        server.stop()
        client = OllamaClient(url)
        with self.assertRaises(OllamaDownError) as ctx:
            client.describe(b"fake-image-bytes")
        self.assertIn("not running", str(ctx.exception))
        self.assertFalse(client.is_running())

    def test_timeout_handling(self):
        server = self._server(delay=2.0)
        client = OllamaClient(server.base_url, timeout=0.5)
        with self.assertRaises(OllamaDownError) as ctx:
            client.describe(b"fake-image-bytes")
        self.assertIn("did not answer in time", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
