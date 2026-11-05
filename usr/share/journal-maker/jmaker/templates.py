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
/* Permalink glyph ("#") on headings and table captions: hidden until the block is
   hovered, the link is keyboard-focused, or the block is the current :target. opacity
   (not display:none) keeps it in the tab order. */
a.headerlink {
  margin-left: 0.3rem; color: var(--muted); font-weight: 400; text-decoration: none;
  opacity: 0; transition: opacity 0.12s ease;
}
*:hover > a.headerlink, a.headerlink:focus-visible, :target > a.headerlink { opacity: 1; }
a.headerlink:hover, a.headerlink:focus-visible { color: var(--accent); }
@media print { a.headerlink { display: none; } }
p.authors { font-family: var(--sans); font-size: 1.05rem; margin: 0.2rem 0; }
p.affil { font-family: var(--sans); font-size: 0.9rem; color: var(--muted); margin: 0.1rem 0; }
p.venue { font-family: var(--sans); font-size: 0.9rem; color: var(--muted); margin: 0.2rem 0; }
.actions { font-family: var(--sans); font-size: 0.9rem; color: var(--muted); margin: 0.4rem 0 0.2rem; display: flex; flex-wrap: wrap; align-items: center; gap: 0.3rem 0.55rem; }
.actions a {
  display: inline-flex; align-items: center; padding: 0.35rem 0.8rem;
  background: var(--accent); color: var(--on-accent); border-radius: 4px;
  text-decoration: none; font-size: 0.9rem;
}
/* Icon-only integrity link (lock-with-key glyph); subtle until hover/focus. */
.actions a.checksum { background: none; color: var(--muted); padding: 0.35rem 0.25rem; font-size: 0.85rem; line-height: 1; }
.actions a.checksum:hover, .actions a.checksum:focus-visible { color: var(--accent); }
.actions a.sources-aid { background: none; color: var(--accent); padding: 0.35rem 0.2rem; font-size: 0.85rem; }
/* LaTeX sources: one no-JS <details> pop-over. <summary> = ghost-button trigger
   (secondary to the filled PDF/Word buttons); the panel floats over the content. */
.actions details.latex-dl { position: relative; }
.actions details.latex-dl > summary {
  list-style: none; cursor: pointer; display: inline-flex; align-items: center;
  gap: 0.35rem; padding: 0.35rem 0.75rem; border: 1px solid var(--accent);
  border-radius: 4px; color: var(--accent); font-size: 0.9rem;
}
.actions details.latex-dl > summary::-webkit-details-marker { display: none; }
.actions details.latex-dl > summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.actions details.latex-dl > summary .caret { font-size: 0.7em; transition: transform 0.15s ease; }
.actions details.latex-dl[open] > summary .caret { transform: rotate(180deg); }
.actions .latex-menu {
  position: absolute; left: 0; top: calc(100% + 0.35rem); z-index: 5;
  min-width: 13rem; background: var(--bg); border: 1px solid var(--rule);
  border-radius: 7px; box-shadow: 0 6px 22px rgba(0, 0, 0, 0.18);
  padding: 0.3rem; display: flex; flex-direction: column;
}
.actions .latex-menu .latex-menu-head {
  margin: 0; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--muted); padding: 0.35rem 0.6rem 0.2rem;
}
.actions .latex-menu a {
  display: flex; justify-content: space-between; gap: 1rem; align-items: baseline;
  padding: 0.4rem 0.6rem; border-radius: 4px; background: none; color: var(--fg);
  font-size: 0.88rem;
}
.actions .latex-menu a .ext { font-family: var(--mono); font-size: 0.74rem; color: var(--muted); }
.actions .latex-menu a:hover, .actions .latex-menu a:focus-visible { background: var(--surface); color: var(--accent); }
/* Narrow screens: a left/right-anchored pop-over can run off either edge (the
   trigger sits mid-row, or first under skip_pdf). Drop the overlay and expand the
   menu inline, full-width and in flow, so it never forces horizontal scroll. */
@media (max-width: 30rem) {
  .actions details.latex-dl[open] { width: 100%; }
  .actions .latex-menu {
    position: static; min-width: 0; margin-top: 0.4rem; box-shadow: none;
  }
}
@media (prefers-reduced-motion: reduce) { .actions details.latex-dl > summary .caret { transition: none; } }
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
   the paper at that section's citation (#citesec-<key>-<N>). */
.qclaim { margin: 0 0 0.7rem; padding-left: 0.75rem; border-left: 2px solid var(--rule); }
.qclaim-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.45rem; margin-bottom: 0.25rem; }
.qclaim-label { font-family: var(--sans); font-size: 0.66rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
.qclaim-sec { font-family: var(--sans); font-size: 0.72rem; font-weight: 650; color: var(--accent); text-decoration: none; border: 1px solid var(--rule); border-radius: 999px; padding: 0.03rem 0.52rem; white-space: nowrap; }
.qclaim-sec:hover, .qclaim-sec:focus-visible { background: var(--surface); text-decoration: underline; }
/* Per-section jump target a "Sec. N" pill links to (#citesec-<key>-<N>): an empty
   inline span before the key's citation in that section. scroll-margin keeps the
   deep-linked citation clear of the viewport top. */
.citesec-anchor { scroll-margin-top: 2rem; }
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
article.body { margin-top: 1.5rem; overflow-wrap: break-word; }
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
article.body code { font-family: var(--mono); font-size: 0.875em; background: var(--surface); border: 1px solid var(--rule); padding: 0.1em 0.35em; border-radius: 3px; overflow-wrap: anywhere; }
article.body pre { font-family: var(--mono); font-size: 0.85rem; line-height: 1.5; overflow-x: auto; max-width: 100%; padding: 1rem; background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; tab-size: 4; }
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
/* Visible, no-JS Wayback archive link on a reference (the source's memento). Quiet, in the
   .csl-source family; the live link stays primary. */
.csl-archive { font-family: var(--sans); font-size: 0.78rem; margin-left: 0.6rem; white-space: nowrap; color: var(--muted); }
.csl-archive:hover, .csl-archive:focus-visible { color: var(--accent); }
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
/* Back-to-top floating control: fixed bottom-right. With JS, SITE_JS shows/hides it
   (400px threshold + 2s idle-hide) with an eased opacity fade mirroring the production
   wiki control. With no JS it falls to the @supports floor below (reveal past 400px on
   modern browsers; always-visible on legacy ones). The <a href="#top"> jumps to
   <body id="top"> with no JS regardless. */
.back-to-top { position: fixed; right: 20px; bottom: 20px; z-index: 40; display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; border-radius: 50%; background: rgba(0, 0, 0, 0.35); color: #fff; text-decoration: none; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.2); text-shadow: 0 0 3px rgba(0, 0, 0, 0.7), 0 1px 2px rgba(0, 0, 0, 0.5); transition: background 0.12s ease; }
.back-to-top:hover, .back-to-top:focus-visible { background: rgba(0, 0, 0, 0.55); color: #fff; }
/* A translucent dark chip (production parity), INVERTED to a translucent light chip in dark
   mode so a white chevron stays visible on a dark page (a dark-on-dark chip would vanish). */
:root[data-theme="dark"] .back-to-top { background: rgba(255, 255, 255, 0.32); color: #fff; }
:root[data-theme="dark"] .back-to-top:hover, :root[data-theme="dark"] .back-to-top:focus-visible { background: rgba(255, 255, 255, 0.48); color: #fff; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .back-to-top { background: rgba(255, 255, 255, 0.32); color: #fff; }
  :root:not([data-theme="light"]) .back-to-top:hover, :root:not([data-theme="light"]) .back-to-top:focus-visible { background: rgba(255, 255, 255, 0.48); color: #fff; }
}
/* JS path: the script toggles .btt-hidden to fade the control in/out (eased opacity,
   matching the production wiki's phased 300ms fade) instead of a binary display snap.
   visibility carries tab-order removal, delayed to the END of the fade-out (0.3s) so the
   opacity fade is seen, and restored at once on fade-in. pointer-events:none drops the
   click target the instant the fade-out starts (opacity near 0 alone stays hit-testable),
   and the :focus rule keeps a control focused mid-fade from being hidden under its own
   focus. The initial hide is committed under the no-opacity base transition (a forced
   reflow in site.js) before .btt-anim enables the fade, so load shows no fade-out. */
:root.js .back-to-top { opacity: 1; visibility: visible; }
:root.js .back-to-top.btt-hidden { opacity: 0; visibility: hidden; pointer-events: none; }
:root.js .back-to-top.btt-anim { transition: opacity 0.3s ease, visibility 0s linear 0s, background 0.12s ease; }
:root.js .back-to-top.btt-anim.btt-hidden { transition: opacity 0.3s ease, visibility 0s linear 0.3s, background 0.12s ease; }
/* A control that gains focus mid-fade-out (still `visibility: visible`, so still tabbable
   for the 0.3s fade) must not then be hidden under that focus -- the delayed
   visibility:hidden would drop focus to <body>. Hold it fully shown while focused, parity
   with the no-JS :focus guard below. */
:root.js .back-to-top.btt-hidden:focus { opacity: 1; visibility: visible; pointer-events: auto; }
@media (prefers-reduced-motion: reduce) {
  :root.js .back-to-top.btt-anim, :root.js .back-to-top.btt-anim.btt-hidden { transition: background 0.12s ease; }
}
/* No-JS reveal floor -- a pure progressive-enhancement fallback. SITE_JS adds the `js`
   class to the root, so with JS this NEVER applies: the script then owns .btt-hidden
   entirely and its focus-guard / idle-hide can never be overridden by a competing CSS
   reveal. With no JS the control reveals once scrolled past the JS 400px threshold
   instead of sitting stuck visible at the top. A DISCRETE visibility flip (not an
   opacity fade): visibility carries the whole state, so the control is either fully
   hidden -- out of the tab order, no click target, no faint focus stop -- or fully
   shown, mirroring the JS path's instant toggle and never interactive-while-faint
   (an opacity fade is `visible` throughout, so it would be clickable at ~0 opacity).
   visibility flips to `visible` for any scroll progress past the range start, so the
   400px start IS the reveal point (the 440px end is nominal). On a short page the scroll
   timeline is inactive and the animation drops out to the visibility:hidden base. The
   @supports guard is REQUIRED: without scroll timelines the animation binds to the time
   timeline and would stick the control hidden -- so unsupported browsers fall through
   to the always-visible base. */
@supports (animation-timeline: scroll()) {
  :root:not(.js) .back-to-top { visibility: hidden; animation: back-to-top-reveal linear both; animation-timeline: scroll(root); animation-range: 400px 440px; }
  /* Keep a focused control visible regardless of scroll -- parity with the JS
     focus-guard: a keyboard user who tabs to it (while shown) then scrolls back
     above 400px must keep its focus indicator, and focus must not be dropped by
     a visibility:hidden mid-focus. */
  :root:not(.js) .back-to-top:focus { animation: none; visibility: visible; }
  @keyframes back-to-top-reveal { from { visibility: hidden; } to { visibility: visible; } }
}
@media print {
  :root { --bg: #ffffff; --fg: #000000; }
  a[href^="http"]::after { content: " (" attr(href) ")"; font-size: 0.8em; word-break: break-all; }
  nav.toc, .actions, details.cite-this, .skip-link, .status-pill-row, .back-to-top-nav { display: none; }
  h1, h2, h3, figure { break-inside: avoid; }
}
"""


# Back-to-top control markup: a static <a href="#top"> (works with no JS -- #top is
# the <body id="top">), enhanced by SITE_JS. Inline SVG chevron (no icon font).
BACK_TO_TOP_HTML = (
    '<nav class="back-to-top-nav" aria-label="Back to top">'
    '<a class="back-to-top" href="#top" aria-label="Back to top of the page">'
    '<svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" '
    'focusable="false"><path d="M5 12.5l5-5 5 5" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    '</a></nav>'
)


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

  // Mark the document JS-capable so the no-JS back-to-top CSS reveal floor (a pure
  // progressive-enhancement fallback) steps aside and this script owns the control.
  document.documentElement.classList.add("js");

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

  // The card most recently shown / stepped / pressed; only IT responds to arrow keys,
  // so one keypress never advances a second (pinned-but-inactive) card on the page.
  var activeHovercard = null;
  // Shared hovercard machinery. Both the citation and footnote previews are a card
  // that hover/focus opens, steps prev/next through its targets in document order (a
  // "n / N" position counter in the nav bar), and is drag-moveable by that nav bar.
  // The only genuine per-type differences come in via opts:
  //   anchors    -- array of in-body anchors (cites or footnote markers).
  //   decorative -- false: role=dialog, keyboard-reachable nav (citations). true:
  //                 aria-hidden decorative preview with nav buttons kept OUT of tab
  //                 order (tabindex=-1), so the card is never a focus/a11y trap
  //                 (footnotes; the real note is reached by activating the marker).
  //   prevLabel / nextLabel -- aria-labels for the step buttons.
  //   contentFor(id) -- a DocumentFragment for the card body (may be empty).
  //   titleFor(id)   -- native title= string for the marker (JS-off / touch fallback),
  //                     or null to leave the marker's title untouched.
  // TT-safe: the card is built with DOM APIs + cloneNode only (no HTML-string sinks),
  // so it survives a strict Content-Security-Policy.
  function makeHovercard(opts) {
    var anchors = opts.anchors;
    var order = [];               // target ids in first-reference document order (deduped)
    var seen = Object.create(null);
    for (var j = 0; j < anchors.length; j++) {
      var href = anchors[j].getAttribute("href");
      if (!href || href.charAt(0) !== "#") { continue; }
      var tid = href.slice(1);
      if (!document.getElementById(tid)) { continue; }   // skip markers with no target
      if (opts.titleFor) {
        var t = opts.titleFor(tid);
        if (t) { anchors[j].setAttribute("title", t); }
      }
      if (!seen[tid]) { seen[tid] = true; order.push(tid); }
    }
    if (!order.length) { return; }
    var card = document.createElement("div");
    card.className = "hovercard";
    if (opts.decorative) {
      // decorative preview, not a dialog: aria-hidden keeps assistive tech from
      // announcing an unreachable duplicate (the real target is reached via the marker).
      card.setAttribute("aria-hidden", "true");
    } else {
      card.setAttribute("role", "dialog");
    }
    card.hidden = true;
    var cbody = document.createElement("div");
    cbody.className = "hovercard-body";
    var cnav = document.createElement("div");
    cnav.className = "hovercard-nav";
    var cprev = document.createElement("button");
    cprev.type = "button"; cprev.className = "hovercard-navbtn";
    cprev.textContent = String.fromCharCode(0x25C0); cprev.setAttribute("aria-label", opts.prevLabel);
    var cpos = document.createElement("span");
    cpos.className = "hovercard-pos";
    var cnext = document.createElement("button");
    cnext.type = "button"; cnext.className = "hovercard-navbtn";
    cnext.textContent = String.fromCharCode(0x25B6); cnext.setAttribute("aria-label", opts.nextLabel);
    if (opts.decorative) {
      // A focusable control inside an aria-hidden card is itself an a11y trap
      // (focusable but never tabbable, and focus must never land inside aria-hidden).
      // Keep the nav pointer-operable but out of tab order, and preventDefault its
      // mousedown so a click never moves focus INTO the card (which would also drop
      // focus to <body> when step() then disables the button at an end).
      cprev.tabIndex = -1; cnext.tabIndex = -1;
      cprev.addEventListener("mousedown", function (e) { e.preventDefault(); });
      cnext.addEventListener("mousedown", function (e) { e.preventDefault(); });
    }
    cnav.appendChild(cprev); cnav.appendChild(cpos); cnav.appendChild(cnext);
    // Nav on TOP: prev/next buttons appended before the body.
    card.appendChild(cnav); card.appendChild(cbody);
    document.body.appendChild(card);

    var hideTimer = null, curIdx = -1, curAnchor = null, pinned = false, moved = false;
    function populate(idx) {
      if (idx < 0 || idx >= order.length) { return; }
      curIdx = idx;
      while (cbody.firstChild) { cbody.removeChild(cbody.firstChild); }
      var frag = opts.contentFor(order[idx]);
      if (frag) { cbody.appendChild(frag); }
      cpos.textContent = (idx + 1) + " / " + order.length;
      // A single-target card has no prev/next to show, but the nav bar is also the
      // drag grip -- keep it (and its grip) visible, hiding only the step controls, so
      // a lone-target card stays drag-moveable.
      var single = order.length < 2;
      cprev.hidden = single; cnext.hidden = single; cpos.hidden = single;
      cprev.disabled = idx === 0;
      cnext.disabled = idx === order.length - 1;
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
      moved = false;             // re-anchor to the marker (drag offset cleared)
      curAnchor = anchor;
      activeHovercard = card;    // this card now owns the arrow keys
      card.hidden = false;
      populate(idx);
      place(anchor);
    }
    // Pinned (the user clicked a nav button) overrides hover-to-hide, so stepping
    // through targets never auto-closes when the card resizes under the pointer.
    function hideSoon() { if (pinned) { return; } hideTimer = setTimeout(function () { card.hidden = true; }, 200); }
    function cancelHide() { if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; } }
    function dismiss() { card.hidden = true; pinned = false; cancelHide(); }
    function step(delta) {
      var ni = curIdx + delta;
      if (ni < 0 || ni >= order.length) { return; }
      cancelHide();
      pinned = true;
      populate(ni);
      // Keep a dragged card where the user put it; otherwise re-anchor on resize.
      if (curAnchor && !moved) { place(curAnchor); }
    }
    for (var c = 0; c < anchors.length; c++) {
      (function (a) {
        var h = a.getAttribute("href");
        if (!h || h.charAt(0) !== "#") { return; }
        var idx = order.indexOf(h.slice(1));
        if (idx < 0) { return; }
        a.addEventListener("mouseenter", function () { show(a, idx); });
        a.addEventListener("mouseleave", hideSoon);
        a.addEventListener("focus", function () { show(a, idx); });
        a.addEventListener("blur", hideSoon);
      })(anchors[c]);
    }
    card.addEventListener("mouseenter", cancelHide);
    card.addEventListener("mouseleave", hideSoon);
    // A pointer press anywhere inside the card pins it, so selecting text on touch
    // (no hover there) is not cut short by the blur/hideSoon closing the card.
    card.addEventListener("pointerdown", function () { pinned = true; activeHovercard = card; cancelHide(); });
    cprev.addEventListener("click", function () { step(-1); });
    cnext.addEventListener("click", function () { step(1); });
    // Drag the card by its nav bar to reposition it (pointer); dragging pins it so
    // it does not auto-hide, and sets `moved` so stepping targets keeps the new spot.
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
    // Keyboard: Escape dismisses; a plain Left/Right steps prev/next. Only the ACTIVE
    // card responds, so one arrow never advances a second (pinned-but-inactive) card
    // elsewhere on the page. Within the active card, step when it is pinned or the
    // focus is on one of its markers / inside it -- the `pinned` term keeps stepping
    // working after a pointer nav-click disables the focused button and the browser
    // drops focus to <body>. Modified arrows are left to the browser (text selection,
    // history, word jump); an unpinned hover-only card does not hijack page scrolling.
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { dismiss(); return; }
      if (card.hidden || activeHovercard !== card) { return; }
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") { return; }
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) { return; }
      var ae = document.activeElement;
      if (!(pinned || card.contains(ae) || anchors.indexOf(ae) >= 0)) { return; }
      e.preventDefault();
      step(e.key === "ArrowLeft" ? -1 : 1);
    });
    // A pinned card is dismissed by a click outside it (the nav click that pins
    // is inside the card, so it never self-dismisses).
    document.addEventListener("click", function (e) {
      if (pinned && !card.hidden && !card.contains(e.target)) { dismiss(); }
    });
  }

  // Citation hovercards: hover/focus a [n] to preview its reference, stepping through
  // the references in document order. The native title= is kept as a JS-off fallback.
  // citeproc renders each in-text cite as <span class="citation"><a href="#ref-KEY">;
  // a grouped cite holds several such anchors. The reference list uses .csl-entry,
  // never .citation, so this selector matches in-text cites only.
  (function () {
    var cites = [].slice.call(document.querySelectorAll("article.body .citation a[href^='#ref-']"));
    function refFragment(id) {
      // Prefer the verbatim source-quote block inlined in the reference entry
      // (.csl-quote) -- a single source of the quote, shared with the reference area
      // (no duplicate hidden store); fall back to the whole reference entry when the
      // key has no quote.
      var frag = document.createDocumentFragment();
      var ref = document.getElementById(id);
      if (!ref) { return frag; }
      var r = ref.querySelector(".csl-quote") || ref;
      var kids = r.childNodes;
      for (var i = 0; i < kids.length; i++) {
        frag.appendChild(kids[i].cloneNode(true));
      }
      return frag;
    }
    function refTitle(id) {
      // Native tooltip = the reference text WITHOUT the inlined .csl-quote (the quote
      // is shown in the hovercard; repeating it in the title is noise).
      var ref = document.getElementById(id);
      if (!ref) { return null; }
      var titleSrc = ref.cloneNode(true);
      var cq = titleSrc.querySelector(".csl-quote");
      if (cq && cq.parentNode) { cq.parentNode.removeChild(cq); }
      return titleSrc.textContent.replace(/\s+/g, " ").trim();
    }
    makeHovercard({
      anchors: cites,
      decorative: false,
      prevLabel: "Previous reference",
      nextLabel: "Next reference",
      contentFor: refFragment,
      titleFor: refTitle
    });
  })();

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

  // Back-to-top: reveal past 400px of scroll, auto-hide 2s after scrolling stops,
  // smooth-scroll on click. Shown/hidden via an eased opacity fade (.btt-hidden)
  // mirroring the production wiki control, not a binary display snap. Progressive --
  // the <a href="#top"> works with no JS.
  (function () {
    var btn = document.querySelector(".back-to-top");
    if (!btn) { return; }
    // Hide instantly on load, then enable the fade. Forcing a reflow between the two
    // commits the hidden state under the base (no-opacity) transition, so opacity snaps
    // to 0 with no fade; .btt-anim then enables the fade for later toggles only. (A lone
    // requestAnimationFrame batches both class adds into one style pass, so with the
    // deferred site.js the initial hide would still play as a 300ms fade-out on load.)
    btn.classList.add("btt-hidden");
    void btn.offsetHeight;
    btn.classList.add("btt-anim");
    function show() { btn.classList.remove("btt-hidden"); }
    // Never hide the control while it holds keyboard focus (a hide-timer or a
    // scroll-to-top must not steal focus from a keyboard user mid-activation, and
    // the fade-out's visibility:hidden would drop focus).
    function hide() { if (document.activeElement !== btn) { btn.classList.add("btt-hidden"); } }
    var idle = null;
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      // "instant" forces the jump a reduced-motion user asked for ("auto" would honor a CSS
      // scroll-behavior:smooth if one were ever set). Then release focus so the scroll-to-top's
      // own hide() is not suppressed by the focus-guard, which would otherwise leave the control
      // at the top catching clicks over the content; moving focus on activation is WCAG-fine.
      var reduce = window.matchMedia
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: 0, behavior: reduce ? "instant" : "smooth" });
      // Release focus only on a POINTER click (detail > 0; keyboard-activated clicks report 0),
      // so the scroll-to-top's own hide() is not suppressed by the focus-guard, leaving the
      // control at the top catching clicks. A keyboard user keeps focus (blurring would discard
      // their place rather than move it somewhere sensible).
      if (e.detail > 0) { btn.blur(); }
    });
    // On blur, re-check the threshold: hide at once near the top, else resume the idle-hide (a
    // focused control's idle timer no-ops, so without this it would linger once focus leaves).
    btn.addEventListener("blur", function () {
      if (window.scrollY < 400) { hide(); return; }
      clearTimeout(idle);
      idle = setTimeout(hide, 2000);
    });
    window.addEventListener("scroll", function () {
      if (window.scrollY < 400) { hide(); return; }
      show();
      clearTimeout(idle);
      idle = setTimeout(hide, 2000);
    }, { passive: true });
  })();

  // Footnote hovercards: hover/focus a footnote marker to preview the note inline,
  // with the same prev/next stepping and drag-to-move as the citation card (shared
  // makeHovercard). Progressive -- the marker stays a working <a href="#fnN"> with no
  // JS (click still jumps to the note at the document end); this only adds a preview.
  // The marker id namespace is pandoc's (#fnN), found by getElementById, so this is
  // agnostic to whether pandoc wrapped the notes in <section> or <aside>. The card is
  // decorative (aria-hidden, untabbable nav) so it is never an a11y trap. TT-safe:
  // DOM APIs + cloneNode only.
  (function () {
    var marks = [].slice.call(
      document.querySelectorAll("article.body a.footnote-ref[href^='#fn']"));
    function noteClone(id) {
      // A clone of the <li id="fnN"> note, minus the back-reference arrow(s)
      // (navigation chrome, noise in a preview); null if the note is missing.
      var li = document.getElementById(id);
      if (!li) { return null; }
      var clone = li.cloneNode(true);
      var backs = clone.querySelectorAll(".footnote-back");
      for (var i = 0; i < backs.length; i++) {
        if (backs[i].parentNode) { backs[i].parentNode.removeChild(backs[i]); }
      }
      // The card is a DECORATIVE preview (aria-hidden, not in tab order): a keyboard
      // user reaches the note's real links by activating the marker (href="#fnN" ->
      // the note at document end, where the links ARE in tab order). So drop href from
      // the preview's own links -- a link that is focusable but can never be tabbed to
      // is the a11y trap; without href it is inert citation text, no trap, and the live
      // links stay one marker-activation away. The marker's title= carries the note
      // text for assistive tech.
      var links = clone.querySelectorAll("a[href]");
      for (var j = 0; j < links.length; j++) {
        links[j].removeAttribute("href");
      }
      return clone;
    }
    function noteFragment(id) {
      var frag = document.createDocumentFragment();
      var clone = noteClone(id);
      if (clone) { while (clone.firstChild) { frag.appendChild(clone.firstChild); } }
      return frag;
    }
    function noteTitle(id) {
      var clone = noteClone(id);
      return clone ? clone.textContent.replace(/\s+/g, " ").trim() : null;
    }
    makeHovercard({
      anchors: marks,
      decorative: true,
      prevLabel: "Previous footnote",
      nextLabel: "Next footnote",
      contentFor: noteFragment,
      titleFor: noteTitle
    });
  })();
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
