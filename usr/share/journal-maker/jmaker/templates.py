#!/usr/bin/python3 -Bsu
"""Static HTML skeleton + CSS for the site.

ASCII only. Pages are composed in generate.py; this module holds the shared
chrome (stylesheet, site header/footer). Visual spec follows common scholarly
venues (eLife/Nature/Distill/JOSS): serif body + system-sans headings, a ~38rem
measure, one blue accent, off-black on off-white, booktabs tables, hanging-indent
references, light + dark via prefers-color-scheme.
"""

import html
from urllib.parse import urljoin

# Site icon: a shield (security) carrying a check (research/verification), on the
# blue accent (--accent #0b5cad). Static shapes only -- no script/on*/external url
# -- so it passes the SVG active-content safety check and serves same-origin under
# img-src 'self'. One SVG scales to every size (favicon, tab, PWA icon).
FAVICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" \
role="img" aria-label="Computer Security Research">
  <rect width="64" height="64" rx="13" fill="#0b5cad"/>
  <path d="M32 11 L51 19 V33 C51 44.5 42.7 51.8 32 55 \
C21.3 51.8 13 44.5 13 33 V19 Z" fill="#ffffff"/>
  <path d="M24.5 33 L30 38.5 L40.5 26.5" fill="none" stroke="#0b5cad" \
stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""

# Social-share card (og:image / twitter:image), 1200x630. Rasterized to og.png
# at build via rsvg-convert. %(title)s is XML-escaped before interpolation;
# %(fontsize)s is shrunk by write_icons so a long title fits the card's text
# column (x=90..1110) instead of overflowing the 1200px canvas.
# Static shapes + system sans text; renders with a fallback font if the build
# host lacks the named family (never fails the build).
OG_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#fdfdfc"/>
  <rect y="606" width="1200" height="24" fill="#0b5cad"/>
  <g transform="translate(90,80) scale(2.1)">
    <path d="M32 11 L51 19 V33 C51 44.5 42.7 51.8 32 55 \
C21.3 51.8 13 44.5 13 33 V19 Z" fill="#0b5cad"/>
    <path d="M24.5 33 L30 38.5 L40.5 26.5" fill="none" stroke="#ffffff" \
stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  </g>
  <text x="90" y="360" font-family="sans-serif" font-size="%(fontsize)s" \
font-weight="700" fill="#15171b">%(title)s</text>
  <text x="90" y="430" font-family="sans-serif" font-size="34" \
fill="#5a5f66">Research previews, posted for public commentary</text>
</svg>
"""

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
  /* Foreground for filled accent surfaces (skip-link, PDF button). The dark
     accent is a LIGHT blue, so white text fails WCAG AA on it -- use a dark
     on-accent there instead. */
  --on-accent: #ffffff;
  --visited: #6b3fa0;
  --rule: #d9d9d4;
  --introbg: #eeeeec;
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
    --on-accent: #15171b;
    --visited: #b79be0;
    --rule: #32363e;
    --introbg: #22262e;
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
  --on-accent: #15171b;
  --visited: #b79be0;
  --rule: #32363e;
  --introbg: #22262e;
  --warn-bg: #3a300f; --warn-fg: #f0d78a; --warn-rule: #7a6420;
  --ok-bg: #16301c; --ok-fg: #9fd9ab; --ok-rule: #2f5d39;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
.skip-link { position: absolute; left: -9999px; top: 0; background: var(--accent); color: var(--on-accent); padding: 0.5rem 0.9rem; border-radius: 0 0 4px 0; font-family: var(--sans); z-index: 10; }
.skip-link:focus { left: 0; }
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
footer.site .footer-nav { display: flex; flex-wrap: wrap; gap: 0.3rem 1rem; margin-bottom: 0.6rem; }
footer.site .footer-nav a { color: var(--accent); }
footer.site p { margin: 0; }
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
  background: var(--accent); color: var(--on-accent); border-radius: 4px;
  text-decoration: none; font-size: 0.9rem;
}
p.actions a.checksum { background: none; color: var(--accent); padding: 0.35rem 0.2rem; font-size: 0.8rem; }
p.actions a.sources-aid { background: none; color: var(--accent); padding: 0.35rem 0.2rem; font-size: 0.85rem; }
.sources-back { font-family: var(--sans); font-size: 0.9rem; margin: 0 0 1.2rem; }
.sources-back a { color: var(--accent); }
/* Wrap any long unbroken token (attribution URLs) so the page never overflows. */
main.sources { overflow-wrap: anywhere; }
main.sources > h1 { margin-bottom: 1.5rem; }
/* On-page contents index: compact multi-column list of the cards + the Remaining
   section, each linking to its anchor. */
.sources-toc { margin: 0 0 2.2rem; border: 1px solid var(--rule); border-radius: 6px; padding: 0.9rem 1.1rem; background: var(--surface); }
.sources-toc h2 { font-family: var(--sans); font-size: 1rem; font-weight: 650; margin: 0 0 0.6rem; }
.sources-toc ul { list-style: none; margin: 0; padding: 0; columns: 2; column-gap: 1.8rem; }
.sources-toc li { break-inside: avoid; margin: 0 0 0.32rem; line-height: 1.4; }
.sources-toc a { font-family: var(--mono); font-size: 0.8rem; color: var(--accent); text-decoration: none; }
.sources-toc a:hover { text-decoration: underline; }
.sources-toc .toc-lbl { font-family: var(--sans); font-size: 0.8rem; color: var(--muted); }
.sources-toc .toc-rmn { margin-top: 0.55rem; }
.sources-toc .toc-rmn a { font-family: var(--sans); font-size: 0.82rem; }
@media (max-width: 640px) { .sources-toc ul { columns: 1; } }
/* One source-quote card: header ([@key] + label), the paper claim(s), the
   verbatim quote(s) as a quotation blockquote, and the refs.bib attribution. */
.qcard { margin: 1.8rem 0; }
.qhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.5rem; margin-bottom: 0.5rem; }
.qkey { font-family: var(--mono); font-size: 0.82rem; color: var(--accent); text-decoration: none; }
.qkey:hover { text-decoration: underline; }
.qlabel { font-family: var(--sans); font-weight: 650; font-size: 1.02rem; min-width: 0; }
/* Paper claim: a structured block above the quote; the section pill links into
   the paper at that section's citation (#cite-<key>-s<N>). */
.qclaim { margin: 0 0 0.7rem; padding-left: 0.75rem; border-left: 2px solid var(--rule); }
.qclaim-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.45rem; margin-bottom: 0.25rem; }
.qclaim-label { font-family: var(--sans); font-size: 0.66rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
.qclaim-sec { font-family: var(--sans); font-size: 0.72rem; font-weight: 650; color: var(--accent); text-decoration: none; border: 1px solid var(--rule); border-radius: 999px; padding: 0.03rem 0.52rem; white-space: nowrap; }
.qclaim-sec:hover, .qclaim-sec:focus-visible { background: var(--surface); text-decoration: underline; }
/* Per-section jump target a "Sec. N" pill links to (#cite-<key>-s<N>): an empty
   inline span before the key's citation in that section. scroll-margin keeps the
   deep-linked citation clear of the viewport top. */
.cite-sec-anchor { scroll-margin-top: 2rem; }
.qclaim-text { font-family: var(--sans); font-size: 0.92rem; color: var(--fg); margin: 0; line-height: 1.5; }
ul.qclaim-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
ul.qclaim-list li { font-family: var(--sans); font-size: 0.92rem; color: var(--fg); line-height: 1.5; display: flex; flex-wrap: wrap; gap: 0.45rem; align-items: baseline; }
ul.qclaim-list li .ct { min-width: 0; }
/* Verbatim quote styled as a quotation card (mw-static-generator Template:Quotation). */
blockquote.quotation { position: relative; margin: 0; background: var(--surface); color: var(--fg); border: none; border-left: 6px solid var(--accent); box-shadow: 2px 2px 4px 1px rgba(0, 0, 0, 0.07); padding: 1rem 1.4rem 1rem 3.4rem; border-radius: 2px; }
blockquote.quotation::before { content: "\\201C"; position: absolute; left: 0.7rem; top: 0.1rem; font-family: Georgia, "Times New Roman", serif; font-size: 3.2rem; line-height: 1; color: var(--accent); opacity: 0.3; pointer-events: none; }
blockquote.quotation p { margin: 0 0 0.7rem; }
blockquote.quotation p:last-child { margin-bottom: 0; }
.qlabel-tag { display: block; margin-bottom: 0.3rem; font-family: var(--sans); font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
/* Per-quote retrieval/provenance note -- separate from the verbatim quote text. */
.qnote { font-family: var(--sans); font-style: normal; font-size: 0.72rem; color: var(--muted); margin-top: 0.3rem; }
.blockquote-context { display: block; margin: 0.9rem 0 0; font-family: var(--sans); }
.blockquote-context .nm { display: block; font-weight: 600; font-size: 0.9rem; color: var(--fg); }
.blockquote-context .rl { display: block; font-size: 0.84rem; color: var(--muted); }
.blockquote-context .src { display: block; font-size: 0.84rem; margin-top: 0.3rem; }
.blockquote-context .src a { color: var(--accent); }
.blockquote-context .src .ret { color: var(--muted); }
/* Remaining references: cited sources with no retrievable verbatim text. */
.sources-remaining { margin-top: 2.5rem; border-top: 1px solid var(--rule); padding-top: 1rem; }
.sources-remaining h2 { font-family: var(--sans); font-size: 1.2rem; font-weight: 650; margin: 0 0 0.3rem; }
.sources-remaining-note { font-family: var(--sans); font-size: 0.85rem; color: var(--muted); margin: 0 0 0.8rem; }
ul.rmn-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
ul.rmn-list li { font-size: 0.92rem; line-height: 1.5; }
ul.rmn-list .qkey { font-family: var(--mono); font-size: 0.82rem; color: var(--accent); }
ul.rmn-list .rmn-reason { color: var(--muted); }
main.page { max-width: var(--measure); }
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
/* Dotted underline distinguishes a citeproc citation ref from a content link
   (solid) AND gives it a non-color distinction, which WCAG 1.4.1 requires for an
   inline link in a text block (axe link-in-text-block). */
article.body .citation a { text-decoration: underline dotted; font-variant-numeric: tabular-nums; }
article.body table { border-collapse: collapse; display: block; width: max-content; max-width: 100%; overflow-x: auto; font-size: 0.95rem; font-variant-numeric: tabular-nums; margin: 1.2rem 0; }
article.body thead th { border-bottom: 2px solid var(--fg); }
article.body tr.header { font-weight: 650; }
article.body tr.even { background: var(--surface); }
article.body tr.odd { background: transparent; }
article.body table { border-top: 2px solid var(--fg); border-bottom: 2px solid var(--fg); }
article.body th, article.body td { padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }
article.body code { font-family: var(--mono); font-size: 0.875em; background: var(--surface); border: 1px solid var(--rule); padding: 0.1em 0.35em; border-radius: 3px; }
article.body pre { font-family: var(--mono); font-size: 0.85rem; line-height: 1.5; overflow-x: auto; padding: 1rem; background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; tab-size: 4; }
article.body pre code { background: none; border: 0; padding: 0; }
article.body blockquote { margin: 1rem 0; padding-left: 1.25rem; border-left: 3px solid var(--rule); color: var(--muted); }
/* pandoc --citeproc reference list: #refs.csl-bib-body wraps one .csl-entry per
   reference, each split into .csl-left-margin ([n]) + .csl-right-inline (text).
   A flex row gives the hanging-indent look the IEEE numeric style expects. */
.csl-bib-body { margin: 0.5rem 0; }
.csl-entry { display: flex; gap: 0.6em; font-size: 0.9rem; line-height: 1.5; margin: 0.35rem 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.csl-entry:target { background: var(--surface); }
.csl-left-margin { flex: 0 0 auto; }
.csl-right-inline { flex: 1 1 auto; min-width: 0; }
/* Reference [n] is a backlink to its first in-text citation: looks like the
   plain number, clickable on hover; the citation it jumps to is highlighted via
   :target below (backwards-navigation aid). */
.csl-backref { color: var(--accent); text-decoration: underline dotted; }
.csl-backref:hover, .csl-backref:focus-visible { text-decoration: underline; }
.csl-source { font-family: var(--sans); font-size: 0.8rem; margin-left: 0.6rem; white-space: nowrap; }
/* Reference-area enrichments (HTML only): a stable [@key] backlink to the in-text
   citation + the verbatim quote inlined, matching the citation hovercard. */
.csl-citekey { font-family: var(--mono); font-size: 0.78rem; color: var(--accent); text-decoration: none; }
.csl-citekey:hover, .csl-citekey:focus-visible { text-decoration: underline; }
.csl-refmeta { margin-top: 0.15rem; font-size: 0.78rem; }
.csl-quote { margin: 0.45rem 0 0.3rem; }
article.body .citation a:target { background: var(--warn-bg); box-shadow: 0 0 0 2px var(--warn-rule); border-radius: 3px; }
.hovercard { position: absolute; z-index: 50; max-width: min(90vw, 30rem); background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; box-shadow: 0 4px 18px rgba(0, 0, 0, 0.18); padding: 0.55rem 0.75rem; font-size: 0.85rem; line-height: 1.5; }
.hovercard[hidden] { display: none; }
.hovercard-body { overflow-wrap: anywhere; }
/* A citeproc .csl-entry is cloned into the card; keep its [n]/text split inline
   so the preview reads as one line, not two stacked flex rows. */
.hovercard .csl-left-margin, .hovercard .csl-right-inline { display: inline; }
/* A source-quote block shown in a hovercard OR inlined in the reference area: the
   quote LEADS as an italic intro panel (IntroLike), the attribution/link sit
   quietly below a short rule. The big drop-quote mark and left accent bar are
   dropped here so the quote text is the focus (the sources-page CARD keeps the
   base quotation styling). Shared so the footnote preview and the reference area
   render the same. */
:is(.hovercard, .csl-quote) blockquote.quotation { margin: 0; padding: 0; background: transparent; box-shadow: none; border-left: none; border-radius: 0; }
:is(.hovercard, .csl-quote) blockquote.quotation::before { content: none; }
:is(.hovercard, .csl-quote) blockquote.quotation p { margin: 0 0 0.4rem; font-size: 1.02rem; line-height: 1.6; font-style: italic; color: var(--fg); background: var(--introbg); border-radius: 9px; padding: 0.6rem 0.85rem 0.7rem 1rem; box-shadow: inset 10px 0 8px -8px rgba(0, 0, 0, 0.12); }
:is(.hovercard, .csl-quote) blockquote.quotation p:last-of-type { margin-bottom: 0; }
/* label is block-level + spaced by the base rule; only the italic needs resetting here (the .csl-quote quote text is italic). */
:is(.hovercard, .csl-quote) blockquote.quotation .qlabel-tag { font-style: normal; }
:is(.hovercard, .csl-quote) .blockquote-context { display: block; position: relative; margin-top: 0.7rem; padding-left: 2.4rem; font-size: 0.75rem; line-height: 1.5; }
:is(.hovercard, .csl-quote) .blockquote-context::before { content: ""; position: absolute; left: 0; top: 0.62em; width: 1.8rem; border-top: 2px solid var(--fg); }
:is(.hovercard, .csl-quote) .blockquote-context .nm { display: inline; font-weight: 600; font-size: 0.78rem; color: var(--fg); }
:is(.hovercard, .csl-quote) .blockquote-context .rl { display: inline; font-size: 0.75rem; color: var(--muted); }
:is(.hovercard, .csl-quote) .blockquote-context .rl:not(:first-child)::before { content: " \\00B7\\20"; }
:is(.hovercard, .csl-quote) .blockquote-context .src { display: block; margin-top: 0.15rem; font-size: 0.75rem; color: var(--muted); }
/* Nav bar doubles as the drag handle (reposition the pinned card by mouse); the
   dotted grip is pushed left, the buttons stay right. */
.hovercard-nav { display: flex; align-items: center; justify-content: flex-end; gap: 0.6rem; margin-bottom: 0.4rem; cursor: grab; touch-action: none; }
.hovercard-nav::before { content: ""; margin-right: auto; width: 1.3rem; height: 0.7rem; background: radial-gradient(var(--muted) 1px, transparent 1.4px); background-size: 0.34rem 0.34rem; opacity: 0.55; }
.hovercard.dragging { box-shadow: 0 12px 34px rgba(0, 0, 0, 0.33); user-select: none; }
.hovercard.dragging .hovercard-nav { cursor: grabbing; }
.hovercard-nav[hidden] { display: none; }
.hovercard-navbtn { font-family: var(--sans); font-size: 0.8rem; line-height: 1; padding: 0.15rem 0.45rem; border: 1px solid var(--rule); border-radius: 4px; background: transparent; color: var(--accent); cursor: pointer; }
.hovercard-navbtn:disabled { opacity: 0.4; cursor: default; }
.hovercard-pos { font-family: var(--sans); font-size: 0.75rem; color: var(--muted); }
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
a.orcid { font-family: var(--sans); font-size: 0.68rem; font-weight: 700; color: #a6ce39; border: 1px solid #a6ce39; border-radius: 3px; padding: 0 0.22rem; text-decoration: none; vertical-align: 0.12em; }
p.history, p.subjects { font-family: var(--sans); font-size: 0.85rem; color: var(--muted); margin: 0.15rem 0; }
.cc-badge { font-family: var(--sans); font-weight: 650; font-size: 0.8rem; padding: 0.05rem 0.4rem; border: 1px solid var(--rule); border-radius: 3px; text-decoration: none; }
section.statement { margin: 1.6rem 0; }
section.statement h2 { font-size: 1.15rem; font-weight: 650; }
.cite-fmt { margin: 0.7rem 0; }
.cite-label { display: block; font-family: var(--sans); font-weight: 650; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 0.2rem; }
.copy-btn { float: right; font-family: var(--sans); font-size: 0.72rem; padding: 0.1rem 0.5rem; margin: 0 0 0.2rem 0.5rem; border: 1px solid var(--rule); border-radius: 3px; background: var(--surface); color: var(--fg); cursor: pointer; }
.copy-btn:hover { border-color: var(--accent); color: var(--accent); }
article.body img.zoomable { cursor: zoom-in; max-width: 100%; height: auto; }
.lightbox { position: fixed; inset: 0; background: rgba(0,0,0,0.85); display: flex; align-items: center; justify-content: center; padding: 1rem; z-index: 50; cursor: zoom-out; }
.lightbox img { max-width: 96vw; max-height: 96vh; }
article.body pre.sourceCode { position: relative; }
code span.kw { color: #7c4dff; } code span.dt { color: #0b7285; }
code span.dv, code span.bn, code span.fl { color: #b5651d; }
code span.st { color: #2e7d32; } code span.co { color: var(--muted); font-style: italic; }
code span.fu { color: #0b5cad; } code span.op, code span.ot { color: var(--fg); }
code span.pp { color: #a6378a; } code span.al, code span.er { color: #c62828; font-weight: 650; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) code span.kw { color: #b388ff; }
  :root:not([data-theme="light"]) code span.dt { color: #4dd0e1; }
  :root:not([data-theme="light"]) code span.st { color: #81c784; }
  :root:not([data-theme="light"]) code span.fu { color: #7db4f0; }
  :root:not([data-theme="light"]) code span.dv, :root:not([data-theme="light"]) code span.bn, :root:not([data-theme="light"]) code span.fl { color: #ffb74d; }
}
nav.article-nav { display: flex; justify-content: space-between; gap: 1rem; margin: 2.2rem 0 0; padding-top: 1rem; border-top: 1px solid var(--rule); font-family: var(--sans); font-size: 0.9rem; }
nav.article-nav .nav-next { margin-left: auto; text-align: right; }
ul.browse { list-style: none; padding: 0; }
ul.browse li { padding: 0.35rem 0; border-bottom: 1px solid var(--rule); font-family: var(--sans); font-size: 0.95rem; }
ul.previews { list-style: none; padding: 0; }
ul.previews li { padding: 0.6rem 0; border-bottom: 1px solid var(--rule); font-size: 1.05rem; }
ul.previews .date { color: var(--muted); font-size: 0.85rem; font-family: var(--sans); margin-left: 0.5rem; }
@media print {
  :root { --bg: #ffffff; --fg: #000000; }
  a[href^="http"]::after { content: " (" attr(href) ")"; font-size: 0.8em; word-break: break-all; }
  nav.toc, p.actions, details.cite-this, .skip-link, .status-pill-row { display: none; }
  h1, h2, h3, figure { break-inside: avoid; }
}
"""


def site_header(journal_title, site_root):
    # Absolute hrefs (site_root, identical on every page) so the header nav is
    # cross-page consistent; depth-relative would differ by page depth.
    t = html.escape(journal_title)
    return (
        '<header class="site">'
        '<a class="brand" href="%s">%s</a>'
        '<nav aria-label="Site"><a href="%s">Home</a></nav>'
        "</header>" % (site_root, t, site_root)
    )


# Self-hosted, Trusted-Types-safe enhancement bundle (script-src 'self'). Builds
# DOM only via textContent / createElement / setAttribute / classList and never a
# TT sink (no innerHTML, no script-url), so it runs under trusted-types 'none'
# with no policy. Hover previews use the native title attribute (no positioned
# tooltip) so no programmatic inline style is needed under style-src 'self'. The
# page is fully usable with JS disabled -- every feature here is additive.
SITE_JS = r"""// Site interactive enhancements. Trusted-Types-safe; progressive.
(function () {
  "use strict";

  // Copy button on each cite-box / code <pre>.
  function addCopy(pre) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy-btn";
    btn.textContent = "Copy";
    btn.addEventListener("click", function () {
      if (!(navigator.clipboard && navigator.clipboard.writeText)) { return; }
      navigator.clipboard.writeText(pre.textContent).then(function () {
        btn.textContent = "Copied";
        setTimeout(function () { btn.textContent = "Copy"; }, 1500);
      }, function () { btn.textContent = "Copy failed"; });
    });
    pre.parentNode.insertBefore(btn, pre);
  }
  var pres = document.querySelectorAll("details.cite-this pre, article.body pre");
  for (var i = 0; i < pres.length; i++) { addCopy(pres[i]); }

  // Citation hovercards: hover/focus a [n] to preview its reference, with prev/next
  // stepping through the references in document order. The native title= is kept as a
  // JS-off fallback. TT-safe: the card is built with DOM APIs + cloneNode only (no
  // HTML-string sinks), so it survives a strict Content-Security-Policy.
  // citeproc renders each in-text cite as <span class="citation"><a href="#ref-KEY">;
  // a grouped cite holds several such anchors. The reference list uses .csl-entry,
  // never .citation, so this selector matches in-text cites only.
  var cites = [].slice.call(document.querySelectorAll("article.body .citation a[href^='#ref-']"));
  var refOrder = [];            // ref ids in first-citation document order (deduped)
  var seen = Object.create(null);
  for (var j = 0; j < cites.length; j++) {
    var href = cites[j].getAttribute("href");
    if (!href || href.charAt(0) !== "#") { continue; }
    var rid = href.slice(1);
    var ref = document.getElementById(rid);
    if (!ref) { continue; }
    // Native tooltip = the reference text WITHOUT the inlined .csl-quote (the
    // quote is shown in the hovercard; repeating it in the title is noise).
    var titleSrc = ref.cloneNode(true);
    var cq = titleSrc.querySelector(".csl-quote");
    if (cq && cq.parentNode) { cq.parentNode.removeChild(cq); }
    cites[j].setAttribute("title", titleSrc.textContent.replace(/\s+/g, " ").trim());
    if (!seen[rid]) { seen[rid] = true; refOrder.push(rid); }
  }
  if (refOrder.length) {
    var card = document.createElement("div");
    card.className = "hovercard";
    card.setAttribute("role", "dialog");
    card.hidden = true;
    var cbody = document.createElement("div");
    cbody.className = "hovercard-body";
    var cnav = document.createElement("div");
    cnav.className = "hovercard-nav";
    var cprev = document.createElement("button");
    cprev.type = "button"; cprev.className = "hovercard-navbtn";
    cprev.textContent = String.fromCharCode(0x25C0); cprev.setAttribute("aria-label", "Previous reference");
    var cpos = document.createElement("span");
    cpos.className = "hovercard-pos";
    var cnext = document.createElement("button");
    cnext.type = "button"; cnext.className = "hovercard-navbtn";
    cnext.textContent = String.fromCharCode(0x25B6); cnext.setAttribute("aria-label", "Next reference");
    cnav.appendChild(cprev); cnav.appendChild(cpos); cnav.appendChild(cnext);
    // Nav on TOP: prev/next buttons appended before the reference body.
    card.appendChild(cnav); card.appendChild(cbody);
    document.body.appendChild(card);

    var hideTimer = null, curIdx = -1, curAnchor = null, pinned = false, moved = false;
    function refFragment(id) {
      var frag = document.createDocumentFragment();
      // id is "ref-<key>". Prefer the verbatim source-quote block inlined in the
      // reference entry (.csl-quote) -- a single source of the quote, shared with
      // the reference area (no duplicate hidden store); fall back to the whole
      // reference entry when the key has no quote.
      var ref = document.getElementById(id);
      if (!ref) { return frag; }
      var r = ref.querySelector(".csl-quote") || ref;
      var kids = r.childNodes;
      for (var i = 0; i < kids.length; i++) {
        frag.appendChild(kids[i].cloneNode(true));
      }
      return frag;
    }
    function populate(idx) {
      if (idx < 0 || idx >= refOrder.length) { return; }
      curIdx = idx;
      while (cbody.firstChild) { cbody.removeChild(cbody.firstChild); }
      cbody.appendChild(refFragment(refOrder[idx]));
      cpos.textContent = (idx + 1) + " / " + refOrder.length;
      cnav.hidden = refOrder.length < 2;
      cprev.disabled = idx === 0;
      cnext.disabled = idx === refOrder.length - 1;
    }
    function place(anchor) {
      var rect = anchor.getBoundingClientRect();
      var left = window.pageXOffset + rect.left;
      var maxLeft = window.pageXOffset + document.documentElement.clientWidth - card.offsetWidth - 8;
      if (left > maxLeft) { left = maxLeft; }
      if (left < window.pageXOffset + 8) { left = window.pageXOffset + 8; }
      card.style.left = left + "px";
      card.style.top = (window.pageYOffset + rect.bottom + 6) + "px";
    }
    function show(anchor, idx) {
      if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
      pinned = false;            // a fresh hover/focus is transient again
      moved = false;             // re-anchor to the citation (drag offset cleared)
      curAnchor = anchor;
      card.hidden = false;
      populate(idx);
      place(anchor);
    }
    // Pinned (the user clicked a nav button) overrides hover-to-hide, so stepping
    // through refs never auto-closes when the card resizes under the pointer.
    function hideSoon() { if (pinned) { return; } hideTimer = setTimeout(function () { card.hidden = true; }, 200); }
    function cancelHide() { if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; } }
    function dismiss() { card.hidden = true; pinned = false; cancelHide(); }
    function step(delta) {
      var ni = curIdx + delta;
      if (ni < 0 || ni >= refOrder.length) { return; }
      cancelHide();
      pinned = true;
      populate(ni);
      // Keep a dragged card where the user put it; otherwise re-anchor on resize.
      if (curAnchor && !moved) { place(curAnchor); }
    }
    for (var c = 0; c < cites.length; c++) {
      (function (a) {
        var h = a.getAttribute("href");
        if (!h || h.charAt(0) !== "#") { return; }
        var idx = refOrder.indexOf(h.slice(1));
        if (idx < 0) { return; }
        a.addEventListener("mouseenter", function () { show(a, idx); });
        a.addEventListener("mouseleave", hideSoon);
        a.addEventListener("focus", function () { show(a, idx); });
        a.addEventListener("blur", hideSoon);
      })(cites[c]);
    }
    card.addEventListener("mouseenter", cancelHide);
    card.addEventListener("mouseleave", hideSoon);
    // A pointer press anywhere inside the card pins it, so selecting text on touch
    // (no hover there) is not cut short by the blur/hideSoon closing the card.
    card.addEventListener("pointerdown", function () { pinned = true; cancelHide(); });
    cprev.addEventListener("click", function () { step(-1); });
    cnext.addEventListener("click", function () { step(1); });
    // Drag the card by its nav bar to reposition it (pointer); dragging pins it so
    // it does not auto-hide, and sets `moved` so stepping refs keeps the new spot.
    (function () {
      var dragging = false, activeId = -1, sx = 0, sy = 0, sl = 0, st = 0;
      cnav.addEventListener("pointerdown", function (e) {
        if (dragging) { return; }   // ignore a second pointer (multi-touch)
        if (e.target.closest && e.target.closest("button")) { return; }
        dragging = true; activeId = e.pointerId; pinned = true; moved = true; cancelHide();
        sx = e.clientX; sy = e.clientY;
        sl = parseFloat(card.style.left) || 0; st = parseFloat(card.style.top) || 0;
        card.classList.add("dragging");
        try { cnav.setPointerCapture(e.pointerId); } catch (ignore) {}
        e.preventDefault();
      });
      cnav.addEventListener("pointermove", function (e) {
        if (!dragging || e.pointerId !== activeId) { return; }
        var nl = sl + (e.clientX - sx), nt = st + (e.clientY - sy);
        var maxL = window.pageXOffset + document.documentElement.clientWidth - card.offsetWidth - 8;
        if (nl > maxL) { nl = maxL; }
        if (nl < window.pageXOffset + 8) { nl = window.pageXOffset + 8; }
        if (nt < window.pageYOffset + 8) { nt = window.pageYOffset + 8; }
        card.style.left = nl + "px"; card.style.top = nt + "px";
      });
      function endDrag(e) { if (dragging && (!e || e.pointerId === activeId)) { dragging = false; activeId = -1; card.classList.remove("dragging"); } }
      cnav.addEventListener("pointerup", endDrag);
      cnav.addEventListener("pointercancel", endDrag);
    })();
    // Keyboard: Escape dismisses; Left/Right step prev/next while the card is
    // open and either pinned or the focus is on a cite anchor / inside the card
    // (so arrow keys are not hijacked from ordinary page scrolling).
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { dismiss(); return; }
      if (card.hidden) { return; }
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") { return; }
      var ae = document.activeElement;
      if (!(pinned || card.contains(ae) || cites.indexOf(ae) >= 0)) { return; }
      e.preventDefault();
      step(e.key === "ArrowLeft" ? -1 : 1);
    });
    // A pinned card is dismissed by a click outside it (the nav click that pins
    // is inside the card, so it never self-dismisses).
    document.addEventListener("click", function (e) {
      if (pinned && !card.hidden && !card.contains(e.target)) { dismiss(); }
    });
  }

  // Figure lightbox: click a body image to view enlarged; click or Escape closes.
  function lightbox(img) {
    var ov = document.createElement("div");
    ov.className = "lightbox";
    var big = document.createElement("img");
    big.setAttribute("src", img.getAttribute("src"));
    big.setAttribute("alt", img.getAttribute("alt") || "");
    ov.appendChild(big);
    function close() { ov.remove(); document.removeEventListener("keydown", onKey); }
    function onKey(e) { if (e.key === "Escape") { close(); } }
    ov.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(ov);
  }
  var imgs = document.querySelectorAll("article.body img");
  for (var k = 0; k < imgs.length; k++) {
    imgs[k].classList.add("zoomable");
    imgs[k].addEventListener("click", function (e) { lightbox(e.currentTarget); });
  }
})();
"""


def site_footer(journal, site_root):
    t = html.escape(journal["title"])
    issn = journal.get("issn", "")
    issn_bit = (" ISSN " + html.escape(issn)) if issn else ""
    nav = ""
    links = journal.get("footer_links") or []
    if links:
        items = []
        for link in links:
            # Resolve against site_root -- the SAME convention as the header nav --
            # so a shared target (e.g. "Home" -> "./") is a byte-identical href in
            # both navs and does not trip axe identical-links-same-purpose. urljoin
            # keeps a mailto:/tel: (or http) scheme intact and, for the clean
            # relative paths load_journal permits, cannot emit an off-origin URL.
            href = urljoin(site_root, link["href"])
            items.append('<a href="%s">%s</a>'
                         % (html.escape(href, quote=True),
                            html.escape(link["title"])))
        nav = ('<nav class="footer-nav" aria-label="Footer">%s</nav>\n'
               % " ".join(items))
    return (
        '<footer class="site">%s<p>%s.%s</p></footer>'
        % (nav, t, issn_bit)
    )
