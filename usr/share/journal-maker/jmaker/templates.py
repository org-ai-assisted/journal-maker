#!/usr/bin/python3 -Bsu
"""Static HTML skeleton + CSS for the journal site.

ASCII only. Pages are composed in generate.py; this module holds the shared
chrome (stylesheet, site header/footer) so every page is visually one system.
"""

import html

STYLE_CSS = """\
:root {
  --bg: #ffffff;
  --fg: #1a1a1a;
  --muted: #555555;
  --rule: #e2e2e2;
  --link: #0b5fa5;
  --accent: #0b5fa5;
  --maxw: 46rem;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #15171a;
    --fg: #e8e8e8;
    --muted: #a6a6a6;
    --rule: #2c2f33;
    --link: #6fb3e8;
    --accent: #6fb3e8;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 1rem/1.6 Georgia, "Times New Roman", serif;
  padding: 0 1rem;
}
a { color: var(--link); }
header.site, footer.site {
  max-width: var(--maxw);
  margin: 0 auto;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
header.site {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 1.2rem 0;
  border-bottom: 1px solid var(--rule);
  flex-wrap: wrap;
  gap: 0.5rem;
}
header.site .brand { font-weight: 700; color: var(--fg); text-decoration: none; }
header.site nav a { margin-left: 1rem; }
footer.site {
  border-top: 1px solid var(--rule);
  margin-top: 3rem;
  padding: 1.2rem 0 2.5rem;
  color: var(--muted);
  font-size: 0.85rem;
}
main {
  max-width: var(--maxw);
  margin: 0 auto;
  padding: 1.5rem 0;
}
h1.title { font-size: 1.9rem; line-height: 1.25; margin: 0.4rem 0 0.6rem; }
p.authors { font-size: 1.05rem; margin: 0.2rem 0; }
p.venue, p.actions { color: var(--muted); font-size: 0.95rem; margin: 0.2rem 0; }
p.actions a {
  display: inline-block;
  margin-top: 0.4rem;
  padding: 0.35rem 0.8rem;
  background: var(--accent);
  color: #ffffff;
  border-radius: 4px;
  text-decoration: none;
  font-family: system-ui, sans-serif;
  font-size: 0.9rem;
}
section.abstract {
  margin: 1.5rem 0;
  padding: 1rem 1.2rem;
  border-left: 3px solid var(--accent);
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}
section.abstract h2 { margin-top: 0; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.05em; }
article.body { margin-top: 1.5rem; }
article.body h2 { font-size: 1.35rem; margin-top: 2rem; border-bottom: 1px solid var(--rule); padding-bottom: 0.2rem; }
article.body h3 { font-size: 1.1rem; margin-top: 1.4rem; }
article.body table { border-collapse: collapse; width: 100%; font-size: 0.92rem; }
article.body th, article.body td { border: 1px solid var(--rule); padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }
article.body code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.9em; }
article.body pre { overflow-x: auto; padding: 0.8rem; background: color-mix(in srgb, var(--fg) 5%, transparent); border-radius: 4px; }
article.body blockquote { margin: 1rem 0; padding-left: 1rem; border-left: 3px solid var(--rule); color: var(--muted); }
ol.articles { list-style: none; padding: 0; }
ol.articles li { padding: 0.8rem 0; border-bottom: 1px solid var(--rule); }
ol.articles .atitle { font-size: 1.1rem; }
ol.articles .ameta { color: var(--muted); font-size: 0.9rem; font-family: system-ui, sans-serif; }
@media (max-width: 480px) {
  body { padding: 0 0.9rem; }
  h1.title { font-size: 1.6rem; }
}
"""


def site_header(root_rel, journal_title):
    """Top chrome shared by every page. root_rel reaches the site root."""
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
