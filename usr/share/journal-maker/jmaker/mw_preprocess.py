#!/usr/bin/python3 -Bsu
"""Preprocess MediaWiki wikitext into a clean, template-free dialect pandoc can read.

Why: pandoc's mediawiki reader does not expand templates ({{...}}). Kicksecure
wiki source uses custom templates that carry real content ({{quotation}},
{{intro}}, {{Anchor}}) plus site chrome ({{Header}}, {{Footer}}, {{#seo:...}}).
This maps the content-bearing templates to standard markup, drops the chrome,
and HARD-ERRORS on any unknown template -- content is never silently dropped.

Scope: handles top-level and nested {{...}}, splitting args on pipes that are
not inside [[...]], {{...}}, or <tag>...</tag>. Not a full MediaWiki parser;
the unknown-template error is the backstop.
"""

import re

# Chrome / metadata templates: no article content -> drop entirely.
_CHROME = {
    "header", "footer", "mobile_mininav", "title", "mininav",
}


class UnknownTemplate(Exception):
    """Raised when a template has no handler, so the build fails loudly."""


def _split_args(body):
    """Split a template body on top-level '|', respecting [[]], {{}}, <>.

    Returns the raw segments (name is segments[0]).
    """
    segs, depth_sq, depth_br, depth_ang, buf = [], 0, 0, 0, []
    i, n = 0, len(body)
    while i < n:
        two = body[i:i + 2]
        c = body[i]
        if two == "[[":
            depth_sq += 1; buf.append(two); i += 2; continue
        if two == "]]":
            depth_sq = max(0, depth_sq - 1); buf.append(two); i += 2; continue
        if two == "{{":
            depth_br += 1; buf.append(two); i += 2; continue
        if two == "}}":
            depth_br = max(0, depth_br - 1); buf.append(two); i += 2; continue
        if c == "<":
            depth_ang += 1; buf.append(c); i += 1; continue
        if c == ">":
            depth_ang = max(0, depth_ang - 1); buf.append(c); i += 1; continue
        if c == "|" and depth_sq == 0 and depth_br == 0 and depth_ang == 0:
            segs.append("".join(buf)); buf = []; i += 1; continue
        buf.append(c); i += 1
    segs.append("".join(buf))
    return segs


def _parse_args(segs):
    """Return (name, positional_list, named_dict) from raw segments."""
    name = segs[0].strip()
    pos, named = [], {}
    for seg in segs[1:]:
        if "=" in seg:
            k, _, v = seg.partition("=")
            # A '=' only counts as a named arg when the key is a single bare
            # token (no spaces) -- so prose like "Let x = 1" stays positional.
            if re.fullmatch(r"\s*[\w.-]+\s*", k):
                named[k.strip()] = v.strip()
                continue
        pos.append(seg.strip())
    return name, pos, named


def _find_template(text, start):
    """Find the next top-level {{...}} at or after start. Returns (s, e) or None."""
    s = text.find("{{", start)
    if s < 0:
        return None
    depth, i = 0, s
    while i < len(text):
        if text[i:i + 2] == "{{":
            depth += 1; i += 2; continue
        if text[i:i + 2] == "}}":
            depth -= 1; i += 2
            if depth == 0:
                return (s, i)
            continue
        i += 1
    return None  # unbalanced; treated as no-match (checker will catch leftovers)


def _handle(name, pos, named):
    """Map one template to standard markup. Raise UnknownTemplate otherwise."""
    low = name.lower()
    if low in _CHROME:
        return ""
    if low.startswith("#"):
        # #seo emits only metadata (no visible content), so drop it; any other
        # parser function may carry content, so refuse rather than silently drop.
        if low.startswith("#seo"):
            return ""
        raise UnknownTemplate(name)
    if low == "intro":
        body = named.get("1") or (pos[0] if pos else "")
        return body.strip() + "\n\n"
    if low == "quotation":
        quote = named.get("quote", pos[0] if pos else "").strip()
        ctx = named.get("context", "").strip()
        out = "<blockquote>\n" + quote
        if ctx:
            out += "<br>\n-- " + ctx
        return out + "\n</blockquote>\n\n"
    if low == "anchor":
        # {{Anchor|show=true|Label}} renders a visible pseudo-heading;
        # anchor-only form has no visible output.
        show = named.get("show", "").lower() == "true"
        label = pos[-1].strip() if pos else ""
        return ("\n=== " + label + " ===\n\n") if (show and label) else ""
    if low == "os":
        return (pos[0].strip() + " ") if pos else ""
    if low == "videolink":
        url = named.get("url") or (pos[0] if pos else "")
        title = named.get("title", "Video")
        return "[%s %s]\n\n" % (url.strip(), title.strip()) if url else ""
    raise UnknownTemplate(name)


def preprocess(text):
    """Expand known templates; raise UnknownTemplate on any unhandled one.

    Runs iteratively so nested templates (a known template inside another) are
    resolved from the inside out.
    """
    for _ in range(50):  # bounded; deep nesting beyond this is pathological
        span = _find_template(text, 0)
        if span is None:
            break
        changed = False
        out, pos_cur = [], 0
        while span is not None:
            s, e = span
            inner = text[s + 2:e - 2]
            # Outer template still contains a template: DESCEND into it (search
            # from just after this '{{') so the innermost is expanded first.
            if "{{" in inner:
                span = _find_template(text, s + 2)
                continue
            name, p, nd = _parse_args(_split_args(inner))
            repl = _handle(name, p, nd)
            out.append(text[pos_cur:s]); out.append(repl)
            pos_cur = e
            changed = True
            span = _find_template(text, e)
        out.append(text[pos_cur:])
        text = "".join(out)
        if not changed:
            break
    return text


if __name__ == "__main__":
    import sys
    sys.stdout.write(preprocess(sys.stdin.read()))
