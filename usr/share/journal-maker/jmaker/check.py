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
Flags the executable/exfiltration primitives (/JavaScript /JS /Launch
/EmbeddedFile /RichMedia /XFA /SubmitForm /ImportData /GoToR) by scanning the PDF
STRUCTURE via `qpdf --json` -- not stream content, so prose mentioning a token
does not false-positive and hex-encoded names are normalized. qpdf is required;
its absence is an ERROR (cannot verify), never a silent pass.
"""

import os
import re
import shutil
import subprocess
import sys

MAX_PDF_BYTES = 5 * 1024 * 1024
# A floor just high enough to prove text is extractable (not a scanned image),
# without rejecting a legitimately short note.
MIN_PDF_TEXT_CHARS = 20

# Executable / exfiltration primitives -- the real supply-chain risk. NOT
# included: /OpenAction and /AA, which are benign action TRIGGERS (hyperref
# emits an /OpenAction "fit page" view in every LaTeX PDF); they are dangerous
# only when they invoke one of these, which is then caught here independently.
ACTIVE_TOKENS = [
    b"/JavaScript", b"/JS", b"/Launch",
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
# Code/preformatted spans legitimately contain [[ ]] (bash tests, C++ attrs)
# and {{ }} (CI expressions, templating) -- strip them before the wiki scan.
_CODE_RE = re.compile(r'<(pre|code)\b[^>]*>.*?</\1>', re.I | re.S)
_DATE_RE = re.compile(r'^\d{4}(/\d{1,2}(/\d{1,2})?)?$')


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


def _valid_date(s):
    """Scholar YYYY, YYYY/MM, or YYYY/MM/DD with in-range month/day."""
    if not _DATE_RE.match(s):
        return False
    parts = s.split("/")
    if len(parts) >= 2 and not 1 <= int(parts[1]) <= 12:
        return False
    if len(parts) == 3 and not 1 <= int(parts[2]) <= 31:
        return False
    return True


def _unescape(s):
    return (s.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'").replace("&middot;", ".")
             .replace("&amp;", "&"))


def _text_only(htmlfrag):
    return re.sub(r"\s+", " ", _unescape(_TAG_RE.sub(" ", htmlfrag))).strip()


def _collect_meta(page):
    out: dict = {"citation_author": []}
    for name, content in _META_RE.findall(page):
        name = name.lower()
        if name == "citation_author":
            out["citation_author"].append(_unescape(content))
        else:
            out[name] = _unescape(content)
    return out


def _dirname_url(u):
    return u.rsplit("/", 1)[0] if "/" in u else u


def check_article(page_path, f, out_dir):
    with open(page_path, "r", encoding="utf-8") as fh:
        page = fh.read()
    meta = _collect_meta(page)

    title = meta.get("citation_title")
    if not title:
        f.err(page_path, "missing citation_title")
    authors = [a for a in meta.get("citation_author", []) if a.strip()]
    if not authors:
        f.err(page_path, "missing citation_author (>=1 non-empty required)")
    pub = meta.get("citation_publication_date")
    if not pub:
        f.err(page_path, "missing citation_publication_date")
    elif not _valid_date(pub):
        f.err(page_path, "citation_publication_date not valid YYYY/MM/DD: %r" % pub)
    pdf_url = meta.get("citation_pdf_url")
    if not pdf_url:
        f.err(page_path, "missing citation_pdf_url")
    elif not re.match(r"^https?://", pdf_url):
        f.err(page_path, "citation_pdf_url must be absolute http(s): %r" % pdf_url)

    # title consistency (collapse whitespace on BOTH sides)
    h1 = _H1_RE.search(page)
    if not h1:
        f.err(page_path, "no visible <h1 class=title>")
    elif title and _text_only(h1.group(1)) != _text_only(title):
        f.err(page_path, "citation_title != visible <h1> (%r vs %r)"
              % (title, _text_only(h1.group(1))))

    # abstract visible and non-trivial (entities, incl. &nbsp;, already decoded)
    ab = _ABSTRACT_RE.search(page)
    if not ab or len(_text_only(ab.group(1))) < 20:
        f.err(page_path, "abstract not visible / too short on the page")

    # The PDF URL must point at this article's REAL on-disk location, and exist.
    # Tying the URL to the file's path under out_dir defeats a mislocated or
    # off-origin citation_pdf_url and an encoded-traversal basename.
    if pdf_url:
        rel = os.path.relpath(os.path.dirname(page_path), out_dir).replace(os.sep, "/")
        name = pdf_url.rsplit("/", 1)[-1]
        if not pdf_url.endswith("/%s/%s" % (rel, name)):
            f.err(page_path, "citation_pdf_url %r not at the article's location "
                  "(expected .../%s/<file>.pdf)" % (pdf_url, rel))
        landing = meta.get("citation_abstract_html_url", "")
        if landing and not landing.rstrip("/").endswith("/%s" % rel):
            f.err(page_path, "citation_abstract_html_url %r not at the article's "
                  "location" % landing)
        if "/" in name or ".." in name or "%" in name:
            f.err(page_path, "citation_pdf_url basename unsafe: %r" % name)
        else:
            pdf_local = os.path.join(os.path.dirname(page_path), name)
            if not os.path.isfile(pdf_local):
                f.err(page_path, "citation_pdf_url file missing: %s" % pdf_local)
            else:
                check_pdf(pdf_local, f)

    # no leftover wiki markup in the rendered body (ignoring code/pre spans)
    body_text = _text_only(_CODE_RE.sub(" ", page))
    if _WIKI_LINK_RE.search(body_text):
        f.err(page_path, "leftover wiki internal link [[...]] in output")
    if _WIKI_TMPL_RE.search(body_text):
        f.err(page_path, "leftover wiki template {{...}} in output")


def check_pdf(path, f):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(1024)
    if b"%PDF-" not in head:
        f.err(path, "not a valid PDF (no %PDF header in first 1KB)")
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

    # supply-chain: no active content. Scan the STRUCTURE (qpdf --json), not
    # stream content, so article prose mentioning a token does not false-positive
    # and hex-encoded names are normalized. qpdf absence is an ERROR, not a pass.
    qpdf = shutil.which("qpdf")
    if not qpdf:
        f.err(path, "qpdf absent; cannot verify PDF active content")
        return
    try:
        r = subprocess.run([qpdf, "--json=latest", path], capture_output=True)
    except Exception as exc:
        f.err(path, "qpdf failed: %s" % exc)
        return
    if r.returncode not in (0, 3):  # 3 == warnings only
        f.err(path, "qpdf could not parse PDF (rc=%d)" % r.returncode)
        return
    hits = sorted({t.decode() for t in ACTIVE_TOKENS if t in r.stdout})
    if hits:
        f.err(path, "active content in PDF: %s" % ", ".join(hits))


def check_site(out_dir):
    f = Findings()
    if not os.path.isfile(os.path.join(out_dir, "index.html")):
        f.err(out_dir, "missing homepage index.html")
    if not os.path.isfile(os.path.join(out_dir, "robots.txt")):
        f.err(out_dir, "missing robots.txt")
    sitemap = os.path.join(out_dir, "sitemap.xml")
    if not os.path.isfile(sitemap):
        f.err(out_dir, "missing sitemap.xml")
    else:
        with open(sitemap, "r", encoding="utf-8") as fh:
            if "<loc>" not in fh.read():
                f.err(sitemap, "sitemap.xml lists no URLs")

    found = 0
    for root, _dirs, files in os.walk(out_dir):
        if "index.html" in files and re.search(r"/v\d+/i\d+/[^/]+$", root):
            found += 1
            check_article(os.path.join(root, "index.html"), f, out_dir)
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
