#!/usr/bin/python3 -Bsu
"""Build a static, Google-Scholar-indexable journal site from Markdown.

Contract per article:
  articles/<slug>/paper.md   -- the paper in Markdown: the H1 ('# Title') and a
                                 '## Abstract' section are the SINGLE SOURCE for
                                 title + abstract; the body is everything from
                                 the first section heading after the abstract.
                                 (title/abstract are parsed here, NOT meta.toml.)
  articles/<slug>/meta.toml  -- the remaining bibliographic metadata (authors,
                                 dates, volume/issue, doi, keywords, license).
  articles/<slug>/source.mw  -- optional pristine wiki fork (ignored by build)
  articles/<slug>/figures/   -- optional images, copied verbatim

Output tree (served at the site root):
  index.html                 -- journal homepage
  v<N>/index.html            -- per-volume browse (every article <=2 links from home)
  v<N>/i<M>/<slug>/index.html-- article landing page == full HTML article + meta
  v<N>/i<M>/<slug>/<slug>.pdf-- camera-ready PDF in the SAME directory
  assets/style.css, robots.txt, sitemap.xml, .nojekyll

PDF and HTML both derive from meta.toml + paper.md, so citation_title always
matches the visible title and the abstract is always both visible and in meta.
"""

import datetime
import html
import os
import re
import shutil
import subprocess
import sys
import tomllib


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- loading

def load_journal(path):
    with open(path, "rb") as fh:
        j = tomllib.load(fh)
    for req in ("title", "base_url"):
        if not j.get(req):
            raise BuildError("journal.toml missing required key: %s" % req)
    # base_url must be absolute (Scholar requires absolute citation_pdf_url) and
    # free of whitespace/newlines (it is interpolated into robots.txt + sitemap).
    if not re.fullmatch(r"https?://[^/\s]+(/[^\s]*)?", j["base_url"]):
        raise BuildError("journal.toml: base_url must be an absolute http(s) URL "
                         "with a host and no whitespace, got %r" % j["base_url"])
    j["base_url"] = j["base_url"].rstrip("/")
    j.setdefault("issn", "")
    j.setdefault("language", "en")
    j.setdefault("publisher", j["title"])
    j.setdefault("license", "")
    j.setdefault("license_url", "")
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
    # cannot traverse out of the output tree or inject into an href.
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(m["slug"])):
        raise BuildError("%s/meta.toml: slug must match [a-z0-9][a-z0-9-]*, got %r"
                         % (adir, m["slug"]))
    m["title"] = title
    m["abstract"] = abstract
    for req in ("authors", "date", "volume", "issue"):
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
    for key in ("volume", "issue"):
        val = m[key]
        # bool is an int subclass; a float (1.5) or a non-digit string is not a
        # valid volume/issue. Coerce the accepted forms to a real int.
        if isinstance(val, bool) or not (isinstance(val, int)
                or (isinstance(val, str) and val.isdigit())):
            raise BuildError("%s/meta.toml: %s must be an integer" % (adir, key))
        m[key] = int(val)
        if m[key] < 1:
            raise BuildError("%s/meta.toml: %s must be a positive integer" % (adir, key))
    if "keywords" in m and not isinstance(m["keywords"], list):
        raise BuildError("%s/meta.toml: keywords must be a list" % adir)
    # Coerce dates to ISO strings: unquoted TOML dates parse as datetime.date,
    # which would crash _scholar_date. Validate the shape here, loudly.
    for key in ("date", "online_date"):
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
    return "v%d/i%d/%s" % (int(m["volume"]), int(m["issue"]), m["slug"])


def _root_rel(rel_dir):
    """'../' repeated to climb from an article dir back to the site root."""
    depth = rel_dir.count("/") + 1
    return "../" * depth


# Neutralize dangerous URL schemes in generated href/src (defense in depth;
# raw HTML passthrough is already disabled in the reader).
_DANGEROUS_URL_RE = re.compile(
    r'((?:href|src)\s*=\s*")\s*(?:javascript|vbscript|data)\s*:', re.I)
_EVENT_ATTR_RE = re.compile(
    r'\son[a-z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.I)


def _sanitize_html(frag):
    frag = _DANGEROUS_URL_RE.sub(r"\1#", frag)
    frag = _EVENT_ATTR_RE.sub("", frag)
    return frag


def md_to_html_fragment(md_text):
    # Disable: raw_html (author <script> becomes text); smart (keep output ASCII
    # -- smart would emit curly quotes / en-dashes); and the attribute extensions
    # that let author Markdown attach arbitrary HTML attributes such as an
    # onerror handler on an image. _sanitize_html is the backstop for any
    # residual event-handler attribute or dangerous URL scheme.
    fmt = ("markdown-raw_html-smart-raw_attribute-link_attributes"
           "-native_divs-native_spans")
    r = _run(["pandoc", "-f", fmt, "-t", "html5", "--wrap=none"], input=md_text)
    return _sanitize_html(r.stdout)


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
    doc = meta_block + doi_line + m["_body_md"]
    # -raw_tex: author raw TeX (e.g. \input{/etc/passwd}) is not passed to the
    # engine. openin_any/openout_any=p additionally bar the engine from reading
    # or writing files outside the tree, in case any TeX slips through.
    env = dict(os.environ, openin_any="p", openout_any="p")
    _run([
        "pandoc", "-f", "markdown-raw_tex-smart", "-o", out_pdf,
        "--pdf-engine=pdflatex",
        "--resource-path", m["_dir"],
        "-V", "geometry:margin=1in",
        "-V", "fontsize=11pt",
        "-V", "linkcolor=blue",
        "-V", "urlcolor=blue",
    ], input=doc, env=env)


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
    add("citation_volume", m["volume"])
    add("citation_issue", m["issue"])
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
        "%s"
        "<title>%s</title>\n"
        '<meta name="description" content="%s">\n'
        '<link rel="canonical" href="%s">\n'
        "%s\n"
        '<link rel="stylesheet" href="%sassets/style.css">\n'
        "</head>\n<body>\n%s\n%s\n%s\n</body>\n</html>\n"
    ) % (
        html.escape(lang), robots, html.escape(head_title),
        html.escape(description),
        html.escape(canonical, quote=True), extra_head, root_rel,
        site_header(root_rel, journal["title"]), body,
        site_footer(journal["title"], journal.get("issn", "")),
    )


def _linkify_citations(body_html):
    """Link in-text [n] to #ref-n and anchor each reference entry."""
    mo = re.search(r'(<h2[^>]*>\s*References\s*</h2>)', body_html, re.I)
    head = body_html if mo is None else body_html[:mo.start()]
    refs = "" if mo is None else body_html[mo.start():]
    head = re.sub(r'\[(\d+)\]',
                  lambda x: '<a class="cite" href="#ref-%s">[%s]</a>'
                  % (x.group(1), x.group(1)), head)
    refs = re.sub(r'<p>\s*\[(\d+)\]',
                  lambda x: '<p id="ref-%s">[%s]' % (x.group(1), x.group(1)), refs)
    return head + refs


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
    return ('<nav class="toc"><div class="toc-label">Contents</div>\n<ol>\n%s\n'
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
        ("volume", str(m["volume"])),
        ("number", str(m["issue"])),
    ]
    fields.append(("doi", m["doi"]) if m.get("doi") else ("url", landing_url))
    body = ",\n".join("  %s = {%s}" % (k, v) for k, v in fields)
    return "@article{%s,\n%s\n}" % (key, body)


def render_article(m, journal):
    rel_dir = _rel_dir(m)
    root_rel = _root_rel(rel_dir)
    landing_url = "%s/%s/" % (journal["base_url"], rel_dir)
    pdf_name = "%s.pdf" % m["slug"]
    pdf_url = landing_url + pdf_name

    meta = citation_meta(m, journal, landing_url, pdf_url)
    body_html = _linkify_citations(md_to_html_fragment(m["_body_md"]))
    abstract_html = md_to_html_fragment(m["abstract"])
    toc = _build_toc(body_html)

    authors_line = ", ".join(html.escape(a["name"]) for a in m["authors"])
    affils = []
    for a in m["authors"]:
        inst = a.get("institution")
        if inst and inst not in affils:
            affils.append(inst)
    affil_bit = ('<p class="affil">%s</p>\n'
                 % "; ".join(html.escape(x) for x in affils)) if affils else ""
    year = m["date"][:4]
    venue = "%s, Volume %s, Issue %s (%s)" % (
        html.escape(journal["title"]), html.escape(str(m["volume"])),
        html.escape(str(m["issue"])), html.escape(year))
    doi_bit = ""
    if m.get("doi"):
        doi_bit = ' &middot; DOI: <a href="https://doi.org/%s">%s</a>' % (
            html.escape(m["doi"], quote=True), html.escape(m["doi"]))
    license_bit = ""
    lic = m.get("license", journal.get("license", ""))
    lic_url = journal.get("license_url", "")
    if lic:
        if lic_url:
            license_bit = ('<footer class="license">Licensed under '
                           '<a href="%s">%s</a>.</footer>'
                           % (html.escape(lic_url, quote=True), html.escape(lic)))
        else:
            license_bit = ('<footer class="license">Licensed under %s.</footer>'
                           % html.escape(lic))

    bibtex = _bibtex(m, journal, landing_url)
    authors_plain = ", ".join(a["name"] for a in m["authors"])
    plain_cite = '%s. "%s." %s, vol. %s, no. %s, %s.' % (
        authors_plain, m["title"], journal["title"], m["volume"], m["issue"], year)
    cite_box = ('<details class="cite-this"><summary>Cite this</summary>\n'
                "<p>%s</p>\n<pre>%s</pre>\n</details>\n"
                % (html.escape(plain_cite), html.escape(bibtex)))

    main = (
        '<main class="article">\n'
        '<h1 class="title">%s</h1>\n'
        '<p class="authors">%s</p>\n'
        "%s"
        '<p class="venue">%s%s</p>\n'
        '<p class="actions"><a href="%s">Download PDF</a></p>\n'
        '<section class="abstract"><h2>Abstract</h2>%s</section>\n'
        "%s%s"
        '<article class="body">\n%s\n</article>\n'
        "%s\n</main>"
    ) % (html.escape(m["title"]), authors_line, affil_bit, venue, doi_bit,
         pdf_name, abstract_html, toc, cite_box, body_html, license_bit)

    description = " ".join(m["abstract"].split())[:300]
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
    main = ('<main class="page">\n<h1>%s</h1>\n%s\n</main>'
            % (html.escape(title), body_html))
    page = _page(journal["language"], "%s -- %s" % (title, journal["title"]),
                 title, canonical, "", main, journal, "../")
    return title, page


def render_homepage(articles, journal, pages):
    items = []
    by_vol: dict = {}
    for m in articles:
        by_vol.setdefault(int(m["volume"]), []).append(m)
    for vol in sorted(by_vol, reverse=True):
        items.append('<li><a href="v%d/index.html">Volume %d</a> '
                     '(%d article%s)</li>'
                     % (vol, vol, len(by_vol[vol]),
                        "" if len(by_vol[vol]) == 1 else "s"))
    page_nav = ""
    if pages:
        links = "\n".join('<li><a href="%s/index.html">%s</a></li>'
                          % (slug, html.escape(title)) for slug, title in pages)
        page_nav = "<h2>About</h2>\n<ul>\n%s\n</ul>\n" % links
    body = (
        '<main>\n<h1>%s</h1>\n'
        "<p>An open-access journal of computer-security research.</p>\n"
        "<h2>Volumes</h2>\n<ul>\n%s\n</ul>\n%s</main>"
    ) % (html.escape(journal["title"]), "\n".join(items), page_nav)
    return _page(journal["language"], journal["title"],
                 "Open-access computer-security research journal.",
                 journal["base_url"] + "/", "", body, journal, "")


def render_volume(vol, metas, journal):
    metas = sorted(metas, key=lambda m: (int(m["issue"]),
                                         int(m.get("firstpage", 0) or 0)))
    lis = []
    for m in metas:
        rel = _rel_dir(m)
        authors = ", ".join(html.escape(a["name"]) for a in m["authors"])
        # From /v<N>/index.html the article is at i<M>/<slug>/ (same volume dir),
        # so the relative link drops the leading volume segment and NO '../'.
        rel_from_volume = "/".join(rel.split("/")[1:])
        lis.append(
            '<li><div class="atitle"><a href="%s/index.html">%s</a></div>'
            '<div class="ameta">%s &middot; Issue %s</div></li>'
            % (rel_from_volume, html.escape(m["title"]),
               authors, html.escape(str(m["issue"]))))
    body = (
        '<main>\n<h1>Volume %d</h1>\n<ol class="articles">\n%s\n</ol>\n</main>'
    ) % (vol, "\n".join(lis))
    return _page(journal["language"], "Volume %d -- %s" % (vol, journal["title"]),
                 "Volume %d." % vol, "%s/v%d/" % (journal["base_url"], vol),
                 "", body, journal, "../")


def write_sitemap(urls, journal, out_dir):
    entries = "\n".join(
        "  <url><loc>%s</loc></url>" % html.escape(u, quote=True) for u in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           "%s\n</urlset>\n") % entries
    with open(os.path.join(out_dir, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write(xml)


def write_robots(journal, out_dir):
    if journal.get("_no_index"):
        # Interim / non-canonical host: keep every URL out of all indexes, so
        # no non-permanent address is ever crawled (Scholar forbids URL changes).
        txt = "User-agent: *\nDisallow: /\n"
    else:
        txt = ("User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n"
               % journal["base_url"])
    with open(os.path.join(out_dir, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write(txt)


# ---------------------------------------------------------------- driver

def _is_within(path, parent):
    try:
        return os.path.commonpath([path, parent]) == parent and path != parent
    except ValueError:
        return False


def build(articles_dir, journal_toml, out_dir, skip_pdf=False, no_index=False):
    journal = load_journal(journal_toml)
    journal["_no_index"] = no_index

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

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    urls = [journal["base_url"] + "/"]
    seen = {}
    for m in articles:
        rel_dir, pdf_name, page = render_article(m, journal)
        if rel_dir in seen:
            raise BuildError("duplicate route %s from %s and %s"
                             % (rel_dir, seen[rel_dir], m["_dir"]))
        seen[rel_dir] = m["_dir"]
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
            md_to_pdf(m, journal, os.path.join(dest, pdf_name))
            urls.append("%s/%s/%s" % (journal["base_url"], rel_dir, pdf_name))

    by_vol: dict = {}
    for m in articles:
        by_vol.setdefault(int(m["volume"]), []).append(m)
    for vol, metas in by_vol.items():
        vdir = os.path.join(out_dir, "v%d" % vol)
        os.makedirs(vdir, exist_ok=True)
        with open(os.path.join(vdir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(render_volume(vol, metas, journal))
        urls.append("%s/v%d/" % (journal["base_url"], vol))

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

    os.makedirs(os.path.join(out_dir, "assets"), exist_ok=True)
    from jmaker.templates import STYLE_CSS
    with open(os.path.join(out_dir, "assets", "style.css"), "w",
              encoding="utf-8") as fh:
        fh.write(STYLE_CSS)

    write_sitemap(urls, journal, out_dir)
    write_robots(journal, out_dir)
    open(os.path.join(out_dir, ".nojekyll"), "w").close()

    return len(articles), out_dir
