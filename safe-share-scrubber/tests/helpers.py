"""Shared test helpers: obviously fake secrets and file fixtures.

Every secret value here is constructed from FAKE markers and matches
a redaction pattern by shape only. Nothing here resembles a real
secret. Values are built from parts (concatenation), never written
as one literal — a full secret-shaped literal in the file trips
secret scanners on push, even with FAKE in it (proven 2026-11-14:
the Slack fixture blocked the first push).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

# Fake secrets, one per shape the engine must catch.
FAKE_AWS = "AKIA" + "FAKEKEY" + "123456789"
FAKE_JWT = ("eyJ" + "FAKEHEADER" + ".eyJ" + "FAKEPAYLOAD"
            + ".FAKESIGNATURE123456")
FAKE_PEM_BODY = ("RkFLRU1BQ0tFRVlCUkFLRU1BQ0tFRVlCUkFLRU1BQ0tF"
                 "RVlCUkFLRU1BQ0tFRVlC")
FAKE_PEM = ("-----BEGIN " + "RSA PRIVATE KEY-----\n" + FAKE_PEM_BODY
            + "\n" + FAKE_PEM_BODY
            + "\n-----END " + "RSA PRIVATE KEY-----")
FAKE_GITHUB = "ghp_" + "FAKE" * 9
FAKE_GITHUB_PAT = "github_pat_" + "FAKE" * 9 + "_FAKEFAKE"
FAKE_SLACK = "xoxb-" + "123456789012" + "-" + "FAKE" * 4
FAKE_GOOGLE = "AIza" + "F4K3" * 8 + "ABC"
FAKE_BEARER = "FAKEBEARERTOKEN1234567890"
FAKE_PASSWORD = "FAKEPASSWORD123"
FAKE_API_KEY = "FAKEAPIKEYVALUE99"
FAKE_URL_PASS = "FAKEURLPASS123"
FAKE_QUERY_KEY = "FAKEQUERYKEY123"
FAKE_SK = "sk-" + "FAKE" * 6 + "1234"
FAKE_BARE_MIXED = "Ab3d" * 10
FAKE_HEX_KEY = "a1b2c3d4e5f6" * 4

ALL_FAKES = [FAKE_AWS, FAKE_JWT, FAKE_PEM_BODY, FAKE_GITHUB,
             FAKE_GITHUB_PAT, FAKE_SLACK, FAKE_GOOGLE, FAKE_BEARER,
             FAKE_PASSWORD, FAKE_API_KEY, FAKE_URL_PASS,
             FAKE_QUERY_KEY, FAKE_SK, FAKE_BARE_MIXED, FAKE_HEX_KEY]

# Innocent text that looks secret-ish and must NOT be redacted.
INNOCENT_GIT_HASH = "deadbeefcafe1234deadbeefcafe1234deadbeef"
INNOCENT_UUID = "123e4567-e89b-12d3-a456-426614174000"
INNOCENT_URL = "https://example.com/docs/guide?page=2"
INNOCENT_PROSE = "Remember to change your password regularly."
# Base64 of "HelloWorld" x3: 40 chars, mixed case, has digits, but
# decodes to printable text, so it is a blob, not a token.
INNOCENT_BASE64 = "SGVsbG9Xb3JsZEhlbGxvV29ybGRIZWxsb1dvcmxk"


def make_text_file(path, content):
    """Write a UTF-8 text fixture and return its path."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def sample_log_with_secrets():
    """A small log carrying one of each secret shape."""
    return "\n".join([
        "2026-11-14 app started",
        "aws key here: " + FAKE_AWS,
        "jwt: " + FAKE_JWT,
        "token " + FAKE_GITHUB,
        "slack " + FAKE_SLACK,
        "google " + FAKE_GOOGLE,
        "Authorization: Bearer " + FAKE_BEARER,
        "password=" + FAKE_PASSWORD,
        "api-key: " + FAKE_API_KEY,
        "url https://fakeuser:" + FAKE_URL_PASS + "@example.com/path",
        "query https://example.com/api?api_key=" + FAKE_QUERY_KEY
        + "&x=1",
        "bare " + FAKE_SK,
        "mixed " + FAKE_BARE_MIXED,
        "token " + FAKE_HEX_KEY,
        FAKE_PEM,
        "Traceback (most recent call last):",
        '  File "app.py", line 9, in main',
        '    raise ValueError("token ' + FAKE_GITHUB + '")',
        "done",
    ]) + "\n"


def sample_innocent_text():
    """Innocent text that looks secret-ish. Must survive untouched."""
    return "\n".join([
        "Fixed in commit " + INNOCENT_GIT_HASH + ", see the log.",
        "Session " + INNOCENT_UUID + " started.",
        "See " + INNOCENT_URL + " for details.",
        INNOCENT_PROSE,
        "Blob: " + INNOCENT_BASE64,
    ]) + "\n"
