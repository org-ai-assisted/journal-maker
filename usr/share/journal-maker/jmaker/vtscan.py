#!/usr/bin/python3 -Bsu
"""Pre-publish VirusTotal gate: scan EVERY built asset before publishing.

Supply-chain policy: no asset ships unscanned. For each file under the site:
  - compute sha256,
  - query VirusTotal via the client (default vtai.py) hash-first; upload when
    unknown and upload is allowed,
  - record detections, permalink, scan date.
Writes vt-results.json (machine) and VT-CHECKLIST.md (human) into the site.
FAILS (non-zero) on any detection, any client error, or a missing client -- an
unscanned asset is a FAILURE, never a silent pass.

The client is expected to accept a path and emit JSON on stdout. Parsing is
defensive about field names (malicious/detections, permalink/link, scan_date).
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

# Never-meaningful-to-scan published files. EVERYTHING else under the site is
# scanned -- no extension allowlist (an .exe/.php/.dotfile must not slip the gate).
_SKIP_NAMES = {".nojekyll", "vt-results.json", "VT-CHECKLIST.md"}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _assets(site):
    out = []
    for root, _dirs, files in os.walk(site):
        for name in files:
            if name in _SKIP_NAMES:
                continue
            out.append(os.path.join(root, name))
    return sorted(out)


def _query(client, path, upload):
    """Run the VT client on one file; return a parsed dict or raise.

    A detection count MUST be present and numeric; a client that exits 0 with no
    verdict (e.g. '{}' or '{"status":"queued"}') is an ERROR, never a clean pass.
    """
    cmd = [client]
    if upload:
        cmd.append("--upload")
    cmd.append(path)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("client rc=%d: %s" % (r.returncode,
                           (r.stderr or r.stdout).strip()))
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("client did not emit JSON: %s" % r.stdout[:200])
    det = None
    for key in ("malicious", "detections", "positives"):
        val = data.get(key)
        if isinstance(val, bool):  # bool is not a detection count
            continue
        if isinstance(val, int):
            det = val
            break
    if det is None:
        raise RuntimeError("client gave no numeric detection count: %s"
                           % r.stdout[:200])
    return {
        "detections": det,
        "permalink": data.get("permalink") or data.get("link", ""),
        "scan_date": data.get("scan_date") or data.get("date", ""),
        "raw": data,
    }


def main(site, client="vtai.py", out=None, upload=True):
    if not os.path.isdir(site):
        print("vtscan: no such site dir: %s" % site, file=sys.stderr)
        return 2
    if shutil.which(client) is None:
        if os.path.isfile(client):
            # A client given as a path (e.g. ./vtai.py) must be run by absolute
            # path; subprocess/execvp searches PATH only and would miss it.
            client = os.path.abspath(client)
        else:
            # absence is a FAILURE, not a skip
            print("vtscan: VirusTotal client not found: %s "
                  "(required by supply-chain policy)" % client, file=sys.stderr)
            return 2

    # Write reports OUTSIDE the site tree, so the published journal never ships
    # an asset inventory (paths, sizes, sha256, VT permalinks).
    reports_dir = os.path.dirname(os.path.abspath(site.rstrip("/")))
    out = out or os.path.join(reports_dir, "vt-results.json")
    checklist = os.path.join(os.path.dirname(os.path.abspath(out)),
                             "VT-CHECKLIST.md")
    results = []
    failures = 0
    for path in _assets(site):
        sha = _sha256(path)
        rel = os.path.relpath(path, site)
        entry = {"path": rel, "sha256": sha,
                 "size": os.path.getsize(path)}
        try:
            q = _query(client, path, upload)
            entry.update(detections=q["detections"], permalink=q["permalink"],
                         scan_date=q["scan_date"], status="scanned")
            if q["detections"] > 0:
                entry["status"] = "DETECTED"
                failures += 1
        except Exception as exc:  # client/parse error == failure
            entry.update(detections=None, status="ERROR", error=str(exc))
            failures += 1
        results.append(entry)

    report = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "site": os.path.abspath(site),
        "asset_count": len(results),
        "failures": failures,
        "assets": results,
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    _write_checklist(report, checklist)

    for e in results:
        mark = "ok" if e["status"] == "scanned" else e["status"]
        print("%-7s %4s  %s" % (mark, e.get("detections"), e["path"]))
    print("vtscan: %d asset(s), %d failure(s); results -> %s"
          % (len(results), failures, out))
    return 1 if failures else 0


def _write_checklist(report, path):
    lines = [
        "# VirusTotal pre-publish checklist",
        "",
        "Generated: %s" % report["generated"],
        "",
        "Every published asset must be scanned with zero detections before",
        "this site is published (supply-chain policy).",
        "",
        "| Asset | Size | Detections | Status | Permalink |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for e in report["assets"]:
        lines.append("| %s | %d | %s | %s | %s |" % (
            e["path"], e["size"],
            "-" if e.get("detections") is None else e["detections"],
            e["status"], e.get("permalink", "") or "-"))
    verdict = "PASS" if report["failures"] == 0 else "FAIL"
    lines += ["", "Result: **%s** (%d failure(s))" % (verdict, report["failures"]),
              ""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
