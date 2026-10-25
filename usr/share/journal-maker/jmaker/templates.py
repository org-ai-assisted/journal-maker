#!/usr/bin/python3 -Bsu
"""Static HTML skeleton + CSS for the journal site.

ASCII only. Pages are composed in generate.py; this module holds the shared
chrome (stylesheet, site header/footer). Visual spec follows common scholarly
venues (eLife/Nature/Distill/JOSS): serif body + system-sans headings, a ~38rem
measure, one blue accent, off-black on off-white, booktabs tables, hanging-indent
references, light + dark via prefers-color-scheme.
"""

import html

STYLE_CSS = """\
:root {
  color-scheme: light dark;
  --serif: Charter, "Bitstream Charter", "Sitka Text", Cambria, "Iowan Old Style", Georgia, serif;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, "DejaVu Sans Mono", "Liberation Mono", Menlo, monospace;
  --bg: #fdfdfc;
  --surface: #f4f4f1;
  --fg: #1b1b1b;
  --muted: #58585a;
  --accent: #0b5cad;
  --visited: #6b3fa0;
  --rule: #d9d9d4;
  --measure: 38rem;
  --warn-bg: #fdf2d0; --warn-fg: #6b4e00; --warn-rule: #e0b84d;
  --ok-bg: #e4f3e6; --ok-fg: #1d5a2a; --ok-rule: #88c096;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #15171b;
    --surface: #1d2026;
    --fg: #e4e4e0;
    --muted: #a3a7ae;
    --accent: #7db4f0;
    --visited: #b79be0;
    --rule: #32363e;
    --warn-bg: #3a300f; --warn-fg: #f0d78a; --warn-rule: #7a6420;
    --ok-bg: #16301c; --ok-fg: #9fd9ab; --ok-rule: #2f5d39;
  }
}
:root[data-theme="dark"] {
  --bg: #15171b;
  --surface: #1d2026;
  --fg: #e4e4e0;
  --muted: #a3a7ae;
  --accent: #7db4f0;
  --visited: #b79be0;
  --rule: #32363e;
  --warn-bg: #3a300f; --warn-fg: #f0d78a; --warn-rule: #7a6420;
  --ok-bg: #16301c; --ok-fg: #9fd9ab; --ok-rule: #2f5d39;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: var(--serif);
  font-size: 1.125rem;
  line-height: 1.65;
  text-rendering: optimizeLegibility;
  padding: 0 1rem;
}
@media (max-width: 40rem) { body { font-size: 1.0625rem; } }
a { color: var(--accent); text-decoration-thickness: 0.06em; text-underline-offset: 0.15em; }
a:visited { color: var(--visited); }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
header.site, footer.site, main { max-width: var(--measure); margin-inline: auto; }
header.site {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 0.5rem; flex-wrap: wrap;
  font-family: var(--sans); font-size: 0.9rem;
  padding: 1.1rem 0; border-bottom: 1px solid var(--rule);
}
header.site .brand { font-weight: 700; color: var(--fg); text-decoration: none; }
header.site nav a { margin-left: 1rem; }
footer.site {
  font-family: var(--sans); font-size: 0.85rem; color: var(--muted);
  border-top: 1px solid var(--rule); margin-top: 3rem; padding: 1.2rem 0 2.5rem;
}
main { padding: 1.5rem 0; }
h1, h2, h3, h4 { font-family: var(--sans); line-height: 1.25; }
h1.title { font-size: 2.1rem; font-weight: 700; letter-spacing: -0.01em; margin: 0.4rem 0 0.5rem; }
@media (min-width: 55rem) { h1.title { font-size: 2.5rem; } }
article.body h2 { font-size: 1.5rem; font-weight: 650; margin: 2rem 0 0.5rem; }
article.body h3 { font-size: 1.2rem; font-weight: 650; margin: 1.4rem 0 0.4rem; }
p.authors { font-family: var(--sans); font-size: 1.05rem; margin: 0.2rem 0; }
p.affil { font-family: var(--sans); font-size: 0.9rem; color: var(--muted); margin: 0.1rem 0; }
p.venue, p.actions { font-family: var(--sans); font-size: 0.9rem; color: var(--muted); margin: 0.2rem 0; }
p.actions a {
  display: inline-block; margin-top: 0.4rem; padding: 0.35rem 0.8rem;
  background: var(--accent); color: #ffffff; border-radius: 4px;
  text-decoration: none; font-size: 0.9rem;
}
section.abstract {
  margin: 1.5rem 0; padding: 1rem 1.25rem;
  background: var(--surface); border-left: 3px solid var(--accent);
}
section.abstract h2 {
  margin-top: 0; font-size: 0.8rem; font-family: var(--sans);
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
}
nav.toc {
  font-family: var(--sans); font-size: 0.9rem;
  background: var(--surface); border: 1px solid var(--rule); border-radius: 5px;
  padding: 0.8rem 1.1rem; margin: 1.5rem 0;
}
nav.toc .toc-label { font-weight: 650; text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.78rem; color: var(--muted); }
nav.toc ol { margin: 0.4rem 0 0; padding-left: 1.4rem; }
nav.toc li { margin: 0.15rem 0; }
article.body { margin-top: 1.5rem; }
article.body a.cite { text-decoration: none; font-variant-numeric: tabular-nums; }
article.body table { border-collapse: collapse; width: 100%; font-size: 0.95rem; font-variant-numeric: tabular-nums; margin: 1.2rem 0; }
article.body thead th { border-bottom: 2px solid var(--fg); }
article.body table { border-top: 2px solid var(--fg); border-bottom: 2px solid var(--fg); }
article.body th, article.body td { padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }
article.body code { font-family: var(--mono); font-size: 0.875em; background: var(--surface); border: 1px solid var(--rule); padding: 0.1em 0.35em; border-radius: 3px; }
article.body pre { font-family: var(--mono); font-size: 0.85rem; line-height: 1.5; overflow-x: auto; padding: 1rem; background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; tab-size: 4; }
article.body pre code { background: none; border: 0; padding: 0; }
article.body blockquote { margin: 1rem 0; padding-left: 1.25rem; border-left: 3px solid var(--rule); color: var(--muted); }
article.body h2#references ~ p[id^="ref-"], p[id^="ref-"] { padding-left: 2em; text-indent: -2em; font-size: 0.9rem; line-height: 1.5; margin: 0.35rem 0; overflow-wrap: anywhere; }
p[id^="ref-"]:target { background: var(--surface); }
details.cite-this { font-family: var(--sans); font-size: 0.9rem; border: 1px solid var(--rule); border-radius: 5px; padding: 0.6rem 1rem; margin: 1.5rem 0; }
details.cite-this summary { cursor: pointer; font-weight: 650; }
details.cite-this pre { font-family: var(--mono); font-size: 0.8rem; background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; padding: 0.8rem; overflow-x: auto; }
footer.license { font-family: var(--sans); font-size: 0.85rem; color: var(--muted); margin-top: 2rem; border-top: 1px solid var(--rule); padding-top: 0.8rem; }
.status-pill-row { margin: 0.2rem 0 0; }
.status-pill { display: inline-block; font-family: var(--sans); font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; padding: 0.15rem 0.5rem; border-radius: 3px; border: 1px solid var(--rule); }
.status-pill.status-draft { background: var(--warn-bg); color: var(--warn-fg); border-color: var(--warn-rule); }
.status-pill.status-published { background: var(--ok-bg); color: var(--ok-fg); border-color: var(--ok-rule); }
.status-pill.status-corrected { background: var(--surface); color: var(--accent); border-color: var(--accent); }
.status-line { font-family: var(--sans); font-size: 0.85rem; color: var(--muted); margin: 0.2rem 0; }
.status-banner { font-family: var(--sans); font-size: 0.92rem; line-height: 1.5; padding: 0.7rem 1rem; border-radius: 5px; margin: 0.5rem 0 1rem; }
.status-banner.status-draft { background: var(--warn-bg); color: var(--warn-fg); border: 1px solid var(--warn-rule); }
.status-banner.status-corrected { background: var(--surface); color: var(--fg); border: 1px solid var(--accent); border-left: 4px solid var(--accent); }
.status-banner a { color: inherit; }
ol.articles { list-style: none; padding: 0; }
ol.articles li { padding: 0.8rem 0; border-bottom: 1px solid var(--rule); }
ol.articles .atitle { font-size: 1.1rem; }
ol.articles .ameta { color: var(--muted); font-size: 0.9rem; font-family: var(--sans); }
@media print {
  :root { --bg: #ffffff; --fg: #000000; }
  a[href^="http"]::after { content: " (" attr(href) ")"; font-size: 0.8em; word-break: break-all; }
  nav.toc, p.actions, details.cite-this { display: none; }
  h1, h2, h3, figure { break-inside: avoid; }
}
"""


def site_header(root_rel, journal_title):
    t = html.escape(journal_title)
    return (
        '<header class="site">'
        '<a class="brand" href="%sindex.html">%s</a>'
        '<nav><a href="%sindex.html">Home</a></nav>'
        "</header>" % (root_rel, t, root_rel)
    )


def site_footer(journal_title, issn):
    t = html.escape(journal_title)
    issn_bit = (" ISSN " + html.escape(issn)) if issn else ""
    return (
        '<footer class="site">%s.%s Open access. Built with journal-maker.'
        "</footer>" % (t, issn_bit)
    )
