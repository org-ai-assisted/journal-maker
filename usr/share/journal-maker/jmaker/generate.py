#!/usr/bin/python3 -Bsu
"""Build a static site of occasional research previews from Markdown.

Contract per article:
  articles/<slug>/paper.md   -- the paper in Markdown: the H1 ('# Title') and a
                                 '## Abstract' section are the SINGLE SOURCE for
                                 title + abstract; the body is everything from
                                 the first section heading after the abstract.
                                 (title/abstract are parsed here, NOT meta.toml.)
  articles/<slug>/meta.toml  -- the remaining bibliographic metadata (authors,
                                 dates, doi, keywords, license).
  articles/<slug>/source.mw  -- optional pristine wiki fork (ignored by build)
  articles/<slug>/figures/   -- optional images, copied verbatim

Output tree (served at the site root):
  index.html                 -- homepage (newest-first preview list)
  <slug>/index.html          -- article landing page == full HTML article + meta
  <slug>/<slug>.pdf          -- camera-ready PDF in the SAME directory
  assets/style.css, robots.txt, sitemap.xml, .nojekyll

PDF and HTML both derive from meta.toml + paper.md, so citation_title always
matches the visible title and the abstract is always both visible and in meta.
"""

import datetime
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import urlsplit


class BuildError(Exception):
    pass


# Posting-status model. Default is "draft" so a new piece is honestly labeled
# not-peer-reviewed until an author DELIBERATELY promotes it to "posted" -- that
# promotion is what turns on the release-state lint (no leftover TODO edit-markers).
# The safe state needs nothing remembered. These are our own previews, posted for
# public commentary: there is no review board and no peer review.
STATUS_LABELS = {
    "draft": "Draft -- not peer reviewed",
    "published": "Posted for comment -- not peer reviewed",
    "corrected": "Corrected -- see correction notice",
}
# Short badge text per status (keep it a state keyword, not a sentence).
_STATUS_PILL = {
    "draft": "Draft",
    "published": "Posted",
    "corrected": "Corrected",
}
# schema.org creativeWorkStatus value (corrected is still a published VoR).
_STATUS_SCHEMA = {"draft": "Draft", "published": "Published",
                  "corrected": "Published"}


# ---------------------------------------------------------------- loading

def load_journal(path):
    with open(path, "rb") as fh:
        j = tomllib.load(fh)
    for req in ("title", "base_url"):
        v = j.get(req)
        # Non-blank STRING, not just truthy: an unquoted TOML value (e.g. a bare
        # date) parses as a non-str and later crashes string/JSON contexts.
        if not isinstance(v, str) or not v.strip():
            raise BuildError("site.toml key must be a non-empty string: %s" % req)
    # base_url must be absolute (Scholar requires absolute citation_pdf_url) and
    # free of whitespace/newlines (it is interpolated into robots.txt + sitemap).
    if not re.fullmatch(r"https?://[^/\s]+(/[^\s]*)?", j["base_url"]):
        raise BuildError("site.toml: base_url must be an absolute http(s) URL "
                         "with a host and no whitespace, got %r" % j["base_url"])
    j["base_url"] = j["base_url"].rstrip("/")
    j.setdefault("issn", "")
    j.setdefault("language", "en")
    # publisher feeds the Scholar institution tag, RIS PB, Zenodo imprint and
    # JSON-LD, none of which may be blank; fall back to the required title for
    # any absent/blank/non-string value (so none ever ships bad metadata).
    pub = j.get("publisher")
    if not isinstance(pub, str) or not pub.strip():
        j["publisher"] = j["title"]
    j.setdefault("license", "")
    j.setdefault("license_url", "")
    # Optional "view markdown source" base: the repo blob root (e.g.
    # https://github.com/<owner>/<repo>/blob/master). When set, each article links
    # to .../articles/<slug>/paper.md and its sources page to source-quotes.md.
    # Must be absolute http(s) with no whitespace (interpolated into an href).
    sb = j.get("source_base_url", "")
    if not isinstance(sb, str):
        raise BuildError("site.toml: source_base_url must be a string")
    sb = sb.strip().rstrip("/")
    if sb and not re.fullmatch(r"https?://[^/\s]+(/[^\s]*)?", sb):
        raise BuildError("site.toml: source_base_url must be an absolute http(s) "
                         "URL with no whitespace, got %r" % j.get("source_base_url"))
    j["source_base_url"] = sb
    # Optional consistent footer navigation (same links/order on every page).
    j.setdefault("footer_links", [])
    if not isinstance(j["footer_links"], list):
        raise BuildError("site.toml: footer_links must be a list")
    for link in j["footer_links"]:
        if (not isinstance(link, dict)
                or not isinstance(link.get("title"), str)
                or not isinstance(link.get("href"), str)
                or not link["title"].strip() or not link["href"].strip()):
            raise BuildError("site.toml: each footer_link needs a non-empty "
                             "string title and href")
        h = link["href"]
        if "://" in h and not h.startswith(("http://", "https://")):
            raise BuildError("site.toml: footer_link href scheme not allowed: "
                             "%r" % h)
        if ".." in h or h.startswith("/"):
            raise BuildError("site.toml: footer_link href must be relative "
                             "(no leading / or ..) or absolute http(s): %r" % h)
    # Per-PAGE vendor-mention allowlist: slug -> exact phrases, applied ONLY to
    # that page's files. Articles carry their own allow_vendor_mentions in
    # meta.toml. There is no global allowlist -- an allowance is always scoped to
    # one file, so it can never license a mention elsewhere.
    pav = j.setdefault("page_allow_vendor_mentions", {})
    if not isinstance(pav, dict):
        raise BuildError("site.toml: page_allow_vendor_mentions must be a "
                         "table (slug -> list of phrases)")
    for slug, phrases in pav.items():
        if (not isinstance(phrases, list)
                or not all(isinstance(x, str) and x.strip() for x in phrases)):
            raise BuildError("site.toml: page_allow_vendor_mentions[%r] must "
                             "be a list of non-empty strings" % slug)
    return j


def _nonfence_lines(lines):
    """Yield (index, line) for lines OUTSIDE fenced code blocks.

    Fenced ``` / ~~~ delimiter lines are skipped too. This keeps a '# comment'
    or '## ...' inside a code sample from being mistaken for the title or the
    Abstract heading (common in a computer-security paper).
    """
    in_fence = False
    fence = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        tok = None
        if stripped.startswith("```"):
            tok = "```"
        elif stripped.startswith("~~~"):
            tok = "~~~"
        if tok is not None:
            if not in_fence:
                in_fence, fence = True, tok
            elif stripped.startswith(fence):
                in_fence, fence = False, None
            continue
        if not in_fence:
            yield i, line


def _parse_paper(md, adir):
    """paper.md is the single source for title + abstract + body.

    title   = first H1 ('# ...')       (ignoring fenced code)
    abstract= the '## Abstract' section body (until the next '## ')
    body    = everything from the first section heading after the abstract
    """
    lines = md.splitlines()
    nonfence = list(_nonfence_lines(lines))

    title = None
    for _i, line in nonfence:
        stripped = line.rstrip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            break
    if not title:
        raise BuildError("%s/paper.md: no H1 title (# ...) found" % adir)

    abs_pos = None
    for pos, (_i, line) in enumerate(nonfence):
        if re.match(r"^##\s+Abstract\s*$", line.strip(), re.I):
            abs_pos = pos
            break
    if abs_pos is None:
        raise BuildError("%s/paper.md: no '## Abstract' section found" % adir)

    buf = []
    body_start = None
    for _i, line in nonfence[abs_pos + 1:]:
        if line.lstrip().startswith("## "):
            body_start = _i
            break
        buf.append(line)
    abstract = "\n".join(buf).strip()
    if not abstract:
        raise BuildError("%s/paper.md: empty '## Abstract' section" % adir)
    if body_start is None:
        raise BuildError("%s/paper.md: no section after the abstract" % adir)

    body = "\n".join(lines[body_start:]).strip()
    if not body:
        raise BuildError("%s/paper.md: no body after the abstract" % adir)
    return title, abstract, body


# A bracketed group holding at least one @key, and the keys inside it. Matches
# the plain [@a] / [@a; @b] and pandoc's prefixed/locator forms [see @a] /
# [cf. @a, p. 3]. A bare "user@host" in prose is never in brackets, so it is not
# mistaken for a cite. Bare NARRATIVE "@a showed" (no brackets) is OUT of scope:
# it is off our [@key] convention (csr-rules), and matching it robustly means
# replicating pandoc's citation grammar (email / word-boundary edge cases).
_CITE_GROUP_RE = re.compile(r"\[([^\]]*@[^\]]+)\]")
_KEY_IN_GROUP_RE = re.compile(r"@([\w:.\-]+)")
# A BibTeX entry key: `@type{key,`.
_BIB_KEY_RE = re.compile(r"^\s*@\w+\s*\{\s*([^,\s]+)\s*,", re.M)


def _citekeys_in(text):
    keys = set()
    for grp in _CITE_GROUP_RE.findall(text):
        keys.update(_KEY_IN_GROUP_RE.findall(grp))
    return keys


def _bib_keys(bib_path):
    # Keys are ASCII (@type{key,); errors="replace" keeps a non-UTF-8 byte in an
    # accented author field from crashing key extraction with a raw traceback --
    # pandoc stays the authority on the bib's actual content at build time.
    with open(bib_path, "r", encoding="utf-8", errors="replace") as fh:
        return set(_BIB_KEY_RE.findall(fh.read()))


# A link/image target is allowed when it is remote (http(s)/mailto/...) or an
# in-page anchor (#...); a relative path (e.g. figures/x.png) resolves under
# <slug>/sources/ and 404s (figures live at <slug>/figures/), so it is rejected.
_REMOTE_OR_ANCHOR_RE = re.compile(r'(?:[a-z][a-z0-9+.-]*:|//|#)', re.I)
# The sidecar is VALIDATED against its RENDERED HTML, never the raw markdown:
# pandoc is the parser, so a [@key] or a relative path shown inside a `code` /
# ```fence``` example is <code> text (never an <a>/<img> or a citation), and a
# reference-style [t][r] link is already resolved -- no code-span modeling, no
# raw-vs-rendered divergence. These scan that rendered fragment.
_HREF_SRC_RE = re.compile(r'<(?:a[^>]*?\shref|img[^>]*?\ssrc)="([^"]*)"', re.I)
_DATA_CITES_RE = re.compile(r'\sdata-cites="([^"]+)"')


def _check_sidecar_drift(adir):
    """File-level source-quotes.md checks at load (fail fast, before any render):
    not a symlink (read + published verbatim -- a link out of the article dir would
    leak another file's text onto the sources/ page) and valid UTF-8 (a stray byte
    would otherwise abort the whole build with a raw UnicodeDecodeError, past the
    CLI's BuildError handler). The link-target + @key-drift checks run on the
    RENDERED fragment (_validate_sources, from render_sources)."""
    sq = os.path.join(adir, "source-quotes.md")
    if not os.path.exists(sq):
        return
    if os.path.islink(sq):
        raise BuildError("%s/source-quotes.md must not be a symlink" % adir)
    try:
        with open(sq, "r", encoding="utf-8") as fh:
            fh.read()
    except UnicodeDecodeError as exc:
        raise BuildError("%s/source-quotes.md is not valid UTF-8: %s" % (adir, exc))


def _validate_sources(frag, adir):
    """Validate the RENDERED sidecar fragment (the single source of truth):

    - every link/image target is remote or an in-page anchor -- a relative target
      would 404 under <slug>/sources/;
    - every cited @key (from the rendered data-cites, so a [@key] inside a code
      example is not counted) exists in refs.bib -- a renamed/removed bib key left
      dangling in the sidecar is the cross-file drift to catch."""
    rel = sorted({t for t in _HREF_SRC_RE.findall(frag)
                  if t and not _REMOTE_OR_ANCHOR_RE.match(t)})
    if rel:
        raise BuildError("%s/source-quotes.md: relative link/image target(s) not "
                         "allowed (use an absolute URL): %s"
                         % (adir, ", ".join(rel)))
    bib = os.path.join(adir, "refs.bib")
    keys = _bib_keys(bib) if os.path.exists(bib) else set()
    used = set()
    for grp in _DATA_CITES_RE.findall(frag):
        used.update(grp.split())
    missing = sorted(used - keys)
    if missing:
        raise BuildError("%s/source-quotes.md: @key(s) not in refs.bib: %s"
                         % (adir, ", ".join(missing)))


def load_article(adir):
    slug_default = os.path.basename(adir.rstrip("/"))
    meta_path = os.path.join(adir, "meta.toml")
    body_path = os.path.join(adir, "paper.md")
    if not os.path.isfile(meta_path):
        raise BuildError("%s: missing meta.toml" % adir)
    if not os.path.isfile(body_path):
        raise BuildError("%s: missing paper.md" % adir)
    with open(meta_path, "rb") as fh:
        m = tomllib.load(fh)
    with open(body_path, "r", encoding="utf-8") as fh:
        paper = fh.read()
    title, abstract, body = _parse_paper(paper, adir)
    # Remote images would be fetched by pandoc at PDF build time (SSRF) and leak
    # the reader's IP at view time; require images to be vendored locally.
    if re.search(r'!\[[^\]]*\]\(\s*https?://', paper):
        raise BuildError("%s/paper.md: remote image URLs are not allowed; vendor "
                         "the image under figures/" % adir)
    m.setdefault("slug", slug_default)
    # Slug lands in filesystem paths and HTML attributes; keep it strict so it
    # cannot traverse out of the output tree or inject into an href. Coerce to
    # str first: a bare `slug = 123` in meta.toml is an int that passes the
    # string-form regex but then reaches _rel_dir/_root_rel (.count) as an int
    # and crashes rendering -- store the validated string everywhere downstream.
    m["slug"] = str(m["slug"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", m["slug"]):
        raise BuildError("%s/meta.toml: slug must match [a-z0-9][a-z0-9-]*, got %r"
                         % (adir, m["slug"]))
    m["title"] = title
    m["abstract"] = abstract
    for req in ("authors", "date"):
        if not m.get(req):
            raise BuildError("%s/meta.toml missing required key: %s" % (adir, req))
    if not isinstance(m["authors"], list) or not m["authors"]:
        raise BuildError("%s/meta.toml: authors must be a non-empty list" % adir)
    for author in m["authors"]:
        if (not isinstance(author, dict)
                or not isinstance(author.get("name"), str)
                or not author["name"].strip()):
            raise BuildError("%s/meta.toml: each author needs a non-empty string "
                             "name" % adir)
    if "keywords" in m and (not isinstance(m["keywords"], list)
                            or not all(isinstance(k, str) for k in m["keywords"])):
        raise BuildError("%s/meta.toml: keywords must be a list of strings" % adir)
    if "subjects" in m and not isinstance(m["subjects"], list):
        raise BuildError("%s/meta.toml: subjects must be a list" % adir)
    if "ccs_concepts" in m and not isinstance(m["ccs_concepts"], list):
        raise BuildError("%s/meta.toml: ccs_concepts must be a list" % adir)
    for a in m["authors"]:
        oid = a.get("orcid")
        if oid is not None and not re.fullmatch(
                r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", str(oid)):
            raise BuildError("%s/meta.toml: orcid must be 0000-0000-0000-000X, "
                             "got %r" % (adir, oid))
    for key in ("data_availability", "funding", "conflicts"):
        if key in m and not isinstance(m[key], str):
            raise BuildError("%s/meta.toml: %s must be a string" % (adir, key))
    if "article_number" in m:
        an = str(m["article_number"])
        # Stable online-only article id (e.g. CSR-2026-001). Keep it to a safe,
        # citation-friendly charset; it is shown and goes into cite strings.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", an):
            raise BuildError("%s/meta.toml: article_number must match "
                             "[A-Za-z0-9][A-Za-z0-9.-]*, got %r" % (adir, an))
        m["article_number"] = an
    # Per-article vendor-mention allowlist: exact phrases permitted in THIS
    # article's output only (e.g. a COI disclosure naming the project).
    av = m.setdefault("allow_vendor_mentions", [])
    if not isinstance(av, list) or not all(
            isinstance(x, str) and x.strip() for x in av):
        raise BuildError("%s/meta.toml: allow_vendor_mentions must be a list of "
                         "non-empty strings" % adir)
    # Coerce dates to ISO strings: unquoted TOML dates parse as datetime.date,
    # which would crash _scholar_date. Validate the shape here, loudly.
    for key in ("date", "online_date", "received", "accepted"):
        val = m.get(key)
        if val is None:
            continue
        if isinstance(val, (datetime.date, datetime.datetime)):
            m[key] = val.isoformat()[:10]
        else:
            m[key] = str(val)
        if not re.match(r"^\d{4}(-\d{2}-\d{2})?$", m[key]):
            raise BuildError("%s/meta.toml: %s must be YYYY-MM-DD or YYYY, got %r"
                             % (adir, key, m[key]))
    status = str(m.get("status", "draft")).lower()
    if status not in STATUS_LABELS:
        raise BuildError("%s/meta.toml: status must be one of %s, got %r"
                         % (adir, ", ".join(sorted(STATUS_LABELS)),
                            m.get("status")))
    m["status"] = status
    if status == "corrected":
        cd = m.get("corrected_date")
        if cd is None:
            raise BuildError("%s/meta.toml: status 'corrected' requires "
                             "corrected_date (YYYY-MM-DD)" % adir)
        cd = cd.isoformat()[:10] if isinstance(cd, (datetime.date,
                                                    datetime.datetime)) else str(cd)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", cd):
            raise BuildError("%s/meta.toml: corrected_date must be YYYY-MM-DD, "
                             "got %r" % (adir, cd))
        m["corrected_date"] = cd
        cu = str(m.get("correction_url", ""))
        if cu and not re.match(r"^https?://", cu):
            raise BuildError("%s/meta.toml: correction_url must be http(s), got %r"
                             % (adir, cu))
        m["correction_url"] = cu
    m["_dir"] = adir
    m["_body_md"] = body
    _check_sidecar_drift(adir)
    return m


# ---------------------------------------------------------------- helpers

def _run(cmd, **kw):
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)
    except FileNotFoundError:
        raise BuildError("required tool not found: %s" % cmd[0])
    except subprocess.CalledProcessError as exc:
        raise BuildError("%s failed:\n%s" % (" ".join(cmd), exc.stderr or exc.stdout))


def _scholar_date(iso):
    """ISO YYYY-MM-DD -> Scholar's YYYY/MM/DD; a bare year passes through."""
    return iso.replace("-", "/")


def _rel_dir(m):
    return m["slug"]


def _root_rel(rel_dir):
    """'../' repeated to climb from an article dir back to the site root."""
    depth = rel_dir.count("/") + 1
    return "../" * depth


def _site_root(journal):
    """Absolute root path for the HEADER nav, identical on every page so the nav
    is cross-page consistent (depth-relative '../' would differ by page depth and
    read as an inconsistent nav). Derived from base_url's path: a host-root site
    yields '/', a subpath deployment yields '/<path>/'."""
    path = urlsplit(journal["base_url"]).path.rstrip("/")
    return (path + "/") if path else "/"


# Neutralize dangerous URL schemes in generated href/src (defense in depth;
# raw HTML passthrough is already disabled in the reader).
_DANGEROUS_URL_RE = re.compile(
    r'((?:href|src)\s*=\s*")\s*(?:javascript|vbscript|data)\s*:', re.I)
_EVENT_ATTR_RE = re.compile(
    r'\son[a-z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.I)
# Inline style attribute: blocked by the strict style-src 'self' CSP (never
# applied, logs a console error), so strip it from pandoc output.
_STYLE_ATTR_RE = re.compile(r'\s+style\s*=\s*("[^"]*"|\'[^\']*\')', re.I)
# One HTML tag: '<' + a letter or '/', then attribute text where a quoted value
# (which may itself contain '>') is consumed whole, up to the closing '>'. The
# attribute strippers run ONLY inside a matched tag -- a blind whole-fragment
# regex also eats the literal sequence style="..." / onX= from RUNNING PROSE (a
# security journal routinely quotes such attributes), silently dropping reader-
# visible text. Pandoc escapes '<'/'>' in text content, so every match here is a
# real tag and a displayed HTML sample inside <pre>/<code> (its '<' escaped) is
# never matched -- the per-tag scope subsumes the old code-span skip.
_TAG_RE = re.compile(r'<[a-zA-Z/][^>"\']*(?:(?:"[^"]*"|\'[^\']*\')[^>"\']*)*>', re.S)


def _strip_tag_attrs(tag):
    tag = _DANGEROUS_URL_RE.sub(r"\1#", tag)
    tag = _EVENT_ATTR_RE.sub("", tag)
    # Strict CSP is style-src 'self': an inline style attribute is BLOCKED (never
    # applied) and logs a console error. Pandoc emits them on table parts (col
    # width, cell align); styling belongs in the stylesheet, so strip them.
    tag = _STYLE_ATTR_RE.sub("", tag)
    return tag


def _sanitize_html(frag):
    return _TAG_RE.sub(lambda m: _strip_tag_attrs(m.group(0)), frag)


# Source stays ASCII " -- "; output renders a spaced en dash (idiomatic typeset
# prose, not a plaintext double hyphen). Skip code so a " -- " argument separator
# in a sample survives. Pandoc's smart stays OFF so quotes are left straight.
_HTML_CODE_RE = re.compile(r"<(pre|code)\b[^>]*>.*?</\1>", re.I | re.S)
_MD_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]+`", re.S)
_EN_DASH = chr(0x2013)  # literal only at runtime; source byte sequence is ASCII


def _sub_outside(code_re, replace, text):
    out, last = [], 0
    for m in code_re.finditer(text):
        out.append(replace(text[last:m.start()]))
        out.append(m.group(0))  # code span: untouched
        last = m.end()
    out.append(replace(text[last:]))
    return "".join(out)


def _endash_html(frag):
    # &ndash; is ASCII bytes (passes the ASCII gate) and renders as an en dash.
    return _sub_outside(_HTML_CODE_RE, lambda s: s.replace(" -- ", " &ndash; "),
                        frag)


def _endash_md(text):
    # PDF path (not ASCII-gated): feed a real en dash; LaTeX/inputenc render it.
    return _sub_outside(_MD_CODE_RE,
                        lambda s: s.replace(" -- ", " " + _EN_DASH + " "), text)


def _ascii_entities_html(frag):
    # citeproc emits typographic punctuation (en dash, curly quotes) and a
    # bibliography may carry accented author names; the HTML path is ASCII-gated,
    # so fold every non-ASCII char to a numeric HTML entity -- byte-ASCII output
    # that renders identically, independent of the CSL locale. Runs on generated
    # output only (the author body is ASCII), so no code span needs protecting.
    return "".join(c if ord(c) < 128 else "&#x%x;" % ord(c) for c in frag)


# IEEE numeric CSL shipped by citation-style-language-styles (Depends). Numbers
# references by first in-text appearance, so inserting a cite never renumbers.
CSL_PATH = "/usr/share/citation-style-language/styles/ieee.csl"


# citeproc wraps case-protected title text (from a {{double-braced}} bib title)
# in <span class="nocase">. It is a BibTeX parse-time marker, a no-op in rendered
# HTML; drop the class so the stylesheet carries no dead selector (the
# website-tests check_site gate flags a sole class with no CSS rule / JS use).
_NOCASE_RE = re.compile(r'\s+class="nocase"')
# autolink_bare_uris tags each autolinked URL with class="uri" -- a presentational
# no-op with no CSS rule / JS use, which the check_site orphan-class gate flags
# (same reason _NOCASE_RE exists). Strip it; the <a href> is what matters.
_URI_CLASS_RE = re.compile(r'\s+class="uri"')


def _check_citeproc(stderr):
    # citeproc EXITS 0 on an undefined [@key] -- it renders "key?" and warns on
    # stderr. Promote any citeproc warning to a hard build failure so a dangling
    # citation cannot ship silently.
    bad = [ln for ln in stderr.splitlines() if "Citeproc:" in ln]
    if bad:
        raise BuildError("unresolved citation(s):\n" + "\n".join(bad))


def md_to_html_fragment(md_text, bib_path=None, autolink=False):
    # Disable: raw_html (author <script> becomes text); smart (keep output ASCII
    # -- smart would emit curly quotes / en-dashes); and the attribute extensions
    # that let author Markdown attach arbitrary HTML attributes such as an
    # onerror handler on an image. _sanitize_html is the backstop for any
    # residual event-handler attribute or dangerous URL scheme.
    fmt = ("markdown-raw_html-smart-raw_attribute-link_attributes"
           "-native_divs-native_spans")
    if autolink:
        # Turn bare http(s) URLs (and emails) into links -- the source-quotes
        # sidecar lists many source URLs as plain text. pandoc linkifies only real
        # absolute URIs, so a label like arXiv:NNNN or "doi 10.x" stays text.
        fmt += "+autolink_bare_uris"
    cmd = ["pandoc", "-f", fmt, "-t", "html5", "--wrap=none"]
    if bib_path:
        # citeproc renders the in-text numbers (by first appearance), the
        # reference list at the ::: {#refs} div, and the DOI/URL links from the
        # bibliography -- replacing the old hand-rolled [n] linkifier.
        cmd += ["--citeproc", "--bibliography", bib_path, "--csl", CSL_PATH,
                "-M", "link-citations=true", "-M", "link-bibliography=true"]
    r = _run(cmd, input=md_text)
    _check_citeproc(r.stderr)
    html = _URI_CLASS_RE.sub("", _NOCASE_RE.sub("", r.stdout))
    return _ascii_entities_html(_endash_html(_sanitize_html(html)))


def _yaml_dq(s):
    """Double-quoted YAML scalar, safely escaped."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def md_to_pdf(m, journal, out_pdf):
    """Render a camera-ready PDF via pandoc + pdflatex (content is ASCII)."""
    authors_yaml = "\n".join("  - " + _yaml_dq(a["name"]) for a in m["authors"])
    abstract = " ".join(m["abstract"].split())
    date_human = m["date"]
    meta_block = (
        "---\n"
        "title: %s\n"
        "author:\n%s\n"
        "date: %s\n"
        "abstract: %s\n"
        "documentclass: article\n"
        "---\n\n"
    ) % (_yaml_dq(m["title"]), authors_yaml, _yaml_dq(date_human),
         _yaml_dq(abstract))
    doi_line = ("DOI: %s\n\n" % m["doi"]) if m.get("doi") else ""
    doc = _endash_md(meta_block + doi_line + m["_body_md"])
    # -raw_tex: author raw TeX (e.g. \input{/etc/passwd}) is not passed to the
    # engine. -raw_attribute: a fenced ```{=latex} / ```{=html} block is literal
    # text, not a raw passthrough to the engine (disabling raw_tex alone does not
    # cover the raw_attribute syntax). Mirrors md_to_html_fragment's reader.
    # openin_any/openout_any=p additionally bar the engine from reading or
    # writing files outside the tree, in case any TeX slips through.
    env = dict(os.environ, openin_any="p", openout_any="p")
    # Preamble additions MUST go through --include-in-header, which inserts them
    # into the LaTeX preamble VERBATIM: the reader runs with raw_tex disabled, so
    # the same \usepackage via a header-includes metadata value is escaped to
    # literal text -- not loaded, and printed as visible garbage in the PDF.
    #   - lmodern: Type-1 (vector) glyphs for sans/mono instead of Type-3 bitmaps
    #     that defeat text extraction (check.py's pdffonts gate rejects Type 3).
    #   - mathpazo: Palatino roman + matching math; stock texlive, no extra CI dep.
    #     Loaded AFTER lmodern so its Palatino roman wins while sans/mono stay LM.
    #   - \UrlBreaks / \Urlmuskip: let long bibliography URLs wrap instead of
    #     overflowing the right margin. url's registers exist only once the package
    #     is loaded, and pandoc inserts these header-includes BEFORE it loads
    #     hyperref (which pulls in url) -- so the config is deferred with
    #     \AtBeginDocument, by when url is loaded and nothing overrides it again.
    hdr = tempfile.NamedTemporaryFile(mode="w", suffix=".tex", delete=False,
                                      encoding="utf-8")
    try:
        hdr.write(
            "\\usepackage{lmodern}\n"
            "\\usepackage{mathpazo}\n"
            "\\AtBeginDocument{%\n"
            "  \\Urlmuskip=0mu plus 1mu\\relax\n"
            "  \\def\\UrlBreaks{\\do\\/\\do\\-\\do\\.\\do\\_\\do\\?"
            "\\do\\&\\do\\=\\do\\#\\do\\%\\do\\;\\do\\:}%\n"
            "}\n")
        hdr.close()
        cmd = [
            "pandoc", "-f", "markdown-raw_tex-smart-raw_attribute", "-o", out_pdf,
            "--pdf-engine=pdflatex",
            "--include-in-header", hdr.name,
            "--resource-path", m["_dir"],
            "-V", "geometry:margin=1in",
            "-V", "fontsize=11pt",
            "-V", "linkcolor=blue",
            "-V", "urlcolor=blue",
        ]
        bib = os.path.join(m["_dir"], "refs.bib")
        if os.path.exists(bib):
            # citeproc resolves before LaTeX, so the engine is unaffected; the
            # reference list lands at the ::: {#refs} div in the body.
            cmd += ["--citeproc", "--bibliography", bib, "--csl", CSL_PATH]
        r = _run(cmd, input=doc, env=env)
        _check_citeproc(r.stderr)
    finally:
        os.unlink(hdr.name)


# ---------------------------------------------------------------- meta tags

def citation_meta(m, journal, landing_url, pdf_url):
    tags = []

    def add(name, content):
        tags.append('<meta name="%s" content="%s">'
                    % (name, html.escape(str(content), quote=True)))

    add("citation_title", m["title"])
    for a in m["authors"]:
        add("citation_author", a["name"])
        if a.get("institution"):
            add("citation_author_institution", a["institution"])
    add("citation_publication_date", _scholar_date(m["date"]))
    if m.get("online_date"):
        add("citation_online_date", _scholar_date(m["online_date"]))
    # A self-published web preview is a technical report, NOT a journal article:
    # Scholar's institution tag carries the publishing site; never
    # citation_journal_title or citation_issn (serial/journal identifiers).
    add("citation_technical_report_institution", journal["publisher"])
    if m.get("article_number"):
        add("citation_technical_report_number", m["article_number"])
    if m.get("firstpage"):
        add("citation_firstpage", m["firstpage"])
    if m.get("lastpage"):
        add("citation_lastpage", m["lastpage"])
    if m.get("doi"):
        add("citation_doi", m["doi"])
    add("citation_language", m.get("language", journal["language"]))
    for kw in m.get("keywords", []):
        add("citation_keywords", kw)
    add("citation_abstract_html_url", landing_url)
    add("citation_pdf_url", pdf_url)
    return "\n".join(tags)


# ----------------------------------------------------------- security policy
# Maximum-strict CSP. The journal ships NO executable script (the only inline
# <script> is inert application/ld+json data), NO web fonts (system stack), and
# makes NO network calls -- so everything collapses to 'none' except the single
# same-origin stylesheet (style-src 'self') and figure images (img-src 'self').
# Trusted Types are enforced AND no policy may be created (trusted-types 'none').

def _csp_header():
    """Full policy for a header-capable host (carries frame-ancestors).

    script-src 'self': ONE self-hosted bundle (assets/site.js), no CDN, no
    'unsafe-inline', no eval. Trusted Types stay enforced AND no policy may be
    created (trusted-types 'none') -- the bundle is written TT-safe (textContent
    / setAttribute / addEventListener only, never a TT sink), so it needs none.
    """
    return (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'; object-src 'none'; "
        "require-trusted-types-for 'script'; trusted-types 'none'")


def _csp_meta():
    """The <meta http-equiv> policy: the header minus frame-ancestors, which a
    meta tag cannot set."""
    return (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; "
        "object-src 'none'; require-trusted-types-for 'script'; "
        "trusted-types 'none'")


# A directly-opened SVG document enforces the response CSP on itself; style-src
# 'self' would drop an SVG's inline styles and render it blank, so a directly
# served SVG gets a sandbox carve-out (still no script).
_SVG_CSP = ("default-src 'none'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'")

# Deny every browser feature except clipboard-write, which the self-hosted
# copy-buttons need (scoped to self; nothing else is permitted).
_PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), browsing-topics=(), camera=(), "
    "clipboard-read=(), clipboard-write=(self), display-capture=(), "
    "encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), hid=(), "
    "magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), "
    "publickey-credentials-get=(), screen-wake-lock=(), serial=(), sync-xhr=(), "
    "usb=(), xr-spatial-tracking=()")


def _security_headers():
    """Canonical HTTP security headers for a header-capable static host, in
    order (GitHub Pages ignores _headers; the <meta> CSP is the boundary there)."""
    return [
        ("Content-Security-Policy", _csp_header()),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("X-XSS-Protection", "0"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("Strict-Transport-Security",
         "max-age=63072000; includeSubDomains; preload"),
        ("Permissions-Policy", _PERMISSIONS_POLICY),
        ("Cross-Origin-Embedder-Policy", "require-corp"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
    ]


def write_headers(out_dir):
    """Emit the root `_headers` file (Cloudflare/Netlify format): one `/*` block
    with the canonical security headers, plus a per-SVG CSP carve-out so a
    directly-opened SVG keeps its inline styles. Mirrors mw-static-generator."""
    lines = ["/*"]
    lines += ["  %s: %s" % (n, v) for n, v in _security_headers()]
    svgs = []
    for root, _d, files in os.walk(out_dir):
        for nm in files:
            if nm.lower().endswith((".svg", ".svgz")):
                rel = os.path.relpath(os.path.join(root, nm),
                                      out_dir).replace(os.sep, "/")
                svgs.append(rel)
    for rel in sorted(svgs):
        # Allowlist the path: anything outside this safe charset could widen or
        # rebind the rule and strip the strict /* CSP off other responses.
        if not re.fullmatch(r"[A-Za-z0-9._ /-]+", rel):
            continue
        lines += ["", "/" + rel, "  ! Content-Security-Policy",
                  "  Content-Security-Policy: " + _SVG_CSP]
    with open(os.path.join(out_dir, "_headers"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- rendering

def _icon_links(root_rel):
    """Favicon + apple-touch + mask icons, theme-color (light/dark) and the PWA
    manifest, emitted in every page head. All same-origin (img-src / manifest-src
    'self'). The SVG scales to any size; the PNGs are rsvg renders for clients
    that need raster. theme-color values track --bg (light #fdfdfc / dark #15171b)."""
    a = root_rel + "assets/"
    return (
        '<link rel="icon" type="image/svg+xml" href="%(a)sfavicon.svg">\n'
        '<link rel="icon" type="image/png" sizes="512x512" href="%(a)sfavicon.png">\n'
        '<link rel="apple-touch-icon" href="%(a)sfavicon.png">\n'
        '<link rel="mask-icon" href="%(a)sfavicon.svg" color="#0b5cad">\n'
        '<meta name="theme-color" media="(prefers-color-scheme: light)" '
        'content="#fdfdfc">\n'
        '<meta name="theme-color" media="(prefers-color-scheme: dark)" '
        'content="#15171b">\n'
        '<link rel="manifest" href="%(a)smanifest.webmanifest">'
    ) % {"a": a}


def _page(lang, head_title, description, canonical, extra_head, body,
          journal, root_rel):
    from jmaker.templates import STYLE_CSS, site_header, site_footer  # noqa
    robots = ('<meta name="robots" content="noindex">\n'
              if journal.get("_no_index") else "")
    return (
        "<!doctype html>\n"
        '<html lang="%s">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta http-equiv="Content-Security-Policy" content="%s">\n'
        "%s"
        "<title>%s</title>\n"
        '<meta name="description" content="%s">\n'
        '<link rel="canonical" href="%s">\n'
        '<link rel="alternate" type="application/rss+xml" title="%s" '
        'href="%sfeed.xml">\n'
        "%s\n"
        "%s\n"
        '<link rel="stylesheet" href="%sassets/style.css">\n'
        '<script src="%sassets/site.js" defer></script>\n'
        "</head>\n<body>\n"
        '<a class="skip-link" href="#main">Skip to content</a>\n'
        "%s\n%s\n%s\n</body>\n</html>\n"
    ) % (
        html.escape(lang), _csp_meta(), robots, html.escape(head_title),
        html.escape(description),
        html.escape(canonical, quote=True),
        html.escape(journal["title"], quote=True), root_rel,
        extra_head, _icon_links(root_rel), root_rel, root_rel,
        site_header(journal["title"], _site_root(journal)), body,
        site_footer(journal, root_rel),
    )


def _build_toc(body_html):
    """Table of contents from the body's H2 headings (pandoc-assigned ids)."""
    items = re.findall(r'<h2[^>]*\bid="([^"]+)"[^>]*>(.*?)</h2>', body_html,
                       re.I | re.S)
    if len(items) < 3:
        return ""
    strip = re.compile(r'<[^>]+>')
    lis = []
    for hid, inner in items:
        text = re.sub(r'\s+', " ", strip.sub("", inner)).strip()
        lis.append('<li><a href="#%s">%s</a></li>'
                   % (html.escape(hid, quote=True), html.escape(text)))
    return ('<nav class="toc" aria-label="Contents">'
            '<div class="toc-label">Contents</div>\n<ol>\n%s\n'
            "</ol></nav>\n" % "\n".join(lis))


def _bibtex(m, journal, landing_url):
    surname = (re.sub(r'[^a-z0-9]', "", m["authors"][0]["name"].lower().split()[-1])
               if m["authors"] else "anon")
    key = "%s%s" % (surname, m["date"][:4])
    # A self-published web preview, NOT a journal article: @misc + howpublished
    # (the site), never @article/journal (see csr framing rules).
    fields = [
        ("author", " and ".join(a["name"] for a in m["authors"])),
        ("title", m["title"]),
        ("howpublished", journal["title"]),
        ("year", m["date"][:4]),
    ]
    if m.get("doi"):
        fields.append(("doi", m["doi"]))
    fields.append(("url", landing_url))
    body = ",\n".join("  %s = {%s}" % (k, v) for k, v in fields)
    return "@misc{%s,\n%s\n}" % (key, body)


def _status_fragment(m):
    """Visible + machine status markers. Pure (no pandoc) so it is unit-testable.

    Returns (pill_html, banner_html, line_html, head_meta). The pill is kept
    OUT of the <h1> so it cannot pollute the citation_title consistency check.
    """
    status = m["status"]
    pill = ('<p class="status-pill-row"><span class="status-pill status-%s">%s'
            "</span></p>\n" % (status, html.escape(_STATUS_PILL[status])))
    line = _endash_html('<p class="status-line">Status: %s</p>\n'
                        % html.escape(STATUS_LABELS[status]))
    banner = ""
    if status == "draft":
        banner = ('<aside class="status-banner status-draft" role="note">'
                  "This is a draft posted for comment. It has not been peer "
                  "reviewed and may change. Cite with caution.</aside>\n")
    elif status == "corrected":
        when = (" on " + html.escape(m["corrected_date"])) if m.get(
            "corrected_date") else ""
        url = m.get("correction_url", "")
        notice = ('See the <a href="%s">correction notice</a>.'
                  % html.escape(url, quote=True)) if url \
            else "See the correction notice."
        banner = ('<aside class="status-banner status-corrected" role="note">'
                  "This article was corrected%s. %s</aside>\n" % (when, notice))
    head = '<meta name="article_status" content="%s">' % status
    return pill, banner, line, head


def _jsonld(m, journal, landing_url):
    """schema.org ScholarlyArticle; carries creativeWorkStatus (the one standard
    machine field for status -- there is no citation_* version/status tag)."""
    ld = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "headline": m["title"],
        "author": [{"@type": "Person", "name": a["name"]} for a in m["authors"]],
        "datePublished": m["date"],
        "creativeWorkStatus": _STATUS_SCHEMA[m["status"]],
        "isAccessibleForFree": True,
        "publisher": {"@type": "Organization", "name": journal["publisher"]},
        "url": landing_url,
    }
    if m.get("doi"):
        ld["identifier"] = "https://doi.org/" + m["doi"]
    if m.get("keywords"):
        ld["keywords"] = ", ".join(m["keywords"])
    # ensure_ascii keeps output ASCII; then neutralize </script> breakout chars.
    j = (json.dumps(ld).replace("<", "\\u003c").replace(">", "\\u003e")
         .replace("&", "\\u0026"))
    return '<script type="application/ld+json">%s</script>' % j


def _og_locale(journal):
    # OpenGraph wants a locale like en_US; map a bare "en" to it, else pass the
    # configured language through.
    lang = journal.get("language", "en")
    return "en_US" if lang == "en" else lang


def _opengraph(title, description, url, journal, og_type="website"):
    """OpenGraph + Twitter-card meta for a link preview (NOT read by Google
    Scholar -- the citation_* tags serve that). Emitted on EVERY page type;
    og_type is 'article' for a paper, 'website' for the homepage / standalone
    pages."""
    def t(key, content, attr="property"):
        return ('<meta %s="%s" content="%s">'
                % (attr, key, html.escape(str(content), quote=True)))
    img = journal["base_url"] + "/assets/og.png"
    return "\n".join([
        t("og:type", og_type),
        t("og:title", title),
        t("og:description", description),
        t("og:url", url),
        t("og:site_name", journal["title"]),
        t("og:locale", _og_locale(journal)),
        t("og:image", img),
        t("og:image:width", "1200"),
        t("og:image:height", "630"),
        t("og:image:alt", journal["title"]),
        t("twitter:card", "summary_large_image", attr="name"),
        t("twitter:title", title, attr="name"),
        t("twitter:description", description, attr="name"),
        t("twitter:image", img, attr="name"),
        t("twitter:image:alt", journal["title"], attr="name"),
    ])


def _jsonld_page(ld_type, name, description, url, journal):
    """schema.org JSON-LD for a non-article page: WebSite (homepage),
    CollectionPage (browse), or WebPage (standalone). Articles use the richer
    ScholarlyArticle block (_jsonld)."""
    ld = {
        "@context": "https://schema.org",
        "@type": ld_type,
        "name": name,
        "description": description,
        "url": url,
        "inLanguage": journal.get("language", "en"),
        "publisher": {"@type": "Organization", "name": journal["publisher"]},
    }
    j = (json.dumps(ld).replace("<", "\\u003c").replace(">", "\\u003e")
         .replace("&", "\\u0026"))
    return '<script type="application/ld+json">%s</script>' % j


def _authors_html(m):
    out = []
    for a in m["authors"]:
        bit = html.escape(a["name"])
        if a.get("orcid"):
            bit += (' <a class="orcid" href="https://orcid.org/%s" '
                    'aria-label="ORCID iD for %s">iD</a>'
                    % (html.escape(a["orcid"], quote=True),
                       html.escape(a["name"], quote=True)))
        out.append(bit)
    return ", ".join(out)


def _history_line(m):
    if not (m.get("received") or m.get("accepted")):
        return ""   # nothing to add beyond the year already shown in the venue
    parts = []
    for label, key in (("Received", "received"), ("Accepted", "accepted"),
                       ("Published", "date")):
        if m.get(key):
            parts.append("%s %s" % (label, html.escape(m[key])))
    return '<p class="history">%s</p>\n' % "; ".join(parts)


def _subjects_line(m):
    subs = m.get("subjects") or []
    if not subs:
        return ""
    return ('<p class="subjects">Subjects: %s</p>\n'
            % "; ".join(html.escape(str(s)) for s in subs))


def _ccs_line(m):
    # ACM CCS concept paths, kept SEPARATE from the arXiv subject class so the
    # two taxonomies are not blended under one label.
    concepts = m.get("ccs_concepts") or []
    if not concepts:
        return ""
    return ('<p class="subjects">CCS Concepts: %s</p>\n'
            % "; ".join(html.escape(str(c)) for c in concepts))


def _license_footer(m, journal):
    lic = m.get("license", journal.get("license", ""))
    if not lic:
        return ""
    lic_url = journal.get("license_url", "")
    copyr = "(c) %s %s." % (m["date"][:4],
                            html.escape(", ".join(a["name"] for a in m["authors"])))
    # With a license URL it is a grant one is "licensed under" (e.g. CC BY 4.0).
    # Without one it is a bare rights statement (e.g. "All rights reserved"),
    # which reads wrong after "Licensed under" -- render it as the statement.
    if lic_url:
        badge = ('<a class="cc-badge" href="%s">%s</a>'
                 % (html.escape(lic_url, quote=True), html.escape(lic)))
        rights = "Licensed under %s." % badge
    else:
        rights = '<span class="cc-badge">%s</span>.' % html.escape(lic)
    return '<footer class="license">%s %s</footer>' % (copyr, rights)


def _statements(m):
    out = []
    for title, key in (("Data and Code Availability", "data_availability"),
                       ("Funding", "funding"),
                       ("Conflicts of Interest", "conflicts")):
        if m.get(key):
            out.append('<section class="statement"><h2>%s</h2>\n<p>%s</p>'
                       "</section>\n" % (title, html.escape(m[key])))
    return "".join(out)


def _ris(m, journal, landing_url):
    # TY ELEC (electronic/web), NOT JOUR: a self-published web document has no
    # journal, so there is no JO field (publisher carries the site). The access
    # URL is UR; the DOI, when present, is its own DO field.
    lines = ["TY  - ELEC"]
    lines += ["AU  - " + a["name"] for a in m["authors"]]
    lines += ["TI  - " + m["title"], "PB  - " + journal["publisher"],
              "PY  - " + m["date"][:4]]
    if m.get("article_number"):
        lines.append("M1  - " + m["article_number"])
    if m.get("doi"):
        lines.append("DO  - " + m["doi"])
    lines.append("UR  - " + landing_url)
    lines.append("ER  - ")
    return "\n".join(lines)


def _apa(m, journal, landing_url, year):
    # Web-page form: Author (Year). Title. Site. URL -- the site is the source,
    # not a journal; always carry a retrieval URL.
    authors = ", ".join(a["name"] for a in m["authors"])
    art = (", Article %s" % m["article_number"]) if m.get("article_number") else ""
    url = ("https://doi.org/%s" % m["doi"]) if m.get("doi") else landing_url
    return "%s (%s). %s. %s%s. %s" % (
        authors, year, m["title"], journal["title"], art, url)


def _ieee_cite(m, journal, landing_url, year):
    # Online form: name the site + an [Online]. Available link, not a journal.
    authors = ", ".join(a["name"] for a in m["authors"])
    artno = (", Art. no. %s" % m["article_number"]) if m.get("article_number") \
        else ""
    tail = (", doi: %s" % m["doi"]) if m.get("doi") else ""
    return '%s, "%s," %s%s, %s%s. [Online]. Available: %s' % (
        authors, m["title"], journal["title"], artno, year, tail, landing_url)


def _cite_box(m, journal, landing_url, year):
    fmts = [
        ("IEEE", _ieee_cite(m, journal, landing_url, year)),
        ("APA", _apa(m, journal, landing_url, year)),
        ("BibTeX", _bibtex(m, journal, landing_url)),
        ("RIS", _ris(m, journal, landing_url)),
    ]
    rows = "".join(
        '<div class="cite-fmt"><span class="cite-label">%s</span>'
        "<pre>%s</pre></div>\n" % (label, html.escape(text))
        for label, text in fmts)
    return ('<details class="cite-this"><summary>Cite this</summary>\n%s'
            "</details>\n" % rows)


def _order_key(m):
    """Stable reading order: by date (newest handled by caller), then slug."""
    return (str(m.get("date", "")), m["slug"])


def _article_nav(neighbors, root_rel):
    """Prev/next links within the journal's reading order (empty if alone)."""
    if not neighbors:
        return ""
    prev, nxt = neighbors
    parts = []
    if prev:
        parts.append('<a class="nav-prev" rel="prev" href="%s%s/">&#8592; %s</a>'
                     % (root_rel, _rel_dir(prev), html.escape(prev["title"])))
    if nxt:
        parts.append('<a class="nav-next" rel="next" href="%s%s/">%s &#8594;</a>'
                     % (root_rel, _rel_dir(nxt), html.escape(nxt["title"])))
    if not parts:
        return ""
    return ('<nav class="article-nav" aria-label="Article navigation">%s</nav>\n'
            % "".join(parts))


def render_article(m, journal, neighbors=None, skip_pdf=False):
    rel_dir = _rel_dir(m)
    root_rel = _root_rel(rel_dir)
    landing_url = "%s/%s/" % (journal["base_url"], rel_dir)
    pdf_name = "%s.pdf" % m["slug"]
    pdf_url = landing_url + pdf_name
    description = " ".join(m["abstract"].split())[:300]

    meta = citation_meta(m, journal, landing_url, pdf_url)
    pill, banner, status_line, status_head = _status_fragment(m)
    meta = (meta + "\n" + status_head + "\n"
            + _opengraph(m["title"], description, landing_url, journal,
                         og_type="article") + "\n"
            + _jsonld(m, journal, landing_url))
    bib_path = os.path.join(m["_dir"], "refs.bib")
    has_bib = os.path.exists(bib_path)
    # A [@key] citation needs refs.bib; scan outside code spans so a literal
    # "[@" in a sample is not mistaken for a citation.
    if not has_bib and _citekeys_in(_MD_CODE_RE.sub(" ", m["_body_md"])):
        raise BuildError("%s: body has [@...] citations but no refs.bib"
                         % m["_dir"])
    # The abstract is rendered WITHOUT citeproc (a cited abstract would append a
    # whole reference list), and it is reused verbatim as the plain-text meta /
    # OpenGraph description -- so a citation there cannot render and would ship as
    # literal "[@key]". Forbid it outright, loudly.
    if _citekeys_in(_MD_CODE_RE.sub(" ", m["abstract"])):
        raise BuildError("%s: abstract must not contain [@...] citations "
                         "(it is the plain-text meta/OG description)" % m["_dir"])
    body_html = md_to_html_fragment(m["_body_md"], bib_path if has_bib else None)
    abstract_html = md_to_html_fragment(m["abstract"])
    toc = _build_toc(body_html)

    authors_line = _authors_html(m)
    affils = []
    for a in m["authors"]:
        inst = a.get("institution")
        if inst and inst not in affils:
            affils.append(inst)
    affil_bit = ('<p class="affil">%s</p>\n'
                 % "; ".join(html.escape(x) for x in affils)) if affils else ""
    year = m["date"][:4]
    venue = "%s (%s)" % (html.escape(journal["title"]), html.escape(year))
    if m.get("article_number"):
        venue += ", Article %s" % html.escape(m["article_number"])
    doi_bit = ""
    if m.get("doi"):
        doi_bit = ' &middot; DOI: <a href="https://doi.org/%s">%s</a>' % (
            html.escape(m["doi"], quote=True), html.escape(m["doi"]))
    history = _history_line(m)
    subjects = _subjects_line(m)
    ccs = _ccs_line(m)
    cite_box = _cite_box(m, journal, landing_url, year)
    statements = _statements(m)
    license_bit = _license_footer(m, journal)
    # PDF + sha256 are generated only on a full build (build() gates them on
    # skip_pdf); omit the download anchors in a skip-pdf tree so it carries no
    # link to an artifact that was never produced. The source-quotes reviewer-aid
    # link appears whenever the sidecar exists, independent of the PDF.
    action_links = []
    if not skip_pdf:
        action_links.append('<a href="%s">Download PDF</a>' % pdf_name)
        action_links.append('<a class="checksum" href="%s.sha256">SHA-256</a>'
                             % pdf_name)
    if os.path.exists(os.path.join(m["_dir"], "source-quotes.md")):
        action_links.append('<a class="sources-aid" href="sources/">'
                            "Source quotes</a>")
    if journal.get("source_base_url"):
        src = "%s/articles/%s/paper.md" % (journal["source_base_url"], m["slug"])
        action_links.append('<a class="sources-aid" href="%s">Markdown source</a>'
                            % html.escape(src, quote=True))
    actions_bit = (('<p class="actions">%s</p>\n' % " ".join(action_links))
                   if action_links else "")

    main = (
        '<main id="main" class="article">\n'
        "%s"                                   # banner (draft/corrected)
        "%s"                                   # status pill
        '<h1 class="title">%s</h1>\n'
        '<p class="authors">%s</p>\n'
        "%s"                                   # affiliations
        '<p class="venue">%s%s</p>\n'
        "%s"                                   # article history
        "%s"                                   # subjects
        "%s"                                   # ccs concepts
        "%s"                                   # status line
        "%s"                                   # pdf download actions (omitted when skip_pdf)
        "%s"                                   # cite box (beside the download action)
        '<section class="abstract"><h2>Abstract</h2>%s</section>\n'
        "%s"                                   # toc
        '<article class="body">\n%s\n</article>\n'
        "%s"                                   # statements (data/funding/COI)
        "%s"                                   # prev/next article nav
        "%s\n</main>"                          # license footer
    ) % (banner, pill, html.escape(m["title"]), authors_line, affil_bit, venue,
         doi_bit, history, subjects, ccs, status_line, actions_bit,
         cite_box, abstract_html, toc, body_html, statements,
         _article_nav(neighbors, root_rel), license_bit)

    page = _page(
        m.get("language", journal["language"]),
        "%s -- %s" % (m["title"], journal["title"]),
        description, landing_url, meta, main, journal, root_rel)
    return rel_dir, pdf_name, page


# pandoc (no citeproc) renders a sidecar heading's leading [@key] as
# <span class="citation" data-cites="KEY">[@key]</span>; rebind the heading's
# auto-slug id to the stable @citekey so the paper can deep-link sources/#KEY.
# Keys are [\w:.\-]+ (csr-rules), so the captured value is HTML-attribute-safe.
# A GROUPED heading ([@a; @b]) yields data-cites="a b": the FIRST key becomes the
# heading id and each remaining key gets its own empty anchor, so every key
# resolves (a space-bearing id would select nothing). Group 2 is the [@key] label
# text, wrapped in a self-link so the key is a clickable permalink to its entry.
_SOURCES_H2_RE = re.compile(
    r'<h2 id="[^"]*"><span class="citation" data-cites="([^"]+)">(.*?)</span>',
    re.S)


def _sources_anchor_ids(frag):
    # De-dup ids across the whole page: two headings sharing a @key (or a key
    # repeated across groups) would emit duplicate ids -- invalid HTML, ambiguous
    # deep-link. First occurrence keeps the bare key; the rest get the first free
    # -N suffix (checked against every id already emitted, so keys like k,k,k-2
    # cannot collide on k-2).
    used = set()

    def uniq(key):
        cand, n = key, 1
        while cand in used:
            n += 1
            cand = "%s-%d" % (key, n)
        used.add(cand)
        return cand

    def repl(mo):
        keys = mo.group(1).split()
        hid = uniq(keys[0])
        extra = "".join('<span id="%s"></span>' % uniq(k) for k in keys[1:])
        # The [@key] label links to the heading's own id -- a clickable permalink
        # to the entry (shareable deep-link).
        return ('<h2 id="%s">%s<span class="citation" data-cites="%s">'
                '<a href="#%s">%s</a></span>'
                % (hid, extra, mo.group(1), hid, mo.group(2)))
    return _SOURCES_H2_RE.sub(repl, frag)


def render_sources(m, journal):
    """Render the per-article source-quotes.md reviewer aid as a standalone,
    read-only HTML page at <slug>/sources/, linked from the article.

    Verbatim source passages behind the paper's paraphrased claims, keyed by the
    same @citekey as refs.bib and the body. Rendered WITHOUT citeproc: the literal
    [@key] stays visible as the human-readable key (no in-text numbering, no
    duplicated reference list). A review aid, not part of the paper. Auto-generated
    from source-quotes.md, never hand-written."""
    sq_path = os.path.join(m["_dir"], "source-quotes.md")
    with open(sq_path, "r", encoding="utf-8") as fh:
        md_text = fh.read()
    rel_dir = _rel_dir(m) + "/sources"
    root_rel = _root_rel(rel_dir)
    canonical = "%s/%s/" % (journal["base_url"], rel_dir)
    rendered = md_to_html_fragment(md_text, autolink=True)
    _validate_sources(rendered, m["_dir"])
    frag = _sources_anchor_ids(rendered)
    title = "Source quotes -- %s" % m["title"]
    description = (("Verbatim source quotes backing the paraphrased claims in "
                    "%s -- a reviewer aid.") % " ".join(m["title"].split()))[:300]
    src_link = ""
    if journal.get("source_base_url"):
        su = "%s/articles/%s/source-quotes.md" % (journal["source_base_url"],
                                                  m["slug"])
        src_link = (' &middot; <a href="%s">Markdown source</a>'
                    % html.escape(su, quote=True))
    back = ('<p class="sources-back"><a href="../">&#8592; Back to the paper</a>%s'
            "</p>\n" % src_link)
    main = '<main id="main" class="page sources">\n%s%s\n</main>' % (back, frag)
    extra = (_opengraph(title, description, canonical, journal) + "\n"
             + _jsonld_page("WebPage", title, description, canonical, journal))
    page = _page(m.get("language", journal["language"]),
                 "%s -- %s" % (title, journal["title"]), description, canonical,
                 extra, main, journal, root_rel)
    return rel_dir, page


def render_page(slug, md_text, journal):
    """Render a standalone static page (about, policies, license) from Markdown."""
    lines = md_text.splitlines()
    title = slug.replace("-", " ").title()
    body_lines = lines
    for i, ln in enumerate(lines):
        s = ln.rstrip()
        if s.startswith("# ") and not s.startswith("## "):
            title = s[2:].strip()
            body_lines = lines[:i] + lines[i + 1:]
            break
    body_html = md_to_html_fragment("\n".join(body_lines))
    canonical = "%s/%s/" % (journal["base_url"], slug)
    # Meta description from the first body paragraph (markdown lightly stripped),
    # falling back to the title -- a real description beats a bare "About".
    desc = title
    for ln in body_lines:
        s = ln.strip()
        if s and not s.startswith("#"):
            s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)   # [text](url) -> text
            s = re.sub(r"[*_`]", "", s)
            desc = " ".join(s.split())[:200]
            break
    main = ('<main id="main" class="page">\n<h1>%s</h1>\n%s\n</main>'
            % (html.escape(title), body_html))
    extra = (_opengraph(title, desc, canonical, journal) + "\n"
             + _jsonld_page("WebPage", title, desc, canonical, journal))
    page = _page(journal["language"], "%s -- %s" % (title, journal["title"]),
                 desc, canonical, extra, main, journal, "../")
    return title, page


def render_homepage(articles, journal, pages):
    ordered = sorted(articles,
                     key=lambda m: (str(m.get("date", "")), m["title"]),
                     reverse=True)
    items = []
    for m in ordered:
        date = html.escape(str(m.get("date", "")))
        items.append('<li><a href="%s/">%s</a>%s</li>'
                     % (_rel_dir(m), html.escape(m["title"]),
                        (' <span class="date">%s</span>' % date) if date else ""))
    page_nav = ""
    if pages:
        links = "\n".join('<li><a href="%s/">%s</a></li>'
                          % (slug, html.escape(title)) for slug, title in pages)
        page_nav = "<h2>About</h2>\n<ul>\n%s\n</ul>\n" % links
    body = (
        '<main id="main">\n<h1>%s</h1>\n'
        "<p>Occasional computer-security research previews, posted for public "
        "commentary.</p>\n"
        '<h2>Previews</h2>\n<ul class="previews">\n%s\n</ul>\n'
        '<p><a href="browse/">Browse by keyword and author</a></p>\n'
        "%s</main>"
    ) % (html.escape(journal["title"]), "\n".join(items), page_nav)
    desc = ("Occasional computer-security research previews for public "
            "commentary.")
    home_url = journal["base_url"] + "/"
    extra = (_opengraph(journal["title"], desc, home_url, journal) + "\n"
             + _jsonld_page("WebSite", journal["title"], desc, home_url, journal))
    return _page(journal["language"], journal["title"], desc,
                 home_url, extra, body, journal, "")


def render_browse(articles, journal):
    """A /browse/ index grouping articles by keyword and by author."""
    def art_link(m):
        return '<a href="../%s/">%s</a>' % (_rel_dir(m), html.escape(m["title"]))

    def section(title, groups):
        if not groups:
            return ""
        lis = []
        for key in sorted(groups):
            items = ", ".join(art_link(x) for x in groups[key])
            lis.append("<li><strong>%s</strong>: %s</li>"
                       % (html.escape(key), items))
        return ("<h2>%s</h2>\n<ul class=\"browse\">\n%s\n</ul>\n"
                % (title, "\n".join(lis)))

    bykw: dict = {}
    byauth: dict = {}
    for m in articles:
        for kw in m.get("keywords", []):
            bykw.setdefault(str(kw), []).append(m)
        for a in m["authors"]:
            byauth.setdefault(a["name"], []).append(m)
    body = ('<main id="main">\n<h1>Browse</h1>\n%s%s</main>'
            % (section("By keyword", bykw), section("By author", byauth)))
    desc = "Browse articles by keyword and author."
    url = journal["base_url"] + "/browse/"
    extra = (_opengraph("Browse", desc, url, journal) + "\n"
             + _jsonld_page("CollectionPage", "Browse", desc, url, journal))
    return _page(journal["language"], "Browse -- %s" % journal["title"],
                 desc, url, extra, body, journal, "../")


def write_sitemap(urls, out_dir):
    # Byte-identical to dist_ai.webcheck.site.render_sitemap (the webcheck
    # 'previews' policy re-derives and compares). The sitemap lists every
    # navigable page regardless of the temporary no-index state: no-index is a
    # per-page <meta> concern, not a reason to drop a real page from the sitemap.
    # sorted() to byte-match webcheck's render_sitemap, which emits
    # sorted(seo_page_urls(...)); the build's own url order is incidental.
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    lines += ["  <url><loc>%s</loc></url>" % html.escape(u, quote=False)
              for u in sorted(urls)]
    lines.append("</urlset>")
    xml = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write(xml)


def write_feed(articles, journal, out_dir):
    """RSS 2.0 feed of articles, newest first (discoverability, no backend)."""
    items = []
    for m in sorted(articles, key=lambda a: a["date"], reverse=True):
        link = "%s/%s/" % (journal["base_url"], _rel_dir(m))
        desc = " ".join(m["abstract"].split())[:300]
        pub = ""
        try:
            dt = datetime.datetime.strptime(m["date"][:10], "%Y-%m-%d")
            pub = "<pubDate>%s</pubDate>" % dt.strftime(
                "%a, %d %b %Y 00:00:00 +0000")
        except ValueError:
            pass
        items.append(
            '  <item><title>%s</title><link>%s</link>'
            '<guid isPermaLink="true">%s</guid>%s'
            "<description>%s</description></item>"
            % (html.escape(m["title"]), html.escape(link, quote=True),
               html.escape(link, quote=True), pub, html.escape(desc)))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<rss version="2.0"><channel>\n'
           "<title>%s</title>\n<link>%s</link>\n<description>%s</description>\n"
           "%s\n</channel></rss>\n"
           % (html.escape(journal["title"]),
              html.escape(journal["base_url"] + "/", quote=True),
              html.escape("Occasional computer-security research previews, "
                          "posted for public commentary."),
              "\n".join(items)))
    with open(os.path.join(out_dir, "feed.xml"), "w", encoding="utf-8") as fh:
        fh.write(xml)


FAVICON_PNG_SIZE = 512  # == dist_ai.webcheck.site.FAVICON_SIZE (check_seo gate)


def _rsvg_png(svg_path, size, dst):
    # Rasterize an SVG to a square PNG via rsvg-convert -- the same tool the
    # family sites' site-generate uses. PNG bytes are not reproducible across
    # librsvg versions, so checks gate size + completeness, never bytes.
    subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size),
                    "-o", dst, svg_path], check=True)


def write_icons(out_dir, journal):
    """favicon (SVG + raster renders), the og.png social card, and the PWA
    manifest. The SVG favicon is declared in every head so the browser never
    probes /favicon.ico (a strict-CSP console error); the raster sizes feed
    apple-touch + the manifest; og.png backs og:image / twitter:image."""
    from jmaker.templates import FAVICON_SVG, OG_SVG
    adir = os.path.join(out_dir, "assets")
    svg = os.path.join(adir, "favicon.svg")
    with open(svg, "w", encoding="utf-8") as fh:
        fh.write(FAVICON_SVG)
    _rsvg_png(svg, FAVICON_PNG_SIZE, os.path.join(adir, "favicon.png"))
    _rsvg_png(svg, 192, os.path.join(adir, "icon-192.png"))
    _rsvg_png(svg, 512, os.path.join(adir, "icon-maskable.png"))
    # Transient og source (title interpolated), rasterized then dropped -- only
    # og.png ships (the leading-dot name also keeps it out of any .svg scan).
    og_svg = os.path.join(adir, ".og.svg")
    # Fit the title to the card's ~1020px text column (x=90..1110) so a long
    # title does not overflow the 1200px canvas. sans-serif 700 averages
    # ~0.6em/char; never enlarge past the 70px design size, and floor at 30px
    # (a title long enough to need smaller fits on one line regardless).
    title = journal["title"]
    fontsize = max(30, min(70, int(1020 / (0.6 * max(len(title), 1)))))
    with open(og_svg, "w", encoding="utf-8") as fh:
        fh.write(OG_SVG % {"title": html.escape(title), "fontsize": fontsize})
    subprocess.run(["rsvg-convert", "-w", "1200", "-h", "630",
                    "-o", os.path.join(adir, "og.png"), og_svg], check=True)
    os.remove(og_svg)
    initials = "".join(w[0] for w in journal["title"].split() if w)[:4].upper()
    manifest = {
        "name": journal["title"],
        "short_name": initials or journal["title"][:12],
        "description": "Occasional computer-security research previews for "
                       "public commentary.",
        # Track base_url's path (via _site_root) so a subpath/project-page deploy
        # (https://host/repo) launches + scopes to /repo/, not the origin root.
        "start_url": _site_root(journal),
        "scope": _site_root(journal),
        "display": "standalone",
        "theme_color": "#0b5cad",
        "background_color": "#fdfdfc",
        "icons": [
            {"src": "favicon.svg", "type": "image/svg+xml", "sizes": "any"},
            {"src": "icon-192.png", "type": "image/png", "sizes": "192x192"},
            {"src": "favicon.png", "type": "image/png", "sizes": "512x512"},
            {"src": "icon-maskable.png", "type": "image/png",
             "sizes": "512x512", "purpose": "maskable"},
        ],
    }
    with open(os.path.join(adir, "manifest.webmanifest"), "w",
              encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")


def write_robots(journal, out_dir):
    # Byte-identical to dist_ai.webcheck.site.render_robots. Always allows
    # crawling HTML so each page's <meta noindex> is read (a crawler must fetch a
    # page to honor its meta), and advertises the sitemap. A no-index build ALSO
    # Disallows PDFs: a PDF carries no noindex meta and GitHub Pages serves no
    # X-Robots-Tag, so a crawl block is the only Pages-compatible lever. It keeps
    # PDF CONTENT out of search (uncrawled -> no snippet/indexed text); it does
    # NOT guarantee the bare URL never appears if externally linked (a known
    # robots limitation), but the interim host is unlinked. Users still download
    # it (robots binds crawlers, not browsers).
    lines = ["User-agent: *", "Allow: /"]
    if journal.get("_no_index"):
        lines.append("Disallow: /*.pdf$")
    txt = "\n".join(lines) + "\n\nSitemap: %s/sitemap.xml\n" % journal["base_url"]
    with open(os.path.join(out_dir, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write(txt)


# ---------------------------------------------------------------- driver

def _is_within(path, parent):
    try:
        return os.path.commonpath([path, parent]) == parent and path != parent
    except ValueError:
        return False


def build(articles_dir, journal_toml, out_dir, skip_pdf=False, publish=False):
    journal = load_journal(journal_toml)
    # Non-indexable by DEFAULT: a draft or interim host must never be crawled.
    # Indexability is an explicit, trust-bearing opt-in (--publish) for the
    # canonical host only.
    journal["_no_index"] = not publish

    # The output dir is wiped (rmtree); refuse only when that would DELETE a
    # source -- out == / contains articles or the content root, or out is inside
    # articles. A normal _site inside the content repo is fine.
    # realpath (not abspath) so a symlinked parent cannot alias past the guard.
    out_abs = os.path.realpath(out_dir)
    articles_abs = os.path.realpath(articles_dir)
    content_root = os.path.dirname(os.path.realpath(journal_toml))
    pages_abs = os.path.join(content_root, "pages")
    for src in (articles_abs, content_root, pages_abs):
        if out_abs == src or _is_within(src, out_abs):
            raise BuildError("refusing to build: output dir %r would delete "
                             "source %r" % (out_dir, src))
    if _is_within(out_abs, articles_abs):
        raise BuildError("refusing to build: output dir %r is inside the "
                         "articles dir %r" % (out_dir, articles_abs))

    adirs = sorted(
        os.path.join(articles_dir, d) for d in os.listdir(articles_dir)
        if os.path.isdir(os.path.join(articles_dir, d))
        and os.path.isfile(os.path.join(articles_dir, d, "meta.toml")))
    if not adirs:
        raise BuildError("no articles with meta.toml under %s" % articles_dir)

    articles = [load_article(d) for d in adirs]

    # Flat routes share one <slug>/ namespace, so an article slug must not
    # collide with another article, a standalone page, or the browse/assets
    # routes -- the build would otherwise overwrite one with another and the
    # homepage/sitemap would point at the wrong target. Reject up front.
    page_slugs = [fn[:-3] for fn in sorted(os.listdir(pages_abs))
                  if fn.endswith(".md")] if os.path.isdir(pages_abs) else []
    route_owner: dict[str, str] = {}
    claims = ([("reserved route", r) for r in ("browse", "assets")]
              + [(m["_dir"], _rel_dir(m)) for m in articles]
              + [("page %s.md" % s, s) for s in page_slugs])
    for owner, route in claims:
        if route in route_owner:
            raise BuildError("route collision at %r: %s and %s"
                             % (route, route_owner[route], owner))
        route_owner[route] = owner
    article_routes = [_rel_dir(m) for m in articles]

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    urls = [journal["base_url"] + "/"]
    # Prev/next neighbours in reading order (volume, issue, article number/slug).
    ordered = sorted(articles, key=_order_key)
    nbr = {}
    for i, a in enumerate(ordered):
        nbr[_rel_dir(a)] = (ordered[i - 1] if i > 0 else None,
                            ordered[i + 1] if i < len(ordered) - 1 else None)
    for m in articles:
        rel_dir, pdf_name, page = render_article(
            m, journal, nbr.get(_rel_dir(m)), skip_pdf=skip_pdf)
        dest = os.path.join(out_dir, rel_dir)
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page)
        # Per-article source-quotes.md reviewer aid -> a read-only HTML page at
        # <slug>/sources/, linked from the article. It is a real navigable page, so
        # it goes in the sitemap like every other page: webcheck's seo_page_urls
        # includes every HTML page except the ephemeral RESULTS_SUBDIR (a noindex
        # meta does NOT drop a page), and the 'previews' SEO check asserts our
        # sitemap.xml == its render_sitemap -- omitting it would read as stale.
        if os.path.exists(os.path.join(m["_dir"], "source-quotes.md")):
            s_rel, s_page = render_sources(m, journal)
            s_dest = os.path.join(out_dir, s_rel)
            os.makedirs(s_dest, exist_ok=True)
            with open(os.path.join(s_dest, "index.html"), "w",
                      encoding="utf-8") as fh:
                fh.write(s_page)
            urls.append("%s/%s/" % (journal["base_url"], s_rel))
        figdir = os.path.join(m["_dir"], "figures")
        if os.path.islink(figdir):
            raise BuildError("figures/ must not be a symlink: %s" % figdir)
        if os.path.isdir(figdir):
            for froot, fdirs, ffiles in os.walk(figdir):
                for nm in fdirs + ffiles:
                    if os.path.islink(os.path.join(froot, nm)):
                        raise BuildError("symlink in figures not allowed: %s"
                                         % os.path.join(froot, nm))
            shutil.copytree(figdir, os.path.join(dest, "figures"))
        urls.append("%s/%s/" % (journal["base_url"], rel_dir))
        if not skip_pdf:
            pdf_path = os.path.join(dest, pdf_name)
            md_to_pdf(m, journal, pdf_path)
            h = hashlib.sha256()
            with open(pdf_path, "rb") as pf:
                for chunk in iter(lambda: pf.read(65536), b""):
                    h.update(chunk)
            with open(pdf_path + ".sha256", "w", encoding="utf-8") as sf:
                sf.write("%s  %s\n" % (h.hexdigest(), pdf_name))  # sha256sum format
            # The PDF is NOT added to the sitemap: it lists HTML navigable pages
            # only (byte-identical to dist_ai.webcheck.site.seo_page_urls, which
            # the 'previews' policy re-derives and compares). The PDF stays
            # discoverable via its landing page's download link, and a no-index
            # build's robots Disallows /*.pdf$ -- advertising it in the sitemap
            # would contradict that.

    # Standalone pages (about, policies, license) from <content>/pages/*.md.
    pages = []
    pages_dir = os.path.join(os.path.dirname(os.path.abspath(journal_toml)),
                             "pages")
    if os.path.isdir(pages_dir):
        for fn in sorted(os.listdir(pages_dir)):
            if not fn.endswith(".md"):
                continue
            slug = fn[:-3]
            with open(os.path.join(pages_dir, fn), "r", encoding="utf-8") as fh:
                title, page = render_page(slug, fh.read(), journal)
            pdir = os.path.join(out_dir, slug)
            os.makedirs(pdir, exist_ok=True)
            with open(os.path.join(pdir, "index.html"), "w",
                      encoding="utf-8") as fh:
                fh.write(page)
            pages.append((slug, title))
            urls.append("%s/%s/" % (journal["base_url"], slug))

    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render_homepage(articles, journal, pages))

    browse_dir = os.path.join(out_dir, "browse")
    os.makedirs(browse_dir, exist_ok=True)
    with open(os.path.join(browse_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render_browse(articles, journal))
    urls.append("%s/browse/" % journal["base_url"])

    os.makedirs(os.path.join(out_dir, "assets"), exist_ok=True)
    from jmaker.templates import STYLE_CSS, SITE_JS
    with open(os.path.join(out_dir, "assets", "style.css"), "w",
              encoding="utf-8") as fh:
        fh.write(STYLE_CSS)
    with open(os.path.join(out_dir, "assets", "site.js"), "w",
              encoding="utf-8") as fh:
        fh.write(SITE_JS)
    write_icons(out_dir, journal)

    write_sitemap(urls, out_dir)
    write_feed(articles, journal, out_dir)
    write_headers(out_dir)
    write_robots(journal, out_dir)

    # Carry the served-tree web-tests policy into the build so the consistency
    # suite reads it from _site/.github/web-tests.yml (else it defaults to the
    # wrong policy). content_root is the dir holding site.toml.
    gh_dir = os.path.join(out_dir, ".github")
    os.makedirs(gh_dir, exist_ok=True)
    wt_src = os.path.join(content_root, ".github", "web-tests.yml")
    if os.path.isfile(wt_src):
        shutil.copyfile(wt_src, os.path.join(gh_dir, "web-tests.yml"))
    # Per-file vendor-mention allowlist manifest: {dir-key -> [phrases]}, where
    # the key is an article's rel dir (v<N>/i<M>/<slug>) or a page slug. The gate
    # applies an entry ONLY to files in that dir, so one article's or page's
    # allowance never licenses a mention anywhere else. Absent/empty = strictest.
    vendor_manifest = {}
    for m in articles:
        av = m.get("allow_vendor_mentions")
        if not av:
            continue
        vendor_manifest[_rel_dir(m)] = av
        # The <slug>/sources/ reviewer-aid page renders the sidecar verbatim, so
        # it shares the article's allowance -- its own dir is a distinct per-file
        # key, else an allow-listed phrase quoted in the sidecar would be flagged.
        if os.path.exists(os.path.join(m["_dir"], "source-quotes.md")):
            vendor_manifest[_rel_dir(m) + "/sources"] = av
    for slug, _title in pages:
        ph = journal["page_allow_vendor_mentions"].get(slug)
        if ph:
            vendor_manifest[slug] = ph
    with open(os.path.join(gh_dir, "vendor-allowlist.json"), "w",
              encoding="utf-8") as fh:
        json.dump(vendor_manifest, fh)
    # Article-route manifest: check.py discovers article landing pages from this,
    # NOT from an in-page marker, so discovery never depends on the very
    # article_status meta that check_article validates (a page that lost the meta
    # must be a HARD error, not a silently-skipped non-article).
    with open(os.path.join(gh_dir, "articles.json"), "w", encoding="utf-8") as fh:
        json.dump(sorted(article_routes), fh)
    open(os.path.join(out_dir, ".nojekyll"), "w").close()

    return len(articles), out_dir
