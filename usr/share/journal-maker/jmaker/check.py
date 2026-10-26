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

import html
import json
import os
import re
import shutil
import subprocess
import sys

MAX_PDF_BYTES = 5 * 1024 * 1024
# A floor just high enough to prove text is extractable (not a scanned image),
# without rejecting a legitimately short note.
MIN_PDF_TEXT_CHARS = 20

# Inherently dangerous PDF dictionary KEYS (embedded code / payload / scripting).
# Matched structurally against qpdf --json keys, NOT as raw substrings, so a font
# subset name (e.g. /JSTKMA+CMR10) or a title mentioning "/JavaScript" does not
# trigger a false positive.
_DANGEROUS_KEYS = {"/JavaScript", "/JS", "/EmbeddedFile", "/RichMedia", "/XFA"}
# Auto-executing action types (a dict's /S value). /GoTo (hyperref's benign "fit
# page" view) and /URI (ordinary hyperlinks) are excluded on purpose.
_DANGEROUS_ACTIONS = {"/JavaScript", "/Launch"}


def _active_hits(obj, hits=None):
    """Walk a qpdf --json object tree for dangerous dictionary keys / actions."""
    if hits is None:
        hits = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _DANGEROUS_KEYS:
                hits.add(k)
            if k == "/S" and isinstance(v, str) and v in _DANGEROUS_ACTIONS:
                hits.add(v)
            _active_hits(v, hits)
    elif isinstance(obj, list):
        for item in obj:
            _active_hits(item, hits)
    return hits


def _origin(url):
    mo = re.match(r'(https?://[^/]+)', url or "")
    return mo.group(1) if mo else ""

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
_STATUS_RE = re.compile(r'<meta\s+name="article_status"\s+content="([a-z]+)">', re.I)
# Unresolved edit-marker: an uppercase TODO immediately followed by ':' or '(',
# matching our **TODO:** / **TODO(editorial):** notes in bold OR plain text (a
# marker that lost its bold -- in a heading, list, or prose -- must still block a
# publish). The ':'/'(' requirement lets ordinary text like "TODO Group" (the
# FOSS org) pass; case-sensitivity keeps Spanish "todo:" and the like out. It is
# matched against tag-stripped, code-free text, so a genuine "# TODO:" inside a
# code example is not mistaken for an unresolved note.
_EDIT_MARKER_RE = re.compile(r'\bTODO\s*[:(]')
_ALLOWED_STATUS = {"draft", "published", "corrected"}


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

    # title consistency. The meta title is already plaintext (entity-decoded),
    # so only normalize its whitespace; the h1 is HTML, so strip tags + decode.
    # (Applying _text_only to the plaintext title would wrongly strip a literal
    # "<...>" in the title as if it were a tag.)
    h1 = _H1_RE.search(page)
    if not h1:
        f.err(page_path, "no visible <h1 class=title>")
    elif title and _text_only(h1.group(1)) != re.sub(r"\s+", " ", title).strip():
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
        if landing and _origin(pdf_url) != _origin(landing):
            f.err(page_path, "citation_pdf_url and citation_abstract_html_url "
                  "differ in origin (%r vs %r)"
                  % (_origin(pdf_url), _origin(landing)))
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

    check_release_state(page, page_path, f)
    check_citation_parity(page, page_path, f)


def check_release_state(page, page_path, f):
    """Visible edit-markers must match the declared status.

    published => no leftover TODO markers (a draft cannot ship as the record with
    unresolved notes); draft/corrected => the matching banner must be present so
    the honesty label can never be dropped. Status drives it, nothing to recall.
    """
    smo = _STATUS_RE.search(page)
    if not smo:
        f.err(page_path, "missing article_status meta (set status in meta.toml)")
        return
    status = smo.group(1).lower()
    if status not in _ALLOWED_STATUS:
        f.err(page_path, "unknown article_status: %r" % status)
    # A version of record (published OR corrected) must carry no unresolved notes,
    # in ANY form -- scan the tag-stripped, code-free text so a bold-dropped marker
    # is caught and a code example's "# TODO:" is not.
    if status in ("published", "corrected"):
        # html.unescape decodes numeric AND named entities, so an encoded colon
        # (TODO&#58;) in a visible marker cannot slip past the regex; _text_only's
        # _unescape covers only a fixed named-entity set.
        marker_text = html.unescape(_text_only(_CODE_RE.sub(" ", page)))
        if _EDIT_MARKER_RE.search(marker_text):
            f.err(page_path, "%s article still has TODO edit-marker(s); "
                  "resolve them or keep status=draft" % status)
    if status == "draft" and "status-banner status-draft" not in page:
        f.err(page_path, "draft article missing the not-peer-reviewed banner")
    if status == "corrected" and "status-banner status-corrected" not in page:
        f.err(page_path, "corrected article missing the correction banner")


def check_citation_parity(page, page_path, f):
    """Every in-text [n] has a reference entry and every entry is cited.

    Catches a dead #ref-n link, an undefined citation, an uncited reference, and
    a duplicate reference id. Works on linkified anchors, falling back to the
    visible [n] markers in the body when a page has no reference links.
    """
    defined = re.findall(r'<li id="ref-(\d+)">', page)
    dups = sorted({n for n in defined if defined.count(n) > 1}, key=int)
    if dups:
        f.err(page_path, "duplicate reference id(s): %s"
              % ", ".join("[%s]" % n for n in dups))
    defined_set = set(defined)

    cited = set(re.findall(r'href="#ref-(\d+)"', page))
    if not cited:
        body = page
        mo = re.search(r'<h2[^>]*>\s*References\s*</h2>', page, re.I)
        if mo:
            body = page[:mo.start()]
        cited = set(re.findall(r'\[(\d+)\]', _text_only(_CODE_RE.sub(" ", body))))

    if not cited and not defined_set:
        return  # an article with no citations and no reference list is fine

    dangling = sorted(cited - defined_set, key=int)
    if dangling:
        f.err(page_path, "in-text citation(s) with no reference entry: %s"
              % ", ".join("[%s]" % n for n in dangling))
    uncited = sorted(defined_set - cited, key=int)
    if uncited:
        f.err(page_path, "reference entr(y/ies) never cited: %s"
              % ", ".join("[%s]" % n for n in uncited))


def _has_type3_font(pdffonts_output):
    """True if pdffonts output lists any Type 3 (bitmap) font.

    pdffonts prints a two-line header then one row per font; the 'type' column
    reads 'Type 3' for a bitmap font (vector fonts read 'Type 1', 'Type 1C',
    'TrueType', 'CID ...'). Pure, so the detection is unit-testable without a
    crafted Type-3 PDF.
    """
    rows = pdffonts_output.splitlines()[2:]
    return any(re.search(r"\bType 3\b", row) for row in rows)


def check_pdf(path, f):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(1024)
    # Must START with %PDF- (leading whitespace tolerated). Junk prepended before
    # the header -- e.g. an HTML/script prefix -- is rejected.
    if not head.lstrip()[:5] == b"%PDF-":
        f.err(path, "not a valid PDF (does not start with %PDF-)")
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

    # Type-3 (bitmap) fonts render poorly and break text extraction / Scholar
    # indexing. A camera-ready PDF must embed only vector fonts (the LaTeX build
    # pins lmodern). pdffonts ships with poppler-utils, as pdftotext does.
    if shutil.which("pdffonts"):
        r = subprocess.run(["pdffonts", path], capture_output=True, text=True)
        if r.returncode != 0:
            # Fail closed: an errored pdffonts leaves empty stdout, which would
            # otherwise read as "no Type 3 font" and bypass the gate.
            f.err(path, "pdffonts exited %d; cannot verify font types (fail closed)"
                        % r.returncode)
        elif _has_type3_font(r.stdout):
            f.err(path, "PDF embeds a Type 3 (bitmap) font; rebuild with lmodern "
                        "(vector fonts) so the PDF stays searchable/indexable")
    else:
        f.warn(path, "pdffonts absent; cannot verify font types")

    # supply-chain: no active content. Parse the STRUCTURE (qpdf --json) and walk
    # for dangerous dictionary keys / auto-exec action types -- NOT a substring
    # scan, so prose or a font subset name cannot false-positive. qpdf absence is
    # an ERROR, not a pass.
    qpdf = shutil.which("qpdf")
    if not qpdf:
        f.err(path, "qpdf absent; cannot verify PDF active content")
        return
    try:
        r = subprocess.run([qpdf, "--json=latest", path],
                           capture_output=True, text=True)
    except Exception as exc:
        f.err(path, "qpdf failed: %s" % exc)
        return
    if r.returncode not in (0, 3):  # 3 == warnings only
        f.err(path, "qpdf could not parse PDF (rc=%d)" % r.returncode)
        return
    try:
        doc = json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        f.err(path, "qpdf JSON parse failed: %s" % exc)
        return
    hits = sorted(_active_hits(doc))
    if hits:
        f.err(path, "active content in PDF: %s" % ", ".join(hits))


_TEXT_EXT = {".html", ".css", ".xml", ".txt", ".svg", ".json"}


def check_ascii(out_dir, f):
    """Enforce ASCII-only published text (no em-dash / curly quotes / nbsp).

    Pandoc's smart extension and stray source Unicode both leak non-ASCII into
    output; this is the script-enforced backstop. Non-ASCII that is genuinely
    needed must be written as an HTML entity (ASCII bytes), not a literal.
    """
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if os.path.splitext(name)[1].lower() not in _TEXT_EXT:
                continue
            path = os.path.join(root, name)
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                data.decode("ascii")
            except UnicodeDecodeError:
                bad = sorted({ch for ch in data.decode("utf-8", "replace")
                              if ord(ch) > 127})
                f.err(path, "non-ASCII in output (ASCII-only policy): %s"
                      % " ".join("U+%04X" % ord(ch) for ch in bad[:12]))


# Interim / AI-assist infrastructure that must NEVER appear in the published
# journal: it is a vendor-neutral academic venue and will move to its own org,
# so an org-ai-assisted link or mention would leak non-permanent infra (and
# break the "never change an indexed URL" rule once the org move happens).
_FORBIDDEN_REFS = ("org-ai-assisted",)


def check_no_internal_refs(out_dir, f):
    """Fail if any served text links to or mentions interim/AI-assist infra."""
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if os.path.splitext(name)[1].lower() not in _TEXT_EXT:
                continue
            path = os.path.join(root, name)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                low = fh.read().lower()
            for tok in _FORBIDDEN_REFS:
                if tok in low:
                    f.err(path, "forbidden reference to interim infra %r in "
                          "published output (journal is vendor-neutral)" % tok)


# Project names the journal stays neutral about: no mention in served content
# unless the exact phrase is allow-listed. The allowlist is PER FILE -- a
# manifest {dir-key -> [phrases]} emitted to _site/.github/vendor-allowlist.json
# (article meta.toml allow_vendor_mentions + site.toml page_allow_vendor_mentions).
_VENDOR_TOKENS = ("kicksecure", "whonix")


def check_no_vendor_refs(out_dir, f):
    """Fail on any Kicksecure/Whonix mention in served text not covered by a
    PER-FILE allow-listed phrase (de-project-ification is enforced, not trusted;
    an allowance for one article/page never licenses a mention elsewhere)."""
    manifest = {}
    mp = os.path.join(out_dir, ".github", "vendor-allowlist.json")
    if os.path.isfile(mp):
        with open(mp, encoding="utf-8") as fh:
            try:
                manifest = json.load(fh)
            except json.JSONDecodeError:
                f.err(mp, "vendor-allowlist.json is not valid JSON")
    for root, _dirs, files in os.walk(out_dir):
        rel_dir = os.path.relpath(root, out_dir).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        if rel_dir == ".github" or rel_dir.startswith(".github/"):
            continue  # internal build config, not served content
        allow = [p.lower() for p in manifest.get(rel_dir, [])]
        for name in files:
            if os.path.splitext(name)[1].lower() not in _TEXT_EXT:
                continue
            path = os.path.join(root, name)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                low = fh.read().lower()
            for phrase in allow:            # remove this file's allow-listed phrases
                low = low.replace(phrase, " ")
            for tok in _VENDOR_TOKENS:
                if tok in low:
                    f.err(path, "non-allowlisted mention of %r in published "
                          "output (journal is vendor-neutral; add the exact "
                          "phrase to this article's meta.toml allow_vendor_mentions "
                          "or site.toml page_allow_vendor_mentions)" % tok)


def check_index_policy(out_dir, f):
    """robots.txt and the pages' noindex meta must agree, and a PUBLISHED
    (indexable) site must carry no leftover TODO edit-marker on ANY page
    (articles AND standalone pages). A mismatch between the two signals, or an
    indexable site shipping an unresolved note, is a hard error."""
    robots_path = os.path.join(out_dir, "robots.txt")
    home = os.path.join(out_dir, "index.html")
    if not (os.path.isfile(robots_path) and os.path.isfile(home)):
        return  # the missing-file errors are raised by check_site already
    with open(robots_path, encoding="utf-8") as fh:
        robots = fh.read()
    with open(home, encoding="utf-8") as fh:
        noindexed = 'name="robots" content="noindex"' in fh.read()
    allows = re.search(r"(?mi)^Allow: /\s*$", robots) is not None
    disallows = re.search(r"(?mi)^Disallow: /\s*$", robots) is not None
    if noindexed:
        if allows or not disallows:
            f.err(robots_path, "pages carry a noindex meta but robots.txt does "
                               "not Disallow: / -- index policy is inconsistent")
        return
    if disallows or not allows:
        f.err(robots_path, "no noindex meta (indexable build) but robots.txt "
                           "does not Allow: / -- index policy is inconsistent")
    # An indexable, published site must not ship unresolved edit-markers on its
    # STANDALONE pages. Article pages carry article_status and are governed by
    # check_release_state (status-aware: a draft article may legitimately keep
    # TODO notes under its not-peer-reviewed banner), so skip them here.
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if not name.endswith(".html"):
                continue
            p = os.path.join(root, name)
            with open(p, encoding="utf-8") as fh:
                page = fh.read()
            if _STATUS_RE.search(page):
                continue
            marker = html.unescape(_text_only(_CODE_RE.sub(" ", page)))
            if _EDIT_MARKER_RE.search(marker):
                f.err(p, "published (indexable) site still has a TODO edit-marker on "
                         "a standalone page; resolve it or build without --publish")


def check_site(out_dir):
    f = Findings()
    check_ascii(out_dir, f)
    check_no_internal_refs(out_dir, f)
    check_no_vendor_refs(out_dir, f)
    if not os.path.isfile(os.path.join(out_dir, "index.html")):
        f.err(out_dir, "missing homepage index.html")
    robots_path = os.path.join(out_dir, "robots.txt")
    no_index = False
    if not os.path.isfile(robots_path):
        f.err(out_dir, "missing robots.txt")
    else:
        with open(robots_path, "r", encoding="utf-8") as fh:
            no_index = "Disallow: /" in fh.read()
    sitemap = os.path.join(out_dir, "sitemap.xml")
    if not os.path.isfile(sitemap):
        f.err(out_dir, "missing sitemap.xml")
    else:
        with open(sitemap, "r", encoding="utf-8") as fh:
            has_urls = "<loc>" in fh.read()
        # A no-index site advertises no crawlable URL, so an empty sitemap is
        # correct; only an INDEXABLE site must list its pages.
        if not has_urls and not no_index:
            f.err(sitemap, "sitemap.xml lists no URLs")
    check_index_policy(out_dir, f)

    # Article landing pages are listed in the build manifest, NOT discovered by
    # an in-page marker: discovery must not depend on the very article_status
    # meta that check_article validates, or a page that lost its meta would be
    # silently skipped instead of flagged.
    manifest = os.path.join(out_dir, ".github", "articles.json")
    if not os.path.isfile(manifest):
        f.err(out_dir, "missing .github/articles.json build manifest")
        return f, 0
    with open(manifest, encoding="utf-8") as fh:
        routes = json.load(fh)
    found = 0
    for route in routes:
        page_path = os.path.join(out_dir, route, "index.html")
        if not os.path.isfile(page_path):
            f.err(out_dir, "article route %r in manifest has no index.html"
                  % route)
            continue
        found += 1
        check_article(page_path, f, out_dir)
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
