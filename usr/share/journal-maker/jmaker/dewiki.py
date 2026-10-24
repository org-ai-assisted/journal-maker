#!/usr/bin/python3 -Bsu
"""De-wiki drafting aid: MediaWiki source -> clean Markdown STARTING POINT.

Not the publish path. It produces a Markdown draft an editor then rewrites into
a paper (de-project-ify, academic tone, references). Steps:
  1. expand/strip known templates (mw_preprocess); unknown ones hard-error there.
  2. pandoc mediawiki -> GitHub-flavored Markdown (tables, refs, links).
  3. ASCII-normalize and drop any residual wiki internal links.

Map keys use chr(0x....) so this source file stays ASCII-only.
"""

import re
import subprocess

from jmaker import mw_preprocess

_ASCII_MAP = {
    chr(0x2018): "'", chr(0x2019): "'", chr(0x201c): '"', chr(0x201d): '"',
    chr(0x2013): "-", chr(0x2014): "--", chr(0x2026): "...", chr(0x00a0): " ",
    chr(0x2705): "Yes", chr(0x274c): "No", chr(0x26a0): "Warning", chr(0xfe0f): "",
}


def _ascii_normalize(s):
    for k, v in _ASCII_MAP.items():
        s = s.replace(k, v)
    return s


def convert_text(mw_text):
    pre = mw_preprocess.preprocess(mw_text)
    r = subprocess.run(
        ["pandoc", "-f", "mediawiki", "-t", "gfm", "--wrap=none"],
        input=pre, text=True, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("pandoc failed: %s" % (r.stderr or r.stdout))
    md = _ascii_normalize(r.stdout)
    # drop any residual wiki internal links the preprocess/pandoc left
    md = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", md)
    md = re.sub(r"\[\[([^\]]+)\]\]", r"\1", md)
    return md


def convert_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return convert_text(fh.read())
