#!/usr/bin/python3 -Bsu
import os
import tempfile
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
        self.assertIn(b"/Launch", c.ACTIVE_TOKENS)
        # /OpenAction is a benign trigger, deliberately NOT blocked
        self.assertNotIn(b"/OpenAction", c.ACTIVE_TOKENS)

    def test_dirname_url(self):
        self.assertEqual(
            c._dirname_url("https://h/v1/i1/x/x.pdf"), "https://h/v1/i1/x")

    def test_parse_paper_ignores_fenced_headings(self):
        md = ("```bash\n# not the title\n## Not Abstract\n```\n"
              "# Real Title\n\n## Abstract\n\nThe real abstract.\n\n"
              "## 1. Introduction\n\nBody text.\n")
        title, abstract, body = g._parse_paper(md, "x")
        self.assertEqual(title, "Real Title")
        self.assertEqual(abstract, "The real abstract.")
        self.assertTrue(body.startswith("## 1. Introduction"))


def _article_page(meta=None, h1="A Title", abstract="word " * 30,
                  body="Introduction body."):
    tags = {
        "citation_title": "A Title",
        "citation_author": "Jane Doe",
        "citation_publication_date": "2026/10/24",
        "citation_abstract_html_url": "https://h/v1/i1/x/",
        "citation_pdf_url": "https://h/v1/i1/x/x.pdf",
    }
    if meta:
        tags.update(meta)
    head = "\n".join('<meta name="%s" content="%s">' % (k, v)
                     for k, v in tags.items() if v is not None)
    return (
        "<!doctype html><html><head>%s</head><body>"
        '<h1 class="title">%s</h1>'
        '<section class="abstract"><h2>Abstract</h2><p>%s</p></section>'
        '<article class="body"><p>%s</p></article>'
        "</body></html>" % (head, h1, abstract, body))


class TestCheckerCanary(unittest.TestCase):
    """Prove the checker FAILS on bad input (guards against a neutered gate)."""

    def _run(self, page):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "index.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(page)
            f = c.Findings()
            c.check_article(path, f)
            return [m for _lvl, _p, m in f.errors]

    def test_missing_pdf_url_errors(self):
        msgs = self._run(_article_page(meta={"citation_pdf_url": None}))
        self.assertTrue(any("citation_pdf_url" in m for m in msgs))

    def test_title_mismatch_errors(self):
        msgs = self._run(_article_page(h1="Different Title"))
        self.assertTrue(any("!= visible" in m for m in msgs))

    def test_short_abstract_errors(self):
        msgs = self._run(_article_page(abstract="tiny"))
        self.assertTrue(any("abstract" in m for m in msgs))

    def test_wiki_markup_errors(self):
        msgs = self._run(_article_page(body="see [[SomePage]] here"))
        self.assertTrue(any("wiki internal link" in m for m in msgs))

    def test_bad_date_errors(self):
        msgs = self._run(_article_page(
            meta={"citation_publication_date": "2026/13/99"}))
        self.assertTrue(any("publication_date" in m for m in msgs))

    def test_wiki_markup_in_code_is_allowed(self):
        page = _article_page(
            body="example <code>[[ -f x ]]</code> and "
                 "<code>${{ secrets.X }}</code>")
        msgs = self._run(page)
        self.assertFalse(any("wiki" in m for m in msgs))


class TestPdfCanary(unittest.TestCase):
    def _check(self, data):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.pdf")
            with open(path, "wb") as fh:
                fh.write(data)
            f = c.Findings()
            c.check_pdf(path, f)
            return [m for _lvl, _p, m in f.errors]

    def test_not_a_pdf_errors(self):
        self.assertTrue(any("valid PDF" in m for m in self._check(b"hello")))

    def test_active_content_errors(self):
        data = b"%PDF-1.5\n" + b"x" * 1000 + b"/OpenAction /JavaScript\n"
        self.assertTrue(any("active content" in m for m in self._check(data)))


if __name__ == "__main__":
    unittest.main()
