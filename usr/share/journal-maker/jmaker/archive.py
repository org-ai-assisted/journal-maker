#!/usr/bin/python3 -Bsu
"""Offline Wayback archiver for the HTML preview's reference archive links.

Separate from the build (which is NETWORK-FREE): this talks to archive.org to populate the
per-reference `archive = { ... }` field in an article's source-quotes.toml, which the build
then reads to render Robust Links. Two phases:

  fetch  -- for each url-bearing refs.bib entry, ask the Wayback Availability API for the
            closest genuine snapshot; for a miss, optionally Save Page Now via the installed
            `ia-save` helper. Writes a resumable cache (key -> memento | no_memento reason).
            Connects ONLY to archive.org, never to the cited target, so there is no SSRF
            surface to guard (unlike a dead-link scanner that fetches the target itself).
  apply  -- surgically insert one `archive = { ... }` line per [citekey] table in
            source-quotes.toml (line-oriented text edit; no TOML round-trip, so the hand
            maintained file's comments and arrays are untouched).

Only a genuine, dated memento whose embedded original matches the cited url is stored; a
miss is recorded as no_memento (the build renders NO link and flags it), never faked.
"""

import json
import os
import re
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from jmaker import generate

_USER_AGENT = "journal-maker-archive (reference preservation)"


def _sleep(seconds):
    """Throttle/backoff sleep. A module-level seam so a test can observe/suppress it."""
    time.sleep(seconds)


def _https_memento(url):
    """The Availability API returns the snapshot URL with an http:// scheme; our links are
    https. Force https on the archive host only (leaves the embedded original untouched)."""
    if url.startswith("http://web.archive.org/"):
        return "https://" + url[len("http://"):]
    return url


def _closest_memento(data):
    """Parse the Availability API JSON (archived_snapshots.closest.url) into a genuine,
    https, dated memento, or None. Mirrors the public archive.org API contract."""
    snap = (data.get("archived_snapshots") or {}).get("closest") or {}
    mem = (snap.get("url") or "").strip()
    if not mem:
        return None
    mem = _https_memento(mem)
    return mem if generate._parse_memento(mem) else None


def _memento_matches(memento, url):
    """True iff the memento is genuine AND its embedded original is the cited url (under the
    same conservative normalization the build's honesty gate uses -- so the archiver never
    stores a memento the gate would reject at build time)."""
    parsed = generate._parse_memento(memento)
    if not parsed:
        return False
    _date, embedded = parsed
    return (generate._norm_url_for_compare(embedded)
            == generate._norm_url_for_compare(url))


def _retry_after_seconds(header):
    """Seconds to wait for a Retry-After header value (an integer delta, or an HTTP-date),
    or None when it cannot be parsed."""
    if not header:
        return None
    header = header.strip()
    if header.isdigit():
        return float(header)
    try:
        import email.utils
        dt = email.utils.parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    delta = dt.timestamp() - time.time()
    return delta if delta > 0 else 0.0


def _build_opener():
    # http(s) only; no handler for file:/ftp: etc.
    return urllib.request.build_opener(
        urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
        urllib.request.HTTPRedirectHandler())


def _availability(url, *, opener, base_delay, log, attempts=4, timeout=30):
    """Closest genuine memento for `url` from the Availability API, or None. Hard-throttles
    (base_delay before every request), honors Retry-After, and backs off exponentially on
    429/5xx -- this host rate-limits bursts."""
    api = "https://archive.org/wayback/available?url=" + quote(url, safe="")
    req = urllib.request.Request(api, headers={"User-Agent": _USER_AGENT})
    delay = base_delay
    for attempt in range(attempts):
        _sleep(base_delay)
        try:
            with opener.open(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            return _closest_memento(data)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                wait = _retry_after_seconds(exc.headers.get("Retry-After")) or delay
                log("  availability HTTP %d; backing off %.0fs" % (exc.code, wait))
                _sleep(wait)
                delay *= 2
                continue
            log("  availability HTTP %d (giving up)" % exc.code)
            return None
        except (urllib.error.URLError, ValueError, OSError) as exc:
            if attempt + 1 < attempts:
                log("  availability error (%s); retrying" % exc)
                _sleep(delay)
                delay *= 2
                continue
            return None
    return None


def _save_page_now(url, *, tor, log):
    """Capture `url` with Save Page Now via the installed `ia-save` helper (reuse of the
    single source, not a reimplementation). Returns a genuine https memento, or None on a
    failure / rate-limit / bot-block (ia-save exits non-zero with a message)."""
    cmd = ["ia-save"] + (["--tor"] if tor else []) + ["--", url]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log("  SPN failed to run ia-save: %s" % exc)
        return None
    if res.returncode != 0:
        log("  SPN blocked/failed: %s" % (res.stderr.strip().splitlines()[-1]
                                          if res.stderr.strip() else "no output"))
        return None
    out = res.stdout.strip().splitlines()
    mem = _https_memento(out[-1].strip()) if out else ""
    return mem if generate._parse_memento(mem) else None


def _load_cache(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_cache(path, cache):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, sort_keys=True)
        fh.write("\n")


def fetch(article_dir, *, save, tor, base_delay, cache_path, log):
    """Populate the cache from archive.org. Resumable: a key with a confirmed memento is
    skipped on re-run; a miss is retried (a snapshot may have appeared, or SPN may now
    succeed). The cache file grows as it goes, so a background supervisor can watch it."""
    bib = os.path.join(article_dir, "refs.bib")
    csl = generate._csl_entries(bib)
    cache = _load_cache(cache_path)
    opener = _build_opener()
    for key, entry in csl.items():
        url = (entry.get("URL") or "").strip()
        if not url:
            continue   # DOI-only / linkless: nothing to archive
        host = (urlsplit(url).hostname or "").lower()
        if host == "web.archive.org" or host.endswith(".web.archive.org"):
            log("%s: bib url is already a Wayback memento; skipping" % key)
            continue
        if cache.get(key, {}).get("memento"):
            continue   # already resolved
        log("%s: %s" % (key, url))
        mem = _availability(url, opener=opener, base_delay=base_delay, log=log)
        if not (mem and _memento_matches(mem, url)):
            if mem:
                log("  availability snapshot is of a different url; ignoring")
            if save:
                log("  Save Page Now ...")
                spn = _save_page_now(url, tor=tor, log=log)
                mem = spn if (spn and _memento_matches(spn, url)) else None
            else:
                mem = None
        if mem:
            cache[key] = {"memento": mem}
            log("  -> %s" % mem)
        else:
            cache[key] = {"no_memento": "no Wayback snapshot available"}
            log("  -> no snapshot")
        _save_cache(cache_path, cache)
    return cache


_HEADER_RE = re.compile(r'^\[([^\[\]]+)\]\s*$')
_ARCHIVE_LINE_RE = re.compile(r'^\s*archive\s*=')


def _toml_escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _archive_toml_line(entry):
    if "memento" in entry:
        return 'archive = { memento = "%s" }\n' % _toml_escape(entry["memento"])
    return 'archive = { no_memento = "%s" }\n' % _toml_escape(entry["no_memento"])


def _ml_after(line, state):
    """Track TOML multiline-string ('''/\"\"\") open/close across lines so a [bracket] or
    `archive =` sequence INSIDE a string value is not mistaken for structure. Approximate
    (it does not model single-line string contents), but apply() re-parses the result with
    tomllib and refuses to write unless only the archive field changed -- so a miss fails
    closed, it never corrupts the file. `state` is None or the open delimiter."""
    i, n = 0, len(line)
    while i < n:
        if state is None:
            if line.startswith('"""', i) or line.startswith("'''", i):
                state = line[i:i + 3]
                i += 3
                continue
        elif line.startswith(state, i):
            state = None
            i += 3
            continue
        i += 1
    return state


def _apply_text(text, cache):
    """Return source-quotes.toml text with one `archive = { ... }` line inserted right after
    each [citekey] header present in the cache (replacing any prior archive line in that
    table, so a re-apply is idempotent). A line-oriented edit that skips multiline-string
    bodies: nothing else is reformatted. Returns (new_text, applied_keys)."""
    out = []
    cur = None
    applied = set()
    in_ml = None
    for line in text.splitlines(keepends=True):
        if in_ml is None:
            m = _HEADER_RE.match(line)
            if m:
                cur = m.group(1)
                out.append(line)
                if cur in cache:
                    out.append(_archive_toml_line(cache[cur]))
                    applied.add(cur)
                in_ml = _ml_after(line, in_ml)
                continue
            if cur in cache and _ARCHIVE_LINE_RE.match(line):
                in_ml = _ml_after(line, in_ml)
                continue   # drop a stale archive line in a managed table
        out.append(line)
        in_ml = _ml_after(line, in_ml)
    return "".join(out), applied


def _verify_only_archive_changed(old_text, new_text, cache, toml_path):
    """Fail-closed safety net: re-parse both texts with tomllib and refuse to write unless
    the ONLY difference is the archive field of each managed [key] (every other table and
    field byte-equal in meaning). Catches any edit the line-oriented pass got wrong rather
    than silently rewriting the author's source of truth."""
    old = tomllib.loads(old_text)
    new = tomllib.loads(new_text)
    if set(old) != set(new):
        raise generate.BuildError(
            "archive: apply would change the set of tables in %s -- refusing to write"
            % toml_path)
    for key, table in old.items():
        if key in cache:
            expected = {k: v for k, v in table.items() if k != "archive"}
            expected["archive"] = ({"memento": cache[key]["memento"]}
                                   if "memento" in cache[key]
                                   else {"no_memento": cache[key]["no_memento"]})
        else:
            expected = table
        if new.get(key) != expected:
            raise generate.BuildError(
                "archive: apply would change more than the archive field of [%s] in %s -- "
                "refusing to write (multiline value or unexpected edit?)" % (key, toml_path))


def apply(article_dir, *, cache_path, log):
    toml_path = os.path.join(article_dir, "source-quotes.toml")
    cache = _load_cache(cache_path)
    if not cache:
        raise generate.BuildError("archive: cache %s is empty; run fetch first"
                                   % cache_path)
    with open(toml_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    new_text, applied = _apply_text(text, cache)
    missing = sorted(set(cache) - applied)
    if missing:
        raise generate.BuildError(
            "archive: %d cache key(s) have no [table] in %s (refs.bib / sidecar drift?): %s"
            % (len(missing), toml_path, ", ".join(missing)))
    _verify_only_archive_changed(text, new_text, cache, toml_path)
    with open(toml_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    links = sum(1 for e in cache.values() if "memento" in e)
    log("archive: wrote %d archive line(s) (%d memento, %d no_memento) into %s"
        % (len(applied), links, len(applied) - links, toml_path))


def main(args):
    do_fetch = args.fetch or not (args.fetch or args.apply)
    do_apply = args.apply or not (args.fetch or args.apply)
    cache_path = args.cache or os.path.join(args.article_dir, ".archive-cache.json")

    def log(msg):
        print(msg, flush=True)

    try:
        if do_fetch:
            fetch(args.article_dir, save=args.save, tor=args.tor,
                  base_delay=args.delay, cache_path=cache_path, log=log)
        if do_apply:
            apply(args.article_dir, cache_path=cache_path, log=log)
    except generate.BuildError as exc:
        print("archive error: %s" % exc, flush=True)
        return 1
    return 0
