#!/usr/bin/python3 -Bsu
"""Mint per-article DOIs via Zenodo (https://zenodo.org).

Two phases, because the DOI must be embedded in the article BEFORE it is
published (Scholar reads citation_doi from the landing page):

  reserve  create a deposition, set its metadata, obtain the RESERVED DOI, and
           write it into the article's meta.toml (doi = "..."). Rebuild the site
           afterwards so citation_doi + the PDF carry the DOI.
  publish  upload the (rebuilt) PDF to that deposition and publish it, which
           activates the DOI.

Auth: ZENODO_TOKEN in the environment (or --token). --sandbox targets
sandbox.zenodo.org for dry runs. Deposition state is kept in <dir>/.zenodo.json.
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

from jmaker import generate

PROD = "https://zenodo.org"
SANDBOX = "https://sandbox.zenodo.org"

# journal-maker license id -> Zenodo license id
_LICENSE_MAP = {
    "CC-BY-4.0": "cc-by-4.0",
    "CC-BY-SA-4.0": "cc-by-sa-4.0",
    "CC0-1.0": "cc-zero",
}


class ZenodoError(Exception):
    pass


def build_metadata(m, journal, abstract):
    """Map article metadata to a Zenodo deposition metadata dict (pure)."""
    creators = []
    for author in m["authors"]:
        entry = {"name": author["name"]}
        if author.get("institution"):
            entry["affiliation"] = author["institution"]
        if author.get("orcid"):
            entry["orcid"] = author["orcid"]
        creators.append(entry)
    meta = {
        "title": m["title"],
        "upload_type": "publication",
        # A self-published preview is a technical report, not a journal article:
        # no journal_title / journal_issn / journal_pages (article-only fields).
        "publication_type": "report",
        "description": " ".join(abstract.split()),
        "creators": creators,
        "publication_date": m["date"],
        "access_right": "open",
        # Ask Zenodo to reserve a DOI in the deposit response; reserve() reads it
        # back from metadata.prereserve_doi.doi. Without this the reserved DOI is
        # not guaranteed to be present, and reserve() would fail after creating
        # the (now orphaned) deposition.
        "prereserve_doi": True,
    }
    lic = m.get("license", journal.get("license", ""))
    if lic:
        meta["license"] = _LICENSE_MAP.get(lic, lic.lower())
    if m.get("keywords"):
        meta["keywords"] = list(m["keywords"])
    return {"metadata": meta}


def _api(method, url, token, payload=None, raw=None, ctype=None):
    headers = {"Authorization": "Bearer %s" % token}
    data = None
    if raw is not None:
        data = raw
        headers["Content-Type"] = ctype or "application/octet-stream"
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        # url is an internally-built https Zenodo API endpoint (a SANDBOX/
        # production constant or a Zenodo bucket URL from its own response),
        # never a user- or file-scheme input -- so B310 does not apply. Bare
        # '# nosec' so the CI bandit (1.6.2) that ignores a per-test-id suffix
        # still honors it.
        with urllib.request.urlopen(req, timeout=120) as resp:  # nosec
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise ZenodoError("%s %s -> HTTP %s: %s"
                          % (method, url, exc.code, exc.read().decode("utf-8", "replace")))
    except urllib.error.URLError as exc:
        raise ZenodoError("%s %s -> %s" % (method, url, exc))
    return json.loads(body) if body else {}


def _token(explicit):
    tok = explicit or os.environ.get("ZENODO_TOKEN")
    if not tok:
        raise ZenodoError("ZENODO_TOKEN not set (or pass --token)")
    return tok


def _state_path(article_dir):
    return os.path.join(article_dir, ".zenodo.json")


def _write_doi_to_meta(article_dir, doi):
    path = os.path.join(article_dir, "meta.toml")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    # Replace an existing top-level doi (single- or double-quoted) in place.
    new, n = re.subn(r'(?m)^doi\s*=\s*([\'"]).*?\1\s*$', 'doi = "%s"' % doi, text)
    if n == 0:
        # Insert as a TOP-LEVEL key BEFORE the first table header, so it cannot
        # land inside a trailing [table] / [[array]] (which EOF-append would do).
        insert = 'doi = "%s"\n' % doi
        mo = re.search(r'(?m)^\s*\[', text)
        new = (text[:mo.start()] + insert + text[mo.start():] if mo
               else text.rstrip("\n") + "\n" + insert)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)


def reserve(article_dir, journal_toml, base, token, replace=False):
    state_file = _state_path(article_dir)
    if os.path.islink(state_file):
        raise ZenodoError(".zenodo.json is a symlink; refusing to overwrite it")
    # A second reserve creates a NEW deposition and overwrites the DOI +
    # .zenodo.json, orphaning the first deposition and its reserved DOI. Refuse
    # unless the operator explicitly asks to replace it.
    if os.path.exists(state_file) and not replace:
        raise ZenodoError(
            "%s already records a reservation; a second reserve would orphan the "
            "first deposition and overwrite its DOI. Pass --replace to reserve "
            "again intentionally." % state_file)
    journal = generate.load_journal(journal_toml)
    m = generate.load_article(article_dir)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(m["date"])):
        raise ZenodoError("Zenodo requires a full YYYY-MM-DD date; meta.toml has %r"
                          % m["date"])
    dep = _api("POST", "%s/api/deposit/depositions" % base, token, payload={})
    dep_id = dep["id"]
    bucket = dep["links"]["bucket"]
    meta = build_metadata(m, journal, m["abstract"])
    updated = _api("PUT", "%s/api/deposit/depositions/%d" % (base, dep_id),
                   token, payload=meta)
    doi = updated.get("metadata", {}).get("prereserve_doi", {}).get("doi", "")
    if not doi:
        raise ZenodoError("no reserved DOI in response for deposition %d" % dep_id)
    _write_doi_to_meta(article_dir, doi)
    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump({"deposition_id": dep_id, "bucket": bucket, "doi": doi,
                   "base": base}, fh, indent=2)
    print("reserved DOI %s (deposition %d); wrote meta.toml -- rebuild, then "
          "'zenodo publish'" % (doi, dep_id))
    return 0


_ZENODO_HOST_RE = re.compile(r"https://(sandbox\.)?zenodo\.org(/|$)")


def _pdf_text(pdf_path):
    """Extract a PDF's text layer (poppler-utils is a hard dependency)."""
    try:
        r = subprocess.run(["pdftotext", "-q", pdf_path, "-"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        # SubprocessError covers TimeoutExpired (a hung pdftotext); it is NOT an
        # OSError, so it must be named explicitly or it escapes as a traceback.
        raise ZenodoError("pdftotext failed on %s: %s" % (pdf_path, exc))
    # Fail closed: a nonzero exit means the extraction is incomplete, so partial
    # output must not be trusted to decide an irreversible publish.
    if r.returncode != 0:
        raise ZenodoError("pdftotext exited %d on %s: %s"
                          % (r.returncode, pdf_path, r.stderr.strip()))
    return r.stdout


def publish(article_dir, pdf_path, base, token):
    if not pdf_path:
        raise ZenodoError("--pdf is required for the publish action")
    state_file = _state_path(article_dir)
    if os.path.islink(state_file):
        raise ZenodoError(".zenodo.json is a symlink; refusing to read it")
    if not os.path.isfile(state_file):
        raise ZenodoError("no .zenodo.json; run 'zenodo reserve' first")
    with open(state_file, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    # The deposition is tied to the environment it was reserved in; a --sandbox
    # publish of a production deposition (or vice versa) would wrongly target the
    # other service, so refuse the mismatch.
    if state.get("base") != base:
        raise ZenodoError("deposition reserved on %r but this run targets %r "
                          "(check --sandbox)" % (state.get("base"), base))
    # Never send the bearer token to a non-Zenodo URL stored in state.
    for url in (state.get("base", ""), state.get("bucket", "")):
        if not _ZENODO_HOST_RE.match(url):
            raise ZenodoError("refusing to send the token to a non-Zenodo URL: %r"
                              % url)
    if not os.path.isfile(pdf_path):
        raise ZenodoError("PDF not found: %s" % pdf_path)
    # Publishing is irreversible (Zenodo cannot delete a published deposition),
    # so confirm this PDF is THIS article's camera-ready build: generate embeds
    # "DOI: <doi>" in the PDF, so the reserved DOI must appear in its text layer.
    # Guards against publishing the wrong article's PDF under this DOI.
    doi = state.get("doi", "")
    if not doi:
        raise ZenodoError("no reserved DOI in .zenodo.json; re-run 'zenodo reserve'")
    # Whole-token match so a reserved DOI (e.g. ...zenodo.123) is not satisfied by
    # a different one that merely contains it (...zenodo.1234).
    if not re.search(r"(?<![\w.])%s(?![\w.])" % re.escape(doi), _pdf_text(pdf_path)):
        raise ZenodoError(
            "%s does not contain the reserved DOI %s; refusing to publish a PDF "
            "that is not this article's camera-ready build (rebuild the site "
            "after 'reserve', then publish that PDF)" % (pdf_path, doi))
    with open(pdf_path, "rb") as fh:
        pdf = fh.read()
    name = os.path.basename(pdf_path)
    _api("PUT", "%s/%s" % (state["bucket"], name), token, raw=pdf,
         ctype="application/pdf")
    rec = _api("POST", "%s/api/deposit/depositions/%d/actions/publish"
               % (state["base"], state["deposition_id"]), token)
    doi = rec.get("doi") or state.get("doi", "")
    print("published; DOI %s" % doi)
    return 0


def main(args):
    base = SANDBOX if args.sandbox else PROD
    try:
        token = _token(args.token)
        if args.action == "reserve":
            return reserve(args.article_dir, args.journal, base, token,
                           replace=args.replace)
        return publish(args.article_dir, args.pdf, base, token)
    except ZenodoError as exc:
        print("zenodo error: %s" % exc, file=sys.stderr)
        return 1
