#!/usr/bin/python3 -Bsu
"""Venue submission-source emitters (md_to_tex_<venue>): structural checks.

pandoc is required (as for the other generate tests); these run in the sandbox
selftest. Compile-verification of the emitted .tex is a build-time step (not here);
this pins the generated FRONTMATTER + per-venue pandoc<->class fixes so a template
change that breaks a venue is caught without a full LaTeX run."""
import os
import tempfile
import unittest

from jmaker import generate as g

STUB_JOURNAL = {"title": "CSR", "base_url": "https://x", "language": "en"}


_DEFAULT_AUTHORS = ('authors = [{ name = "Patrick Schleizer", '
                    'institution = "Example Security Research", '
                    'email = "contact@example.org" }]\n')
_DEFAULT_KEYWORDS = 'keywords = ["remote attestation", "device integrity"]\n'


def _article(d, abstract="A concise abstract here now.", authors=_DEFAULT_AUTHORS,
             keywords=_DEFAULT_KEYWORDS):
    with open(os.path.join(d, "meta.toml"), "w", encoding="utf-8") as fh:
        fh.write(authors + 'date = "2026-10-24"\n' + keywords)
    with open(os.path.join(d, "paper.md"), "w", encoding="utf-8") as fh:
        fh.write("# A Venue Title\n\n## Abstract\n\n%s\n\n"
                 "## 1. Intro\n\nBody citing [@k1].\n\n"
                 "## References\n\n::: {#refs}\n:::\n" % abstract)
    with open(os.path.join(d, "refs.bib"), "w", encoding="utf-8") as fh:
        fh.write("@article{k1, title={{T}}, author={Doe, Jane}, "
                 "journal={J}, year={2024}, pages={1--2}}\n")
    return g.load_article(d)


def _emit(venue_id, **kw):
    with tempfile.TemporaryDirectory() as d:
        # clean slug subdir: a mkdtemp name may carry '_', which slug validation rejects
        art = os.path.join(d, "art")
        os.makedirs(art)
        m = _article(art, **kw)
        out = os.path.join(art, "o.tex")
        getattr(g, "md_to_tex_%s" % venue_id)(m, STUB_JOURNAL, out)
        with open(out, encoding="utf-8") as fh:
            return fh.read()


class TestVenueEmitters(unittest.TestCase):
    def test_elsarticle(self):
        tex = _emit("elsarticle")
        self.assertIn("\\documentclass[", tex)
        self.assertIn("{elsarticle}", tex)
        self.assertIn("\\begin{frontmatter}", tex)
        self.assertIn("\\author[1]{Patrick Schleizer}", tex)
        self.assertIn("\\ead{contact@example.org}", tex)
        self.assertIn("\\affiliation[1]{organization={Example Security Research}}", tex)
        self.assertIn("\\begin{keyword}", tex)
        self.assertIn("remote attestation \\sep device integrity", tex)
        self.assertIn("\\bibliographystyle{elsarticle-num}", tex)

    def test_ieeetran(self):
        tex = _emit("ieeetran")
        self.assertIn("{IEEEtran}", tex)
        # title + author in the PREAMBLE (before begin document), then maketitle
        pre = tex.split("\\begin{document}")[0]
        self.assertIn("\\title{A Venue Title}", pre)
        self.assertIn("\\author{Patrick Schleizer", pre)
        self.assertIn("\\maketitle", tex)
        self.assertIn("\\begin{IEEEkeywords}", tex)
        self.assertIn("\\bibliographystyle{IEEEtranN}", tex)

    def test_acmart_drops_amssymb_and_omits_affiliation(self):
        tex = _emit("acmart")
        self.assertIn("{acmart}", tex)
        # amssymb dropped (clashes with acmart's newtxmath \Bbbk)
        self.assertIn("\\usepackage{amsmath}", tex)
        self.assertNotIn("amssymb", tex)
        # no \country in our schema -> no \affiliation emitted (acmart would error)
        self.assertNotIn("\\affiliation", tex)
        self.assertIn("\\email{contact@example.org}", tex)
        self.assertIn("\\keywords{remote attestation, device integrity}", tex)
        self.assertIn("\\bibliographystyle{ACM-Reference-Format}", tex)

    def test_snjnl_strips_pandoc_bibstyle(self):
        tex = _emit("snjnl")
        self.assertIn("{sn-jnl}", tex)
        # the sn-jnl class sets its own \bibliographystyle from the class option;
        # pandoc's duplicate must be stripped (else bibtex: another \bibstyle)
        self.assertNotIn("\\bibliographystyle", tex)
        self.assertIn("\\author[1]{\\fnm{Patrick} \\sur{Schleizer}}", tex)
        self.assertIn("\\affil[1]{\\orgname{Example Security Research}}", tex)
        self.assertIn("\\abstract{", tex)

    def test_frontmatter_abstract_neutralizes_tex(self):
        # author abstract text must not inject TeX: pandoc's raw-TeX-disabled reader
        # escapes % and & and neutralizes a stray backslash (no raw \input command).
        tex = _emit("elsarticle", abstract=r"Cost 50% & up; try \input{x}.")
        self.assertIn("50\\% \\& up", tex)
        self.assertNotIn("\\input{x}", tex)
        self.assertIn("\\textbackslash", tex)  # backslash neutralized

    def test_plain_field_escapes_tex_specials(self):
        # name/email/institution/keywords are escaped (not converted); a TeX special
        # in a name cannot inject.
        tex = _emit("elsarticle",
                    authors='authors = [{name="A & B", email="a@x"}]\n')
        self.assertIn("A \\& B", tex)
        self.assertNotIn("A & B", tex)

    def test_all_known_venues_emit(self):
        for vid in g.VENUES:
            tex = _emit(vid)
            self.assertIn("\\begin{document}", tex)
            self.assertIn("\\bibliography{refs}", tex)

    def test_abstract_markdown_is_converted_not_escaped(self):
        # title/abstract go through pandoc so inline markup RENDERS instead of
        # showing as literal escaped source.
        tex = _emit("elsarticle", abstract="We prove *strong* security here.")
        self.assertIn("\\emph{strong}", tex)
        self.assertNotIn("*strong*", tex)

    def test_refs_strip_accepts_numbered_heading(self):
        # bodies that number every section may number References too; the .tex refs
        # strip must still drop the heading + empty #refs div (natbib re-adds the list).
        for heading in ("## References", "## 7. References", "## 11 References"):
            body = "Body text.\n\n%s\n\n::: {#refs}\n:::\n" % heading
            out = g._TEX_REFS_STRIP_RE.sub("", body)
            self.assertNotIn("References", out)
            self.assertNotIn("#refs", out)

    def test_ieeetran_per_author_affiliation(self):
        # each author's \thanks carries ONLY their own institution + email (a single
        # combined \thanks would lose the author<->affiliation mapping).
        authors = ('authors = [{name="Alice", institution="U1", email="a@x"}, '
                   '{name="Bob", institution="U2", email="b@y"}]\n')
        tex = _emit("ieeetran", authors=authors)
        self.assertIn("Alice\\thanks{U1; a@x}", tex)
        self.assertIn("Bob\\thanks{U2; b@y}", tex)

    def test_snjnl_field_newline_collapsed(self):
        # a blank line in a non-\long field (sn-jnl \email/\keywords) would be a
        # \par and break the compile; fields are one-lined.
        tex = _emit("snjnl", authors='authors = [{name="A", email="a@b.com\\n\\nx"}]\n')
        self.assertIn("\\email{a@b.com x}", tex)
        self.assertNotIn("a@b.com\n\nx", tex)

    def test_remote_image_in_author_field_rejected(self):
        # the paper.md build-time-fetch (SSRF) policy also covers author meta fields
        # (they are spliced into the docx markdown source). No pandoc needed.
        with tempfile.TemporaryDirectory() as d:
            art = os.path.join(d, "art")
            os.makedirs(art)
            bad = ('authors = [{ name = "A", '
                   'institution = "![p](https://127.0.0.1/secret.png)" }]\n')
            self.assertRaises(g.BuildError, _article, art, authors=bad)


if __name__ == "__main__":
    unittest.main()
