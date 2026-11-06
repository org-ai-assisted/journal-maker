#!/usr/bin/python3 -Bsu
"""Offline Wayback archiver for the HTML preview's reference archive links.

Separate from the build (which is NETWORK-FREE): this talks to archive.org to populate the
per-reference `archive = { ... }` field in an article's source-quotes.toml, which the build
then reads to render Robust Links. Two phases:

  fetch  -- for each url-bearing refs.bib entry, ask the Wayback Availability API for the
            closest genuine snapshot; for a miss, optionally Save Page Now -- authenticated
            SPN2 (archive.org S3 keys in IA_S3_ACCESS_KEY / IA_S3_SECRET_KEY, which bypass the
            anonymous datacenter 429), else the anonymous `ia-save` helper. Writes a resumable
            cache (key -> memento | no_memento reason).
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
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit

from jmaker import generate

_USER_AGENT = "journal-maker-archive (reference preservation)"

# Sentinel distinguishing a TRANSIENT lookup failure (429/5xx/network, retries exhausted)
# from a CONFIRMED absence (the API answered: no snapshot). fetch() must never record
# no_memento for a transient failure -- a re-run retries it.
_LOOKUP_FAILED = object()

# Never sleep longer than this for a Retry-After header (a hostile/huge value must not stall).
_RETRY_AFTER_CAP = 300.0


class _ArchiveOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect ONLY to archive.org over https. Refuse any other target so a
    redirect can never forward the SPN2 IA_S3 Authorization header off the trusted host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = (urlsplit(newurl).hostname or "").lower()
        if not newurl.lower().startswith("https://") or not (
                host == "archive.org" or host.endswith(".archive.org")):
            raise urllib.error.HTTPError(
                req.full_url, code, "refusing redirect off archive.org: %s" % newurl,
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
    # http(s) only (no file:/ftp: handler), and redirects confined to archive.org so a
    # cross-host redirect cannot carry the SPN2 credential away.
    return urllib.request.build_opener(
        urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
        _ArchiveOnlyRedirect())


def _availability(url, *, opener, base_delay, log, attempts=4, timeout=30):
    """Closest genuine memento for `url` from the Availability API. Returns the memento, None
    for a CONFIRMED absence (the API answered with no usable snapshot), or _LOOKUP_FAILED for
    a TRANSIENT failure (429/5xx/network, retries exhausted) -- the caller must not treat the
    latter as absence. Hard-throttles, honors a capped Retry-After, backs off on 429/5xx."""
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
                wait = min(_retry_after_seconds(exc.headers.get("Retry-After")) or delay,
                           _RETRY_AFTER_CAP)
                log("  availability HTTP %d; backing off %.0fs" % (exc.code, wait))
                _sleep(wait)
                delay *= 2
                continue
            log("  availability HTTP %d (transient; will retry on a re-run)" % exc.code)
            return _LOOKUP_FAILED
        except (urllib.error.URLError, ValueError, OSError) as exc:
            if attempt + 1 < attempts:
                log("  availability error (%s); retrying" % exc)
                _sleep(delay)
                delay *= 2
                continue
            return _LOOKUP_FAILED
    return _LOOKUP_FAILED


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


_SPN_SAVE_URL = "https://web.archive.org/save"
_SPN_STATUS_URL = "https://web.archive.org/save/status/"


def _spn_memento_from_status(status):
    """Build a genuine https memento from an SPN2 status payload (status==success, with a
    14-digit `timestamp` and the captured `original_url`), or None. Pure -- unit-testable."""
    if (status or {}).get("status") != "success":
        return None
    ts = str(status.get("timestamp") or "")
    original = status.get("original_url") or ""
    if not ts or not original:
        return None
    mem = "https://web.archive.org/web/%s/%s" % (ts, original)
    return mem if generate._parse_memento(mem) else None


def _save_page_now_auth(url, access, secret, *, opener, base_delay, log,
                        poll_attempts=20):
    """Capture `url` via the AUTHENTICATED Save Page Now 2 API (archive.org S3 keys), which
    is not subject to the anonymous datacenter 429. Submits the job, polls its status
    (throttled), and returns a genuine https memento on success, else None. Talks only to
    archive.org."""
    headers = {"Accept": "application/json",
               "Authorization": "LOW %s:%s" % (access, secret),
               "User-Agent": _USER_AGENT}
    # if_not_archived_within=30d makes a resubmit return the existing capture rather than a
    # duplicate, so retrying a transient 429/5xx is safe.
    body = urlencode({"url": url, "skip_first_archive": "1",
                      "if_not_archived_within": "30d"}).encode("ascii")
    req = urllib.request.Request(_SPN_SAVE_URL, data=body, headers=headers)
    submit = None
    delay = base_delay
    for attempt in range(4):
        _sleep(base_delay)
        try:
            with opener.open(req, timeout=60) as resp:
                submit = json.loads(resp.read().decode("utf-8", "replace"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < 4:
                wait = min(_retry_after_seconds(exc.headers.get("Retry-After")) or delay,
                           _RETRY_AFTER_CAP)
                log("  SPN2 submit HTTP %d; backing off %.0fs" % (exc.code, wait))
                _sleep(wait)
                delay *= 2
                continue
            log("  SPN2 submit HTTP %d (%s)" % (exc.code, "auth" if exc.code in (401, 403)
                                                else "giving up"))
            return None
        except (urllib.error.URLError, ValueError, OSError) as exc:
            if attempt + 1 < 4:
                log("  SPN2 submit error (%s); retrying" % exc)
                _sleep(delay)
                delay *= 2
                continue
            return None
    if not isinstance(submit, dict):
        log("  SPN2 submit: unexpected (non-object) response")
        return None
    job_id = submit.get("job_id")
    if not job_id:
        log("  SPN2 no job_id: %s" % (submit.get("message") or submit))
        return None
    status_req = urllib.request.Request(_SPN_STATUS_URL + quote(str(job_id), safe=""),
                                        headers=headers)
    errors = 0
    for _ in range(poll_attempts):
        _sleep(base_delay)
        try:
            with opener.open(status_req, timeout=60) as resp:
                st = json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, ValueError, OSError) as exc:
            errors += 1
            log("  SPN2 status error (%s)" % exc)
            if errors >= 3:
                return None
            continue   # a transient status-fetch error should not abandon the capture
        if not isinstance(st, dict):
            log("  SPN2 status: unexpected (non-object) response")
            return None
        state = st.get("status")
        if state == "success":
            return _spn_memento_from_status(st)
        if state == "error":
            log("  SPN2 capture error: %s" % (st.get("message")
                                              or st.get("exception") or "unknown"))
            return None
        # else pending/processing -> keep polling
    log("  SPN2 still pending after %d polls; giving up" % poll_attempts)
    return None


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
    # Authenticated SPN2 (archive.org S3 keys) bypasses the anonymous datacenter 429. When
    # the keys are present it is the Save-Page-Now path; otherwise fall back to the anonymous
    # ia-save helper. Build stays unaffected either way (this is the offline tool).
    ia_access = os.environ.get("IA_S3_ACCESS_KEY")
    ia_secret = os.environ.get("IA_S3_SECRET_KEY")
    if save and ia_access and ia_secret:
        log("Save Page Now: authenticated SPN2 (archive.org S3 keys)")
    elif save:
        log("Save Page Now: anonymous ia-save (no IA_S3 keys; may be 429-limited)")
    for key, entry in csl.items():
        url = (entry.get("URL") or "").strip()
        if not url:
            continue   # DOI-only / linkless: nothing to archive
        host = (urlsplit(url).hostname or "").lower()
        if host == "web.archive.org" or host.endswith(".web.archive.org"):
            log("%s: bib url is already a Wayback memento; skipping" % key)
            continue
        cached_mem = cache.get(key, {}).get("memento")
        if cached_mem and _memento_matches(cached_mem, url):
            continue   # already resolved for the CURRENT url (re-query if the url changed)
        log("%s: %s" % (key, url))
        avail = _availability(url, opener=opener, base_delay=base_delay, log=log)
        avail_transient = avail is _LOOKUP_FAILED
        if avail_transient:
            # A transient Availability failure (429/5xx/network) normally leaves the key for a
            # re-run. But AUTHENTICATED SPN2 is a SEPARATE endpoint, not subject to the
            # Availability rate limit, so when it is configured still try to capture rather
            # than let the throttle block the one path that could succeed. Anonymous ia-save
            # shares the throttle, so for it (or without --save) keep skipping for a re-run.
            if not (save and ia_access and ia_secret):
                log("  availability lookup failed (transient); leaving unresolved for a re-run")
                continue   # never record no_memento for a failed lookup -- a re-run retries
            log("  availability lookup failed (transient); trying authenticated SPN2 anyway")
            avail = None   # fall through to the SPN2 capture path below
        mem = avail if (avail and _memento_matches(avail, url)) else None
        if not mem:
            if avail:
                log("  availability snapshot is of a different url; ignoring")
            if save:
                log("  Save Page Now ...")
                if ia_access and ia_secret:
                    spn = _save_page_now_auth(url, ia_access, ia_secret, opener=opener,
                                              base_delay=base_delay, log=log)
                else:
                    spn = _save_page_now(url, tor=tor, log=log)
                mem = spn if (spn and _memento_matches(spn, url)) else None
            else:
                mem = None
        if mem:
            cache[key] = {"memento": mem}
            log("  -> %s" % mem)
        elif avail_transient:
            # Availability was transient AND SPN2 did not return a matching memento (SPN2 can
            # fail transiently too: submit 429/5xx, still pending, network error). The miss is
            # UNCONFIRMED, so leave the key unresolved -- never a false no_memento that a
            # --save apply would then write OVER a real memento. A re-run retries both paths.
            log("  availability transient and SPN2 did not capture; leaving unresolved for a re-run")
            continue
        else:
            cache[key] = {"no_memento": "no Wayback snapshot available"}
            log("  -> no snapshot")
        _save_cache(cache_path, cache)
    return cache


# A top-level table header: a bare key, or a quoted key (a dotted citekey must be quoted so
# it is one table, not nested), with an optional trailing comment.
_HEADER_RE = re.compile(
    r'^\[\s*(?:"([^"\n]+)"|\'([^\'\n]+)\'|([^\[\]"\'#\s]+))\s*\](?:\s*#.*)?\s*$')
_ARCHIVE_LINE_RE = re.compile(r'^\s*archive\s*=')


def _header_key(line):
    """The table key of a `[key]` / `[ "quoted.key" ]` header (with an optional trailing
    comment), unquoted so a quoted/dotted citekey matches its cache key, or None."""
    m = _HEADER_RE.match(line)
    if not m:
        return None
    return m.group(1) or m.group(2) or m.group(3)


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
            hk = _header_key(line)
            if hk is not None:
                cur = hk
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


def _atomic_write(path, text):
    """Write text to a temp file in the same directory, fsync it, then os.replace it onto
    path -- so a crash mid-write leaves the original intact, never a truncated file."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".archive-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply(article_dir, *, cache_path, log):
    toml_path = os.path.join(article_dir, "source-quotes.toml")
    # Read + published verbatim like _load_sidecar: refuse a symlink (it could redirect the
    # write off the article dir).
    if os.path.islink(toml_path):
        raise generate.BuildError("archive: %s must not be a symlink" % toml_path)
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
    _atomic_write(toml_path, new_text)
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
