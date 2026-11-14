"""Redaction engine for Safe Share Scrubber. Standard library only.

scrub_text(text) finds secrets and replaces each one with a labeled
marker like [REDACTED AWS KEY]. Findings carry the secret kind and
the 1-based line number, never the secret value.

scrub_file(path) reads a file, writes a safe copy next to it, and
returns a result dict. The original file is never changed.

The bare-token patterns are deliberately tight: a bare hex string is
only a finding when it sits next to a key-ish word (a git commit hash
in a sentence is not a secret), and a bare mixed-case token needs 40
or more characters with upper case, lower case, and a digit (a UUID
does not qualify). A run that decodes as base64 to printable text is
a data blob, not a token, and is left alone. Redaction is pattern
based and cannot prove a file holds no secret it has no pattern for;
the report says so in plain words.
"""

import base64
import re
from pathlib import Path

# ---------------------------------------------------------------- kinds

KIND_AWS = "AWS access key"
KIND_JWT = "JWT"
KIND_PRIVATE_KEY = "Private key"
KIND_GITHUB = "GitHub token"
KIND_SLACK = "Slack token"
KIND_GOOGLE = "Google API key"
KIND_BEARER = "Bearer token"
KIND_ASSIGNMENT = "Password or secret in assignment"
KIND_URL_PASSWORD = "Password in URL"
KIND_URL_QUERY = "Secret in URL query"
KIND_BARE_TOKEN = "Bare token"

MARKER_AWS = "[REDACTED AWS KEY]"
MARKER_JWT = "[REDACTED JWT]"
MARKER_PRIVATE_KEY = "[REDACTED PRIVATE KEY]"
MARKER_GITHUB = "[REDACTED GITHUB TOKEN]"
MARKER_SLACK = "[REDACTED SLACK TOKEN]"
MARKER_GOOGLE = "[REDACTED GOOGLE API KEY]"
MARKER_BEARER = "[REDACTED BEARER TOKEN]"
MARKER_ASSIGNMENT = "[REDACTED PASSWORD OR SECRET]"
MARKER_URL_PASSWORD = "[REDACTED PASSWORD]"
MARKER_URL_QUERY = "[REDACTED URL SECRET]"
MARKER_BARE_TOKEN = "[REDACTED TOKEN]"

# ---------------------------------------------------------------- patterns

# Each rule is (kind, marker, pattern, value_group, guard). When
# value_group is None the whole match is replaced by the marker;
# otherwise only that group is replaced and the rest of the match
# is kept (so a key name, a user name, or a header survives). guard
# is an optional callable that vetoes a match (value -> True means
# leave it alone). Rules run in this order: specific token shapes
# first, URLs before assignments (so a secret query param reads as
# a URL finding, not an assignment finding), bare tokens last.
_RULES = [
    (KIND_AWS, MARKER_AWS,
     re.compile(r"AKIA[0-9A-Z]{16}"), None, None),
    (KIND_JWT, MARKER_JWT,
     re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
     None, None),
    (KIND_GITHUB, MARKER_GITHUB,
     re.compile(r"(?:ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9]{20,}"
                r"|github_pat_[A-Za-z0-9_]{20,}"), None, None),
    (KIND_SLACK, MARKER_SLACK,
     re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), None, None),
    (KIND_GOOGLE, MARKER_GOOGLE,
     re.compile(r"AIza[0-9A-Za-z_-]{35}"), None, None),
    (KIND_URL_PASSWORD, MARKER_URL_PASSWORD,
     re.compile(r"(https?://[^:/\s]+:)([^@\s]+)(@)"), 2, None),
    (KIND_URL_QUERY, MARKER_URL_QUERY,
     re.compile(r"([?&](?:api[_-]?key|api[_-]?token|token|secret|"
                r"password|passwd|auth|access[_-]?token|"
                r"client[_-]?secret)=)([^&\s\"']+)",
                re.IGNORECASE), 2, None),
    (KIND_BEARER, MARKER_BEARER,
     re.compile(r"(Authorization:\s*Bearer\s+)(\S+)",
                re.IGNORECASE), 2, None),
    (KIND_ASSIGNMENT, MARKER_ASSIGNMENT,
     re.compile(r"(?i)(password|passwd|pwd|api[_-]?key|api[_-]?token|"
                r"access[_-]?token|auth[_-]?token|secret|token|"
                r"client[_-]?secret)"
                # The closing quote covers JSON keys: "secret": "x".
                r"([\"']?\s*[:=]\s*[\"']?)"
                r"([^\s\"'}\],;]+)"), 3, None),
    (KIND_BARE_TOKEN, MARKER_BARE_TOKEN,
     re.compile(r"sk[-_][A-Za-z0-9_-]{16,}"), None, None),
    (KIND_BARE_TOKEN, MARKER_BARE_TOKEN,
     re.compile(r"\b(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])"
                r"(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]{40,}\b"),
     None, "base64_text"),
    # Bare hex only counts next to a key-ish word: a hash standing
    # alone in a sentence (a git commit, a checksum) is not a secret.
    (KIND_BARE_TOKEN, MARKER_BARE_TOKEN,
     re.compile(r"(?i)(?:\b(?:api[_ -]?key|key|token|secret|auth)\b"
                r"[^A-Za-z0-9\n]{0,12})([0-9a-fA-F]{40,})\b"), 1,
     None),
]

_PEM_BEGIN = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
_PEM_END = re.compile(
    r"-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")

VERDICT_SAFE = "Safe to share"
VERDICT_REMAIN = "Not safe to share: secrets remain after redaction"
VERDICT_BINARY = "Skipped: binary file, not scrubbed"
VERDICT_UNREADABLE = "Could not read file"


def _looks_like_base64_text(run):
    """True when a run decodes as base64 to printable text.

    A base64 blob of text and a random token look the same by shape,
    but they decode differently: text decodes to printable bytes,
    a random token decodes to binary garbage. A run that decodes to
    printable text is a data blob, not a token.
    """
    try:
        padded = run + "=" * (-len(run) % 4)
        decoded = base64.b64decode(padded, validate=True)
    except (ValueError, base64.binascii.Error):
        return False
    if len(decoded) < 20:
        return False
    return all(32 <= byte < 127 or byte in (9, 10, 13)
               for byte in decoded)


def _apply_rule(line, rule, line_no, findings):
    """Run one rule over one line, recording findings."""
    kind, marker, pattern, value_group, guard = rule

    def vetoed(value):
        if value.startswith("[REDACTED"):
            return True
        if guard == "base64_text":
            return _looks_like_base64_text(value)
        return False

    def repl(match):
        if value_group is None:
            value = match.group(0)
            if vetoed(value):
                return match.group(0)
            findings.append({"kind": kind, "line": line_no,
                             "marker": marker})
            return marker
        value = match.group(value_group)
        if vetoed(value):
            return match.group(0)
        findings.append({"kind": kind, "line": line_no,
                         "marker": marker})
        start, end = match.span(value_group)
        base = match.start()
        text = match.group(0)
        return text[:start - base] + marker + text[end - base:]

    return pattern.sub(repl, line)


def _strip_pem_blocks(lines):
    """Replace PEM blocks with one marker line each.

    lines is the original line list. Returns (new_lines,
    orig_line_numbers, findings): new_lines keeps the original line
    numbers in orig_line_numbers, so findings after a multi-line PEM
    block still point at the right original line. An unclosed BEGIN
    redacts through the end of the file.
    """
    out_lines = []
    out_numbers = []
    findings = []
    i = 0
    while i < len(lines):
        if _PEM_BEGIN.search(lines[i]):
            begin = i
            end = None
            for j in range(begin + 1, len(lines)):
                if _PEM_END.search(lines[j]):
                    end = j
                    break
            if end is None:
                end = len(lines) - 1
            findings.append({"kind": KIND_PRIVATE_KEY,
                             "line": begin + 1,
                             "marker": MARKER_PRIVATE_KEY})
            out_lines.append(MARKER_PRIVATE_KEY)
            out_numbers.append(begin + 1)
            i = end + 1
        else:
            out_lines.append(lines[i])
            out_numbers.append(i + 1)
            i += 1
    return out_lines, out_numbers, findings


def scrub_text(text):
    """Redact secrets in text.

    Returns (scrubbed_text, findings). Findings are dicts {kind,
    line, marker} with 1-based line numbers in the ORIGINAL text.
    No secret value ever appears in a finding.
    """
    lines = text.split("\n")
    lines, numbers, findings = _strip_pem_blocks(lines)
    scrubbed_lines = []
    for line, line_no in zip(lines, numbers):
        for rule in _RULES:
            line = _apply_rule(line, rule, line_no, findings)
        scrubbed_lines.append(line)
    # PEM findings were collected before the line pass; put the
    # whole list back in line order (stable, so findings on one
    # line keep rule order).
    findings.sort(key=lambda item: item["line"])
    return "\n".join(scrubbed_lines), findings


def safe_copy_path(path):
    """debug.log -> debug.safe.log; a file with no extension gets
    .safe appended to its name."""
    path = Path(path)
    if path.suffix:
        return path.with_name(path.stem + ".safe" + path.suffix)
    return path.with_name(path.name + ".safe")


def _is_binary(data):
    """A file is binary when it holds NUL bytes or is not UTF-8."""
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def scrub_file(path):
    """Scrub one file and write its safe copy next to it.

    Returns a result dict: path, safe_path (None when skipped or
    unreadable), findings, secrets_found, verdict, skipped,
    skipped_reason, error. The original file is never changed.
    Verdict is "Safe to share" only when a re-scan of the scrubbed
    text finds zero secrets left.
    """
    path = Path(path)
    result = {
        "path": str(path),
        "safe_path": None,
        "findings": [],
        "secrets_found": 0,
        "verdict": "",
        "skipped": False,
        "skipped_reason": None,
        "error": None,
    }
    try:
        data = path.read_bytes()
    except OSError as exc:
        result["error"] = str(exc)
        result["verdict"] = VERDICT_UNREADABLE
        return result
    if _is_binary(data):
        result["skipped"] = True
        if b"\x00" in data:
            reason = "binary file (contains NUL bytes)"
        else:
            reason = "binary file (not UTF-8 text)"
        result["skipped_reason"] = reason
        result["verdict"] = VERDICT_BINARY
        return result
    text = data.decode("utf-8")
    scrubbed, findings = scrub_text(text)
    remaining = scrub_text(scrubbed)[1]
    safe_path = safe_copy_path(path)
    try:
        safe_path.write_text(scrubbed, encoding="utf-8")
    except OSError as exc:
        result["error"] = str(exc)
        result["verdict"] = VERDICT_UNREADABLE
        return result
    result["safe_path"] = str(safe_path)
    result["findings"] = findings
    result["secrets_found"] = len(findings)
    if remaining:
        result["verdict"] = VERDICT_REMAIN
    else:
        result["verdict"] = VERDICT_SAFE
    return result
