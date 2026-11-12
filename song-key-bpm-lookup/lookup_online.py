#!/usr/bin/env python3
"""T17 online provider — MusicBrainz + AcousticBrainz.

Free, no API key. Verified live 2026-11-12 (MusicBrainz returned a real
recording for "Plush / Stone Temple Pilots"; AcousticBrainz returned a
proper 404 for a recording with no submission).

Docs:
  * MusicBrainz API: https://musicbrainz.org/doc/MusicBrainz_API
    (1 request/second limit, descriptive User-Agent required)
  * AcousticBrainz API: https://acousticbrainz.org/data
    (GET /api/v1/<mbid>/high-level for key, /low-level for BPM)

Flow: MusicBrainz search recording by title+artist -> MBID -> AcousticBrainz
high-level (tonal.key_key + tonal.key_scale) and low-level (rhythm.bpm).

Honest limits:
  * AcousticBrainz only has data for tracks users submitted — most lookups
    return "no data". That is reported, never faked.
  * MusicBrainz rate-limits to 1 req/sec and may return "server busy"
    under load (seen live 2026-11-12 on a shared IP). Retries once after
    a short wait; a busy server is "could not check", not "not found".
  * Key confidence comes from AcousticBrainz's key_strength; low strength
    is reported alongside the key.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "bnb-tools-song-key-bpm-lookup/1.0 (https://github.com/BROKE-N-BORED/BNB-TOOLS)"
MB_SEARCH = "https://musicbrainz.org/ws/2/recording/?query=%s&fmt=json&limit=1"
AB = "https://acousticbrainz.org/api/v1/%s/%s"


def _get_json(url, retries=1):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 404:
            return 404, None
        if e.code == 503 and retries > 0:
            time.sleep(2)
            return _get_json(url, retries - 1)
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"error": body[:200]}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, {"error": "network failure: %s" % e}


def parse_acousticbrainz(high, low):
    """Extract key/BPM from AcousticBrainz responses (pure function, so
    the smoke test can verify parsing without the network)."""
    out = {"key": None, "key_strength": None, "bpm": None}
    if high:
        tonal = high.get("tonal", {})
        k, scale = tonal.get("key_key"), tonal.get("key_scale")
        if k and scale:
            out["key"] = "%s %s" % (k, scale)
            out["key_strength"] = tonal.get("key_strength")
    if low:
        bpm = low.get("rhythm", {}).get("bpm")
        if bpm:
            out["bpm"] = round(float(bpm))
    return out


def lookup_song(title, artist):
    """Look up one song. Returns a dict with key/bpm (or None) + notes."""
    result = {"title": title, "artist": artist, "key": None, "bpm": None,
              "mbid": None, "source": None, "note": ""}
    query = "recording:%s AND artist:%s" % (title, artist)
    status, data = _get_json(MB_SEARCH % urllib.parse.quote(query))
    if status is None:
        result["note"] = data.get("error", "network failure")
        return result
    if status != 200 or not data or "recordings" not in data:
        result["note"] = ("MusicBrainz could not be reached "
                          "(status %s; %s)"
                          % (status, (data or {}).get("error", "")))
        return result
    if not data["recordings"]:
        result["note"] = "no MusicBrainz recording found"
        return result
    rec = data["recordings"][0]
    result["mbid"] = rec["id"]
    result["mb_title"] = rec.get("title")
    time.sleep(1.1)  # MusicBrainz asks for 1 req/sec
    h_status, high = _get_json(AB % (rec["id"], "high-level"))
    l_status, low = _get_json(AB % (rec["id"], "low-level"))
    if h_status == 404 and l_status == 404:
        result["note"] = ("MusicBrainz found the recording, but "
                          "AcousticBrainz has no submission for it "
                          "(sparse coverage — most tracks have none)")
        return result
    parsed = parse_acousticbrainz(
        high if h_status == 200 else None,
        low if l_status == 200 else None)
    result.update(parsed)
    result["source"] = "AcousticBrainz"
    if result["key_strength"] is not None and result["key_strength"] < 0.5:
        result["note"] = ("key confidence low (strength %.2f) — treat as "
                          "a guess" % result["key_strength"])
    return result
