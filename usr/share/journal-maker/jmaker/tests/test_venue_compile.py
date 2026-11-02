#!/usr/bin/python3 -Bsu
"""Compile-verify the generated submission sources end to end.

Emits the neutral + four venue .tex for a fixture article and compiles each with
pdflatex+bibtex, proving the generated LaTeX actually builds (the structural
test_venue.py cannot catch a class/package regression that only shows at compile).

Heavy and dependency-full ON PURPOSE: needs pandoc, the pandoc texlive set,
texlive-publishers (elsarticle/IEEEtran/acmart), texlive-plain-generic (binhex.tex
for acmart's hyperxmp), and the vendored sn-jnl. Run where those are installed (the
CI tests workflow, a provisioned sandbox); a missing tool/class fails LOUD, never a
skip. The fixture is multi-author with per-author affiliations, exercising the
IEEE per-author \\thanks + markdown-in-title/abstract paths too."""
import os
import tempfile
import unittest

from jmaker import generate as g

JOURNAL = {"title": "CSR", "base_url": "https://x", "language": "en"}

EMITTERS = {
    "neutral": "md_to_tex",
    "elsarticle": "md_to_tex_elsarticle",
    "ieeetran": "md_to_tex_ieeetran",
    "acmart": "md_to_tex_acmart",
    "snjnl": "md_to_tex_snjnl",
}


def _fixture(d):
    with open(os.path.join(d, "meta.toml"), "w", encoding="utf-8") as fh:
        fh.write('authors = [{ name = "Ada Lovelace", '
                 'institution = "Example Lab", email = "ada@example.org" }, '
                 '{ name = "Alan Turing", institution = "Other Lab" }]\n'
                 'date = "2026-10-24"\n'
                 'keywords = ["one", "two"]\n')
    with open(os.path.join(d, "paper.md"), "w", encoding="utf-8") as fh:
        fh.write("# A Compile Fixture with *emphasis*\n\n"
                 "## Abstract\n\nShort abstract with *emphasis* and an ampersand &.\n\n"
                 "## 1. Intro\n\nBody citing [@k1] and [@k2].\n\n"
                 "- a\n- b\n\n"
                 "## References\n\n::: {#refs}\n:::\n")
    with open(os.path.join(d, "refs.bib"), "w", encoding="utf-8") as fh:
        fh.write("@article{k1, title={{A}}, author={Doe, Jane}, journal={J}, "
                 "year={2024}, pages={1--2}}\n"
                 "@inproceedings{k2, title={{B}}, author={Roe, Rick}, "
                 "booktitle={P}, year={2023}, pages={3--4}}\n")
    return g.load_article(d)


class TestVenueCompile(unittest.TestCase):
    def test_all_formats_compile(self):
        with tempfile.TemporaryDirectory() as d:
            art = os.path.join(d, "art")
            os.makedirs(art)
            m = _fixture(art)
            for name, emitter in EMITTERS.items():
                with self.subTest(fmt=name):
                    out = os.path.join(art, "paper-%s.tex" % name)
                    getattr(g, emitter)(m, JOURNAL, out)
                    g.compile_tex(out)  # raises BuildError on failure


if __name__ == "__main__":
    unittest.main()
