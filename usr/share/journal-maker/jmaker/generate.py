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
        if not j.get(req):
            raise BuildError("site.toml missing required key: %s" % req)
    # base_url must be absolute (Scholar requires absolute citation_pdf_url) and
    # free of whitespace/newlines (it is interpolated into robots.txt + sitemap).
    if not re.fullmatch(r"https?://[^/\s]+(/[^\s]*)?", j["base_url"]):
        raise BuildError("site.toml: base_url must be an absolute http(s) URL "
                         "with a host and no whitespace, got %r" % j["base_url"])
    j["base_url"] = j["base_url"].rstrip("/")
    j.setdefault("issn", "")
    j.setdefault("language", "en")
    j.setdefault("publisher", j["title"])
    j.setdefault("license", "")
    j.setdefault("license_url", "")
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


def _sanitize_html(frag):
    frag = _DANGEROUS_URL_RE.sub(r"\1#", frag)
    frag = _EVENT_ATTR_RE.sub("", frag)
    # Strict CSP is style-src 'self': an inline style attribute is BLOCKED (never
    # applied) and logs a console error. Pandoc emits them on table parts (col
    # width, cell align), so strip every inline style -- styling belongs in the
    # stylesheet, and a blocked style was dead weight anyway. Skip code spans so a
    # displayed HTML sample keeps its literal style="..." (pandoc entity-escapes
    # quotes inside code, but guard explicitly).
    frag = _sub_outside(_HTML_CODE_RE, lambda s: _STYLE_ATTR_RE.sub("", s), frag)
    return frag


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


def md_to_html_fragment(md_text):
    # Disable: raw_html (author <script> becomes text); smart (keep output ASCII
    # -- smart would emit curly quotes / en-dashes); and the attribute extensions
    # that let author Markdown attach arbitrary HTML attributes such as an
    # onerror handler on an image. _sanitize_html is the backstop for any
    # residual event-handler attribute or dangerous URL scheme.
    fmt = ("markdown-raw_html-smart-raw_attribute-link_attributes"
           "-native_divs-native_spans")
    r = _run(["pandoc", "-f", fmt, "-t", "html5", "--wrap=none"], input=md_text)
    return _endash_html(_sanitize_html(r.stdout))


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
        _run([
            "pandoc", "-f", "markdown-raw_tex-smart-raw_attribute", "-o", out_pdf,
            "--pdf-engine=pdflatex",
            "--include-in-header", hdr.name,
            "--resource-path", m["_dir"],
            "-V", "geometry:margin=1in",
            "-V", "fontsize=11pt",
            "-V", "linkcolor=blue",
            "-V", "urlcolor=blue",
        ], input=doc, env=env)
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
    add("citation_journal_title", journal["title"])
    if journal.get("issn"):
        add("citation_issn", journal["issn"])
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
        "img-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'; object-src 'none'; "
        "require-trusted-types-for 'script'; trusted-types 'none'")


def _csp_meta():
    """The <meta http-equiv> policy: the header minus frame-ancestors, which a
    meta tag cannot set."""
    return (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; base-uri 'none'; form-action 'none'; "
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
        '<link rel="icon" type="image/svg+xml" href="%sassets/favicon.svg">\n'
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
        extra_head, root_rel, root_rel, root_rel,
        site_header(journal["title"], _site_root(journal)), body,
        site_footer(journal, root_rel),
    )


# A bare URL in a reference entry (pandoc already entity-escaped any &); not
# preceded by " or > so a URL already inside an href/anchor is left alone.
_REF_URL_RE = re.compile(r'(?<![">])(https?://[^\s<]+)')


def _anchor(href_url, text=None, trail=""):
    # Linkify runs AFTER _sanitize_html on pandoc output, so '&', '<', '>' are
    # already entity-escaped -- re-escaping would double them (&amp; -> &amp;amp;).
    # Only '"' is left literal by pandoc in body text, and an unescaped '"' here
    # would close the href early and smuggle an attribute past the sanitizer, so
    # neutralize just that one.
    if text is None:
        text = href_url

    def q(s):
        return s.replace('"', "&quot;")
    return '<a href="%s">%s</a>%s' % (q(href_url), q(text), trail)


def _linkify_refs(refs):
    """Turn plain-text DOIs and URLs in reference entries into links."""
    refs = re.sub(
        r'\bdoi:\s*(10\.[^\s<]+)',
        lambda x: 'doi: ' + _anchor("https://doi.org/" + x.group(1).rstrip("."),
                                    x.group(1).rstrip(".")), refs, flags=re.I)

    def _url(x):
        url, trail = x.group(1), ""
        # Strip trailing sentence punctuation, but keep a ')' that closes a '('
        # inside the URL itself (e.g. a Wikipedia '..._(disambiguation)' link).
        while url:
            ch = url[-1]
            if ch in ".,;":
                trail = ch + trail
                url = url[:-1]
                continue
            if ch == ")" and url.count("(") < url.count(")"):
                trail = ch + trail
                url = url[:-1]
                continue
            break
        return _anchor(url, trail=trail)
    return _REF_URL_RE.sub(_url, refs)


def _linkify_citations(body_html):
    """Link in-text [n] to #ref-n (first mention gets a back-anchor id), anchor
    each reference entry with a backlink to its first mention, and turn plain
    DOIs/URLs in references into links."""
    mo = re.search(r'(<h2[^>]*>\s*References\s*</h2>)', body_html, re.I)
    head = body_html if mo is None else body_html[:mo.start()]
    refs = "" if mo is None else body_html[mo.start():]
    seen: set = set()

    def _cite(x):
        n = x.group(1)
        if n in seen:
            return '<a class="cite" href="#ref-%s">[%s]</a>' % (n, n)
        seen.add(n)
        return ('<a class="cite" id="cite-%s" href="#ref-%s">[%s]</a>'
                % (n, n, n))
    # Only a lone [n] is a citation, and only OUTSIDE code spans -- so an array
    # index such as arr[2] in a <code> block is not linkified. Combined/range
    # forms ([1, 2], [1-3]) are intentionally NOT auto-linkified: they are
    # indistinguishable from an ordinary prose number range (a byte range
    # [0-15], a coordinate [3, 4]) and guessing wrong fails the build.
    head = _sub_outside(_HTML_CODE_RE,
                        lambda s: re.sub(r"\[(\d+)\]", _cite, s), head)

    def _refs_to_ol(m):
        def _li(x):
            n = x.group(1)
            content = x.group(2).rstrip()
            back = ('<a class="backref" href="#cite-%s" '
                    'aria-label="back to citation">&#8617;</a> ' % n) if n in seen \
                else ""
            # Emit the visible "[n]" as literal text, NOT a CSS list counter, so the
            # displayed number always equals the citation key n -- even when the
            # reference list is not authored in 1,2,3 order.
            return '<li id="ref-%s">[%s] %s%s</li>' % (n, n, back, content)
        lis = re.sub(r'<p>\s*\[(\d+)\]\s*(.*?)</p>\s*', _li, m.group(0), flags=re.S)
        return '\n<ol class="references">\n' + lis.rstrip() + '\n</ol>\n'
    # Convert EVERY consecutive run of reference paragraphs after the References
    # heading (each run -> its own <ol>), so a reference separated from the main
    # block by an interrupting paragraph is still wrapped and anchored (id="ref-n")
    # and its in-text citation does not dangle. References is the last section, so
    # `refs` spans it to end of document; there is no later section whose "[k]"
    # lines this could wrongly capture.
    refs = re.sub(r'(?:<p>\s*\[\d+\]\s*.*?</p>\s*)+', _refs_to_ol, refs,
                  flags=re.S)
    return head + _linkify_refs(refs)


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
    fields = [
        ("author", " and ".join(a["name"] for a in m["authors"])),
        ("title", m["title"]),
        ("journal", journal["title"]),
        ("year", m["date"][:4]),
    ]
    fields.append(("doi", m["doi"]) if m.get("doi") else ("url", landing_url))
    body = ",\n".join("  %s = {%s}" % (k, v) for k, v in fields)
    return "@article{%s,\n%s\n}" % (key, body)


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


def _opengraph(m, journal, landing_url, description):
    """OpenGraph + Twitter-card meta: web search and social link previews.
    (These are NOT read by Google Scholar -- the citation_* tags serve that.)"""
    def t(key, content, attr="property"):
        return ('<meta %s="%s" content="%s">'
                % (attr, key, html.escape(str(content), quote=True)))
    return "\n".join([
        t("og:type", "article"),
        t("og:title", m["title"]),
        t("og:description", description),
        t("og:url", landing_url),
        t("og:site_name", journal["title"]),
        t("twitter:card", "summary", attr="name"),
        t("twitter:title", m["title"], attr="name"),
        t("twitter:description", description, attr="name"),
    ])


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
    lines = ["TY  - JOUR"]
    lines += ["AU  - " + a["name"] for a in m["authors"]]
    lines += ["TI  - " + m["title"], "JO  - " + journal["title"],
              "PY  - " + m["date"][:4]]
    if m.get("article_number"):
        lines.append("M1  - " + m["article_number"])
    if m.get("doi"):
        lines.append("DO  - " + m["doi"])
    lines.append("UR  - " + ("https://doi.org/" + m["doi"]
                             if m.get("doi") else landing_url))
    lines.append("ER  - ")
    return "\n".join(lines)


def _apa(m, journal, year):
    authors = ", ".join(a["name"] for a in m["authors"])
    art = (", Article %s" % m["article_number"]) if m.get("article_number") else ""
    src = (" https://doi.org/%s" % m["doi"]) if m.get("doi") else ""
    return "%s (%s). %s. %s%s.%s" % (
        authors, year, m["title"], journal["title"], art, src)


def _ieee_cite(m, journal, year):
    authors = ", ".join(a["name"] for a in m["authors"])
    artno = (", Art. no. %s" % m["article_number"]) if m.get("article_number") \
        else ""
    tail = (", doi: %s" % m["doi"]) if m.get("doi") else ""
    return '%s, "%s," %s%s, %s%s.' % (
        authors, m["title"], journal["title"], artno, year, tail)


def _cite_box(m, journal, landing_url, year):
    fmts = [
        ("IEEE", _ieee_cite(m, journal, year)),
        ("APA", _apa(m, journal, year)),
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


def render_article(m, journal, neighbors=None):
    rel_dir = _rel_dir(m)
    root_rel = _root_rel(rel_dir)
    landing_url = "%s/%s/" % (journal["base_url"], rel_dir)
    pdf_name = "%s.pdf" % m["slug"]
    pdf_url = landing_url + pdf_name
    description = " ".join(m["abstract"].split())[:300]

    meta = citation_meta(m, journal, landing_url, pdf_url)
    pill, banner, status_line, status_head = _status_fragment(m)
    meta = (meta + "\n" + status_head + "\n"
            + _opengraph(m, journal, landing_url, description) + "\n"
            + _jsonld(m, journal, landing_url))
    body_html = _linkify_citations(md_to_html_fragment(m["_body_md"]))
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
        '<p class="actions"><a href="%s">Download PDF</a> '
        '<a class="checksum" href="%s.sha256">SHA-256</a></p>\n'
        "%s"                                   # cite box (beside the download action)
        '<section class="abstract"><h2>Abstract</h2>%s</section>\n'
        "%s"                                   # toc
        '<article class="body">\n%s\n</article>\n'
        "%s"                                   # statements (data/funding/COI)
        "%s"                                   # prev/next article nav
        "%s\n</main>"                          # license footer
    ) % (banner, pill, html.escape(m["title"]), authors_line, affil_bit, venue,
         doi_bit, history, subjects, ccs, status_line, pdf_name, pdf_name,
         cite_box, abstract_html, toc, body_html, statements,
         _article_nav(neighbors, root_rel), license_bit)

    page = _page(
        m.get("language", journal["language"]),
        "%s -- %s" % (m["title"], journal["title"]),
        description, landing_url, meta, main, journal, root_rel)
    return rel_dir, pdf_name, page


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
    main = ('<main id="main" class="page">\n<h1>%s</h1>\n%s\n</main>'
            % (html.escape(title), body_html))
    page = _page(journal["language"], "%s -- %s" % (title, journal["title"]),
                 title, canonical, "", main, journal, "../")
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
    return _page(journal["language"], journal["title"],
                 "Occasional computer-security research previews for public "
                 "commentary.",
                 journal["base_url"] + "/", "", body, journal, "")


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
    return _page(journal["language"], "Browse -- %s" % journal["title"],
                 "Browse articles by keyword and author.",
                 journal["base_url"] + "/browse/", "", body, journal, "../")


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


def write_robots(journal, out_dir):
    # Byte-identical to dist_ai.webcheck.site.render_robots. Always allows
    # crawling and advertises the sitemap; a no-index page keeps itself out of
    # indexes via its per-page <meta noindex> (which a crawler must be allowed to
    # fetch to honor), so robots never Disallows. Blank line before Sitemap
    # matches webcheck's canonical render_robots.
    txt = ("User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n"
           % journal["base_url"])
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
        rel_dir, pdf_name, page = render_article(m, journal, nbr.get(_rel_dir(m)))
        dest = os.path.join(out_dir, rel_dir)
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page)
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
            urls.append("%s/%s/%s" % (journal["base_url"], rel_dir, pdf_name))

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
    from jmaker.templates import STYLE_CSS, SITE_JS, FAVICON_SVG
    with open(os.path.join(out_dir, "assets", "style.css"), "w",
              encoding="utf-8") as fh:
        fh.write(STYLE_CSS)
    with open(os.path.join(out_dir, "assets", "site.js"), "w",
              encoding="utf-8") as fh:
        fh.write(SITE_JS)
    # Declared in every page head so the browser never probes /favicon.ico (a
    # 404 that a strict-CSP page logs as a console error). SVG scales to any size.
    with open(os.path.join(out_dir, "assets", "favicon.svg"), "w",
              encoding="utf-8") as fh:
        fh.write(FAVICON_SVG)

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
        if m.get("allow_vendor_mentions"):
            vendor_manifest[_rel_dir(m)] = m["allow_vendor_mentions"]
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
