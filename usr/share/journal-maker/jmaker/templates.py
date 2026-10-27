#!/usr/bin/python3 -Bsu
"""Static HTML skeleton + CSS for the site.

ASCII only. Pages are composed in generate.py; this module holds the shared
chrome (stylesheet, site header/footer). Visual spec follows common scholarly
venues (eLife/Nature/Distill/JOSS): serif body + system-sans headings, a ~38rem
measure, one blue accent, off-black on off-white, booktabs tables, hanging-indent
references, light + dark via prefers-color-scheme.
"""

import html

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
  --warn-bg: #3a300f; --warn-fg: #f0d78a; --warn-rule: #7a6420;
  --ok-bg: #16301c; --ok-fg: #9fd9ab; --ok-rule: #2f5d39;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
.skip-link { position: absolute; left: -9999px; top: 0; background: var(--accent); color: var(--on-accent); padding: 0.5rem 0.9rem; border-radius: 0 0 4px 0; font-family: var(--sans); z-index: 10; }
.skip-link:focus { left: 0; }
a.backref { text-decoration: none; font-size: 0.85em; }
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
/* Dotted underline distinguishes a citation ref from a content link (solid) AND
   gives it a non-color distinction, which WCAG 1.4.1 requires for an inline link
   in a text block (axe link-in-text-block). */
article.body a.cite { text-decoration: underline dotted; font-variant-numeric: tabular-nums; }
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
ol.references { list-style: none; padding-left: 0; margin: 0.5rem 0; }
ol.references li { padding-left: 2.4em; text-indent: -2.4em; font-size: 0.9rem; line-height: 1.5; margin: 0.35rem 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
ol.references li:target { background: var(--surface); }
.hovercard { position: absolute; z-index: 50; max-width: min(90vw, 30rem); background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; box-shadow: 0 4px 18px rgba(0, 0, 0, 0.18); padding: 0.55rem 0.75rem; font-size: 0.85rem; line-height: 1.5; }
.hovercard[hidden] { display: none; }
.hovercard-body { overflow-wrap: anywhere; }
.hovercard-nav { display: flex; align-items: center; justify-content: flex-end; gap: 0.6rem; margin-top: 0.4rem; }
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
  var cites = [].slice.call(document.querySelectorAll("a.cite"));
  var refOrder = [];            // ref ids in first-citation document order (deduped)
  var seen = Object.create(null);
  for (var j = 0; j < cites.length; j++) {
    var href = cites[j].getAttribute("href");
    if (!href || href.charAt(0) !== "#") { continue; }
    var rid = href.slice(1);
    var ref = document.getElementById(rid);
    if (!ref) { continue; }
    cites[j].setAttribute("title", ref.textContent.replace(/\s+/g, " ").trim());
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
    card.appendChild(cbody); card.appendChild(cnav);
    document.body.appendChild(card);

    var hideTimer = null, curIdx = -1, curAnchor = null, pinned = false;
    function refFragment(id) {
      var frag = document.createDocumentFragment();
      var r = document.getElementById(id);
      if (!r) { return frag; }
      var kids = r.childNodes;
      for (var i = 0; i < kids.length; i++) {
        var k = kids[i];
        if (k.nodeType === 1 && k.classList && k.classList.contains("backref")) { continue; }
        frag.appendChild(k.cloneNode(true));
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
      if (curAnchor) { place(curAnchor); }
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
    cprev.addEventListener("click", function () { step(-1); });
    cnext.addEventListener("click", function () { step(1); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { dismiss(); } });
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


def site_footer(journal, root_rel):
    t = html.escape(journal["title"])
    issn = journal.get("issn", "")
    issn_bit = (" ISSN " + html.escape(issn)) if issn else ""
    nav = ""
    links = journal.get("footer_links") or []
    if links:
        items = []
        for link in links:
            href = link["href"]
            if not href.startswith(("http://", "https://")):
                href = root_rel + href   # root-relative, same targets every page
            items.append('<a href="%s">%s</a>'
                         % (html.escape(href, quote=True),
                            html.escape(link["title"])))
        nav = ('<nav class="footer-nav" aria-label="Footer">%s</nav>\n'
               % " ".join(items))
    return (
        '<footer class="site">%s<p>%s.%s</p></footer>'
        % (nav, t, issn_bit)
    )
