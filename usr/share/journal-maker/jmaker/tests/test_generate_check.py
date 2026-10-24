#!/usr/bin/python3 -Bsu
import unittest

from jmaker import check as c
from jmaker import generate as g


JOURNAL = {"title": "Computer Security Research", "language": "en",
           "base_url": "https://computer-security-research.github.io",
           "issn": "", "publisher": "CSR", "license": "CC-BY-4.0",
           "license_url": "https://creativecommons.org/licenses/by/4.0/"}

META = {"slug": "x", "title": "A Title", "volume": 1, "issue": 1,
        "date": "2026-10-24", "online_date": "2026-10-24",
        "authors": [{"name": "Jane Doe", "institution": "U"},
                    {"name": "Rick Roe"}],
        "abstract": "An abstract.", "keywords": ["k1", "k2"],
        "firstpage": 1, "lastpage": 12, "doi": ""}


class TestGenerateHelpers(unittest.TestCase):
    def test_scholar_date(self):
        self.assertEqual(g._scholar_date("2026-10-24"), "2026/10/24")
        self.assertEqual(g._scholar_date("2026"), "2026")

    def test_rel_dir_and_root_rel(self):
        self.assertEqual(g._rel_dir(META), "v1/i1/x")
        self.assertEqual(g._root_rel("v1/i1/x"), "../../../")

    def test_yaml_dq_escapes(self):
        self.assertEqual(g._yaml_dq('a"b\\c'), '"a\\"b\\\\c"')

    def test_citation_meta_has_required(self):
        landing = "https://computer-security-research.github.io/v1/i1/x/"
        pdf = landing + "x.pdf"
        meta = g.citation_meta(META, JOURNAL, landing, pdf)
        self.assertIn('name="citation_title" content="A Title"', meta)
        self.assertEqual(meta.count('name="citation_author"'), 2)
        self.assertIn('citation_author_institution', meta)
        self.assertIn('content="2026/10/24"', meta)
        self.assertIn('citation_pdf_url" content="%s"' % pdf, meta)
        self.assertIn('citation_journal_title', meta)
        # empty issn/doi must be omitted, not emitted blank
        self.assertNotIn("citation_issn", meta)
        self.assertNotIn("citation_doi", meta)


class TestChecker(unittest.TestCase):
    def test_collect_meta(self):
        page = ('<meta name="citation_title" content="T">'
                '<meta name="citation_author" content="A">'
                '<meta name="citation_author" content="B">')
        m = c._collect_meta(page)
        self.assertEqual(m["citation_title"], "T")
        self.assertEqual(m["citation_author"], ["A", "B"])

    def test_text_only_strips_tags(self):
        self.assertEqual(c._text_only("<h1>Hi <b>there</b></h1>"), "Hi there")

    def test_wiki_markup_detected(self):
        self.assertTrue(c._WIKI_LINK_RE.search("see [[Foo]] now"))
        self.assertTrue(c._WIKI_TMPL_RE.search("a {{tmpl}} b"))

    def test_active_tokens_present(self):
        self.assertIn(b"/JavaScript", c.ACTIVE_TOKENS)
        self.assertIn(b"/OpenAction", c.ACTIVE_TOKENS)

    def test_dirname_url(self):
        self.assertEqual(
            c._dirname_url("https://h/v1/i1/x/x.pdf"), "https://h/v1/i1/x")


if __name__ == "__main__":
    unittest.main()
