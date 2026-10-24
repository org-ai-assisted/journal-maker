#!/usr/bin/python3 -Bsu
"""Gate a built journal site: Google Scholar compliance + PDF sanity + PDF
supply-chain security. Any ERROR fails the build (exit non-zero).

Scholar invariants (scholar.google.com/intl/en/scholar/inclusion.html):
  - required meta: citation_title, >=1 citation_author, citation_publication_date,
    citation_pdf_url (missing any one makes Scholar discard ALL meta tags).
  - citation_pdf_url must be absolute and in the SAME directory as the landing
    page; the file must exist.
  - the abstract must be visible on the page, not only in meta.
  - citation_title must match the visible title.
  - no leftover wiki markup ([[...]] / {{...}}) may ship.

PDF sanity: valid %PDF header, <= 5 MB, extractable (searchable) text.

PDF security (supply-chain policy): a generated PDF must carry NO active content.
Flags /JavaScript /JS /OpenAction /AA /Launch /EmbeddedFile /RichMedia /XFA
/SubmitForm /ImportData /GoToR. Detection normalizes object streams with qpdf
when available (so compressed dictionary keys are exposed); without qpdf it is a
best-effort raw scan and says so.
"""

import os
import re
import shutil
import subprocess
import sys

MAX_PDF_BYTES = 5 * 1024 * 1024
MIN_PDF_TEXT_CHARS = 500

ACTIVE_TOKENS = [
    b"/JavaScript", b"/JS", b"/OpenAction", b"/AA", b"/Launch",
    b"/EmbeddedFile", b"/RichMedia", b"/XFA", b"/SubmitForm",
    b"/ImportData", b"/GoToR",
]

_META_RE = re.compile(
    r'<meta\s+name="(citation_[a-z_]+)"\s+content="(.*?)">', re.I | re.S)
_H1_RE = re.compile(r'<h1[^>]*class="title"[^>]*>(.*?)</h1>', re.I | re.S)
_ABSTRACT_RE = re.compile(
    r'<section[^>]*class="abstract"[^>]*>(.*?)</section>', re.I | re.S)
_WIKI_LINK_RE = re.compile(r'\[\[[^\]]+\]\]')
_WIKI_TMPL_RE = re.compile(r'\{\{[^}]+\}\}')
_TAG_RE = re.compile(r'<[^>]+>')


class Findings:
    def __init__(self):
        self.items = []

    def err(self, path, msg):
        self.items.append(("ERROR", path, msg))

    def warn(self, path, msg):
        self.items.append(("WARN", path, msg))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "ERROR"]


def _unescape(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'").replace("&middot;", "."))


def _text_only(htmlfrag):
    return re.sub(r"\s+", " ", _unescape(_TAG_RE.sub(" ", htmlfrag))).strip()


def _collect_meta(page):
    out = {"citation_author": []}
    for name, content in _META_RE.findall(page):
        name = name.lower()
        if name == "citation_author":
            out["citation_author"].append(_unescape(content))
        else:
            out[name] = _unescape(content)
    return out


def _dirname_url(u):
    return u.rsplit("/", 1)[0] if "/" in u else u


def check_article(page_path, f):
    with open(page_path, "r", encoding="utf-8") as fh:
        page = fh.read()
    meta = _collect_meta(page)

    if not meta.get("citation_title"):
        f.err(page_path, "missing citation_title")
    if not meta.get("citation_author"):
        f.err(page_path, "missing citation_author (>=1 required)")
    if not meta.get("citation_publication_date"):
        f.err(page_path, "missing citation_publication_date")
    pdf_url = meta.get("citation_pdf_url")
    if not pdf_url:
        f.err(page_path, "missing citation_pdf_url")

    # title consistency
    h1 = _H1_RE.search(page)
    if not h1:
        f.err(page_path, "no visible <h1 class=title>")
    elif meta.get("citation_title") and \
            _text_only(h1.group(1)) != meta["citation_title"].strip():
        f.err(page_path, "citation_title != visible <h1> (%r vs %r)"
              % (meta["citation_title"], _text_only(h1.group(1))))

    # abstract visible and substantial
    ab = _ABSTRACT_RE.search(page)
    if not ab or len(_text_only(ab.group(1))) < 80:
        f.err(page_path, "abstract not visible / too short on the page")

    # same-directory PDF rule + file exists
    if pdf_url:
        landing = meta.get("citation_abstract_html_url", "")
        if landing and _dirname_url(pdf_url) != _dirname_url(landing):
            f.err(page_path, "citation_pdf_url not in landing-page directory")
        pdf_local = os.path.join(os.path.dirname(page_path),
                                 pdf_url.rsplit("/", 1)[-1])
        if not os.path.isfile(pdf_local):
            f.err(page_path, "citation_pdf_url file missing: %s" % pdf_local)
        else:
            check_pdf(pdf_local, f)

    # no leftover wiki markup in the rendered body
    body_text = _text_only(page)
    if _WIKI_LINK_RE.search(body_text):
        f.err(page_path, "leftover wiki internal link [[...]] in output")
    if _WIKI_TMPL_RE.search(body_text):
        f.err(page_path, "leftover wiki template {{...}} in output")


def _normalized_pdf_bytes(path):
    """Expose compressed dictionary keys via qpdf if present; else raw bytes."""
    qpdf = shutil.which("qpdf")
    if qpdf:
        try:
            r = subprocess.run(
                [qpdf, "--qdf", "--object-streams=disable",
                 "--decode-level=all", path, "-"],
                capture_output=True)
            if r.returncode in (0, 3):  # 3 == warnings only
                return r.stdout, True
        except Exception:
            pass
    with open(path, "rb") as fh:
        return fh.read(), False


def check_pdf(path, f):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(5)
    if head != b"%PDF-":
        f.err(path, "not a valid PDF (bad %PDF header)")
        return
    if size > MAX_PDF_BYTES:
        f.err(path, "PDF too large: %d bytes (> %d)" % (size, MAX_PDF_BYTES))

    # searchable text
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-q", path, "-"],
                           capture_output=True, text=True)
        if len(r.stdout.strip()) < MIN_PDF_TEXT_CHARS:
            f.err(path, "PDF has little/no extractable text (not searchable?)")
    else:
        f.warn(path, "pdftotext absent; cannot verify searchable text")

    # supply-chain: no active content
    data, normalized = _normalized_pdf_bytes(path)
    hits = sorted({t.decode() for t in ACTIVE_TOKENS if t in data})
    if hits:
        f.err(path, "active content in PDF: %s" % ", ".join(hits))
    elif not normalized:
        f.warn(path, "qpdf absent; active-content scan was raw/best-effort")


def check_site(out_dir):
    f = Findings()
    if not os.path.isfile(os.path.join(out_dir, "index.html")):
        f.err(out_dir, "missing homepage index.html")
    if not os.path.isfile(os.path.join(out_dir, "robots.txt")):
        f.err(out_dir, "missing robots.txt")
    if not os.path.isfile(os.path.join(out_dir, "sitemap.xml")):
        f.err(out_dir, "missing sitemap.xml")

    found = 0
    for root, _dirs, files in os.walk(out_dir):
        if "index.html" in files and re.search(r"/v\d+/i\d+/[^/]+$", root):
            found += 1
            check_article(os.path.join(root, "index.html"), f)
    if found == 0:
        f.err(out_dir, "no article landing pages found")
    return f, found


def main(argv):
    if not argv:
        print("usage: check <site-dir>", file=sys.stderr)
        return 2
    out_dir = argv[0]
    f, n = check_site(out_dir)
    for level, path, msg in f.items:
        print("%s: %s: %s" % (level, os.path.relpath(path, out_dir), msg))
    errs = len(f.errors)
    print("checked %d article(s); %d error(s), %d warning(s)"
          % (n, errs, len(f.items) - errs))
    return 1 if errs else 0
