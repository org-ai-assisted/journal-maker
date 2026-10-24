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

    def test_active_hits_detects_dangerous(self):
        self.assertEqual(c._active_hits({"/Names": {"/JavaScript": []}}),
                         {"/JavaScript"})
        self.assertIn("/Launch", c._active_hits({"/OpenAction": {"/S": "/Launch"}}))

    def test_active_hits_ignores_benign(self):
        # hyperref GoTo view, a hyperlink, a font subset name, a title mention
        benign = {"/OpenAction": {"/S": "/GoTo"},
                  "/Annots": [{"/S": "/URI", "/URI": "https://example.org"}],
                  "/Font": {"/BaseFont": "/JSTKMA+CMR10"},
                  "/Title": "Analysis of /JavaScript engines"}
        self.assertEqual(c._active_hits(benign), set())

    def test_dirname_url(self):
        self.assertEqual(
            c._dirname_url("https://h/v1/i1/x/x.pdf"), "https://h/v1/i1/x")

    def test_linkify_citations(self):
        html_in = ('<p>claim [5].</p><h2 id="references">References</h2>'
                   '<p>[5] Foo.</p>')
        out = g._linkify_citations(html_in)
        self.assertIn('href="#ref-5">[5]</a>', out)
        self.assertIn('<p id="ref-5">[5] Foo.', out)

    def test_build_toc(self):
        body = ('<h2 id="a">1. Intro</h2><h2 id="b">2. Bg</h2>'
                '<h2 id="c">3. More</h2>')
        toc = g._build_toc(body)
        self.assertIn('href="#a"', toc)
        self.assertIn("Contents", toc)

    def test_build_toc_short_is_empty(self):
        self.assertEqual(g._build_toc('<h2 id="a">Only</h2>'), "")

    def test_bibtex(self):
        bt = g._bibtex(META, JOURNAL, "https://h/v1/i1/x/")
        self.assertIn("@article{", bt)
        self.assertIn("title = {A Title}", bt)
        self.assertIn("author = {Jane Doe and Rick Roe}", bt)

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
            c.check_article(path, f, d)
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


class TestZenodo(unittest.TestCase):
    def test_build_metadata_maps_fields(self):
        from jmaker import zenodo
        m = dict(META)
        m["title"] = "A Title"
        m["abstract"] = "An   abstract."
        out = zenodo.build_metadata(m, JOURNAL, m["abstract"])["metadata"]
        self.assertEqual(out["title"], "A Title")
        self.assertEqual(out["upload_type"], "publication")
        self.assertEqual(out["publication_type"], "article")
        self.assertEqual(out["description"], "An abstract.")
        self.assertEqual(out["license"], "cc-by-4.0")
        self.assertEqual(out["journal_title"], "Computer Security Research")
        self.assertEqual(len(out["creators"]), 2)
        self.assertEqual(out["creators"][0]["affiliation"], "U")
        self.assertEqual(out["journal_pages"], "1-12")

    def test_write_doi_to_meta(self):
        from jmaker import zenodo
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "meta.toml")
            with open(mp, "w", encoding="utf-8") as fh:
                fh.write('date = "2026-10-24"\ndoi = ""\nvolume = 1\n')
            zenodo._write_doi_to_meta(d, "10.5281/zenodo.123")
            with open(mp, "r", encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn('doi = "10.5281/zenodo.123"', text)
            self.assertNotIn('doi = ""', text)


class TestLoading(unittest.TestCase):
    def _article(self, d, meta_toml):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "meta.toml"), "w", encoding="utf-8") as fh:
            fh.write(meta_toml)
        with open(os.path.join(d, "paper.md"), "w", encoding="utf-8") as fh:
            fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                     "validation purposes here.\n\n## 1. Intro\n\nBody.\n")

    def test_base_url_must_be_absolute(self):
        with tempfile.TemporaryDirectory() as d:
            jt = os.path.join(d, "journal.toml")
            with open(jt, "w", encoding="utf-8") as fh:
                fh.write('title = "J"\nbase_url = "/journal"\n')
            with self.assertRaises(g.BuildError):
                g.load_journal(jt)

    def test_bad_slug_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, 'slug = "../evil"\nvolume = 1\nissue = 1\n'
                              'date = "2026-10-24"\nauthors = [{name = "A"}]\n')
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_empty_author_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, 'volume = 1\nissue = 1\ndate = "2026-10-24"\n'
                              'authors = [{name = ""}]\n')
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_out_overlapping_articles_refused(self):
        with tempfile.TemporaryDirectory() as d:
            jt = os.path.join(d, "journal.toml")
            with open(jt, "w", encoding="utf-8") as fh:
                fh.write('title = "J"\nbase_url = "https://e.example"\n')
            arts = os.path.join(d, "articles")
            os.makedirs(arts)
            with self.assertRaises(g.BuildError):
                g.build(arts, jt, arts)  # out == articles dir

    def test_base_url_requires_authority(self):
        with tempfile.TemporaryDirectory() as d:
            jt = os.path.join(d, "journal.toml")
            with open(jt, "w", encoding="utf-8") as fh:
                fh.write('title = "J"\nbase_url = "https:///"\n')
            with self.assertRaises(g.BuildError):
                g.load_journal(jt)

    def test_float_volume_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, 'volume = 1.5\nissue = 1\ndate = "2026-10-24"\n'
                              'authors = [{name = "A"}]\n')
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_negative_volume_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, 'volume = -1\nissue = 1\ndate = "2026-10-24"\n'
                              'authors = [{name = "A"}]\n')
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_remote_image_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            os.makedirs(ad)
            with open(os.path.join(ad, "meta.toml"), "w", encoding="utf-8") as fh:
                fh.write('volume = 1\nissue = 1\ndate = "2026-10-24"\n'
                         'authors = [{name = "A"}]\n')
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation.\n\n## 1. Intro\n\n"
                         "![x](https://evil.example/x.png)\n")
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_out_site_inside_content_allowed(self):
        # a normal _site under the content root must NOT trip the guard; it fails
        # later (no articles), which is a different, expected error
        with tempfile.TemporaryDirectory() as d:
            jt = os.path.join(d, "journal.toml")
            with open(jt, "w", encoding="utf-8") as fh:
                fh.write('title = "J"\nbase_url = "https://e.example"\n')
            os.makedirs(os.path.join(d, "articles"))
            try:
                g.build(os.path.join(d, "articles"), jt, os.path.join(d, "_site"))
            except g.BuildError as exc:
                self.assertNotIn("would delete", str(exc))
                self.assertNotIn("inside the", str(exc))


class TestCheckerLocation(unittest.TestCase):
    def _run(self, meta):
        with tempfile.TemporaryDirectory() as out:
            d = os.path.join(out, "v1", "i1", "x")
            os.makedirs(d)
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(_article_page(meta=meta))
            f = c.Findings()
            c.check_article(os.path.join(d, "index.html"), f, out)
            return [m for _lvl, _p, m in f.errors]

    def test_wrong_location_errors(self):
        msgs = self._run({"citation_pdf_url": "https://h/wrong/x.pdf",
                          "citation_abstract_html_url": "https://h/v1/i1/x/"})
        self.assertTrue(any("not at the article" in m for m in msgs))

    def test_correct_location_no_location_error(self):
        msgs = self._run({"citation_pdf_url": "https://h/v1/i1/x/x.pdf",
                          "citation_abstract_html_url": "https://h/v1/i1/x/"})
        self.assertFalse(any("not at the article" in m for m in msgs))

    def test_relative_pdf_url_errors(self):
        msgs = self._run({"citation_pdf_url": "x.pdf",
                          "citation_abstract_html_url": "https://h/v1/i1/x/"})
        self.assertTrue(any("absolute" in m for m in msgs))

    def test_off_origin_pdf_errors(self):
        msgs = self._run({"citation_pdf_url": "https://evil.example/v1/i1/x/x.pdf",
                          "citation_abstract_html_url": "https://h/v1/i1/x/"})
        self.assertTrue(any("origin" in m for m in msgs))


class TestAsciiGate(unittest.TestCase):
    def test_non_ascii_output_errors(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "page.html"), "w", encoding="utf-8") as fh:
                fh.write("<p>em" + chr(0x2014) + "dash, curly" + chr(0x2019) + "q</p>")
            f = c.Findings()
            c.check_ascii(d, f)
            self.assertTrue(any("ASCII-only" in m for _l, _p, m in f.errors))

    def test_ascii_output_ok(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "page.html"), "w", encoding="utf-8") as fh:
                fh.write("<p>plain ascii -- ok</p>")
            f = c.Findings()
            c.check_ascii(d, f)
            self.assertEqual(f.errors, [])


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

    def test_prepended_junk_rejected(self):
        # non-whitespace before %PDF- is rejected (a leading newline is tolerated)
        self.assertTrue(any("valid PDF" in m
                            for m in self._check(b"<script>x</script>\n%PDF-1.5")))


if __name__ == "__main__":
    unittest.main()
