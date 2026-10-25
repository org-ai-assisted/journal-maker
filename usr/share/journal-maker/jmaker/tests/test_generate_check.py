#!/usr/bin/python3 -Bsu
import json
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
        self.assertIn('<p id="ref-5">[5] ', out)
        self.assertIn('href="#cite-5"', out)   # backlink to first mention
        self.assertIn("Foo.", out)

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

    def test_build_metadata_sets_prereserve_doi(self):
        # reserve() reads the reserved DOI back from metadata.prereserve_doi.doi;
        # the request must ask Zenodo to reserve one.
        from jmaker import zenodo
        out = zenodo.build_metadata(dict(META), JOURNAL, "x")["metadata"]
        self.assertIs(out["prereserve_doi"], True)

    def test_pdf_reader_disables_raw_attribute(self):
        # A fenced ```{=latex} / ```{=html} block must not pass through to the
        # engine; the PDF reader disables raw_attribute like the HTML reader.
        from jmaker import zenodo  # noqa: F401 (keep import parity with class)
        captured = {}

        def fake_run(argv, **kw):
            captured["argv"] = argv
            class R:
                stdout = ""
            return R()
        orig = g._run
        g._run = fake_run
        self.addCleanup(lambda: setattr(g, "_run", orig))
        m = dict(META)
        m["doi"] = ""
        m["_body_md"] = "body\n"
        m["_dir"] = "/nonexistent"
        g.md_to_pdf(m, JOURNAL, "/dev/null")
        argv = captured["argv"]
        fmt = argv[argv.index("-f") + 1]
        self.assertIn("-raw_attribute", fmt)

    def test_reserve_refuses_second_reservation(self):
        # A second reserve would orphan the first deposition; refuse it and never
        # hit the API.
        from jmaker import zenodo

        def boom(*a, **k):
            raise RuntimeError("_api must not be called when refusing")
        orig = zenodo._api
        zenodo._api = boom
        self.addCleanup(lambda: setattr(zenodo, "_api", orig))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".zenodo.json"), "w", encoding="utf-8") as fh:
                json.dump({"deposition_id": 1, "doi": "10.5281/zenodo.1"}, fh)
            with self.assertRaises(zenodo.ZenodoError) as cm:
                zenodo.reserve(d, "journal.toml", zenodo.SANDBOX, "tok")
            self.assertIn("already records", str(cm.exception))

    def test_publish_rejects_pdf_without_doi(self):
        # Publishing is irreversible; a PDF lacking the reserved DOI is refused
        # before any API call.
        from jmaker import zenodo

        def boom(*a, **k):
            raise RuntimeError("_api must not be called when refusing")
        orig_api, orig_txt = zenodo._api, zenodo._pdf_text
        zenodo._api = boom
        zenodo._pdf_text = lambda p: "unrelated text, no doi here"
        self.addCleanup(lambda: setattr(zenodo, "_api", orig_api))
        self.addCleanup(lambda: setattr(zenodo, "_pdf_text", orig_txt))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".zenodo.json"), "w", encoding="utf-8") as fh:
                json.dump({"deposition_id": 1, "doi": "10.5281/zenodo.123",
                           "bucket": "https://sandbox.zenodo.org/api/files/x",
                           "base": zenodo.SANDBOX}, fh)
            pdf = os.path.join(d, "a.pdf")
            with open(pdf, "wb") as fh:
                fh.write(b"%PDF-1.4 dummy")
            with self.assertRaises(zenodo.ZenodoError) as cm:
                zenodo.publish(d, pdf, zenodo.SANDBOX, "tok")
            self.assertIn("reserved DOI", str(cm.exception))

    def test_publish_accepts_pdf_with_doi(self):
        # The matching PDF passes the guard and the upload + publish calls run.
        from jmaker import zenodo
        calls = []

        def rec(method, url, token, **k):
            calls.append((method, url))
            return {"doi": "10.5281/zenodo.123"}
        orig_api, orig_txt = zenodo._api, zenodo._pdf_text
        zenodo._api = rec
        zenodo._pdf_text = lambda p: "title ... DOI: 10.5281/zenodo.123 ... body"
        self.addCleanup(lambda: setattr(zenodo, "_api", orig_api))
        self.addCleanup(lambda: setattr(zenodo, "_pdf_text", orig_txt))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".zenodo.json"), "w", encoding="utf-8") as fh:
                json.dump({"deposition_id": 1, "doi": "10.5281/zenodo.123",
                           "bucket": "https://sandbox.zenodo.org/api/files/x",
                           "base": zenodo.SANDBOX}, fh)
            pdf = os.path.join(d, "a.pdf")
            with open(pdf, "wb") as fh:
                fh.write(b"%PDF-1.4 dummy")
            self.assertEqual(zenodo.publish(d, pdf, zenodo.SANDBOX, "tok"), 0)
        self.assertEqual(len(calls), 2)


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

    def test_non_string_keyword_rejected(self):
        # A non-string keyword would crash JSON-LD/meta rendering later; reject
        # it at load with a clean error.
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, 'volume = 1\nissue = 1\ndate = "2026-10-24"\n'
                              'authors = [{name = "A"}]\nkeywords = ["ok", 1]\n')
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


class TestCitationParity(unittest.TestCase):
    def _run(self, page):
        f = c.Findings()
        c.check_citation_parity(page, "p", f)
        return [m for _l, _p, m in f.errors]

    def test_clean(self):
        page = '<a href="#ref-1">[1]</a><p id="ref-1">[1] X.</p>'
        self.assertEqual(self._run(page), [])

    def test_dangling_citation(self):
        page = '<a href="#ref-2">[2]</a><p id="ref-1">[1] X.</p>'
        self.assertTrue(any("no reference entry" in m for m in self._run(page)))

    def test_uncited_reference(self):
        page = ('<a href="#ref-1">[1]</a><p id="ref-1">[1] X.</p>'
                '<p id="ref-2">[2] Y.</p>')
        self.assertTrue(any("never cited" in m for m in self._run(page)))

    def test_duplicate_reference(self):
        page = ('<a href="#ref-1">[1]</a><p id="ref-1">[1] X.</p>'
                '<p id="ref-1">[1] dup.</p>')
        self.assertTrue(any("duplicate" in m for m in self._run(page)))

    def test_no_citations_ok(self):
        self.assertEqual(self._run("<p>no citations here</p>"), [])


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


class TestStatus(unittest.TestCase):
    def _article(self, d, meta_toml):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "meta.toml"), "w", encoding="utf-8") as fh:
            fh.write(meta_toml)
        with open(os.path.join(d, "paper.md"), "w", encoding="utf-8") as fh:
            fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                     "validation purposes here.\n\n## 1. Intro\n\nBody.\n")

    _BASE = 'volume = 1\nissue = 1\ndate = "2026-10-24"\nauthors = [{name = "A"}]\n'

    def test_default_status_is_draft(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, self._BASE)
            self.assertEqual(g.load_article(ad)["status"], "draft")

    def test_invalid_status_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, self._BASE + 'status = "final"\n')
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_corrected_requires_date(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, self._BASE + 'status = "corrected"\n')
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_corrected_bad_url_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, self._BASE + 'status = "corrected"\n'
                          'corrected_date = "2026-10-25"\n'
                          'correction_url = "javascript:evil"\n')
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_corrected_valid(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, self._BASE + 'status = "corrected"\n'
                          'corrected_date = "2026-10-25"\n')
            m = g.load_article(ad)
            self.assertEqual(m["status"], "corrected")
            self.assertEqual(m["corrected_date"], "2026-10-25")

    def test_fragment_draft(self):
        pill, banner, line, head = g._status_fragment({"status": "draft"})
        self.assertIn("status-pill status-draft", pill)
        self.assertIn("status-banner status-draft", banner)
        self.assertIn("not peer reviewed", line)
        self.assertIn('content="draft"', head)

    def test_fragment_published_has_no_banner(self):
        pill, banner, line, head = g._status_fragment({"status": "published"})
        self.assertEqual(banner, "")
        self.assertIn("status-pill status-published", pill)
        self.assertIn('content="published"', head)

    def test_fragment_corrected_banner_has_date(self):
        _p, banner, _l, _h = g._status_fragment(
            {"status": "corrected", "corrected_date": "2026-10-25",
             "correction_url": "https://e.example/notice"})
        self.assertIn("status-banner status-corrected", banner)
        self.assertIn("2026-10-25", banner)
        self.assertIn("https://e.example/notice", banner)

    def test_jsonld_has_status_and_escapes(self):
        j = g._jsonld({"title": "A <b> title", "authors": [{"name": "A"}],
                       "date": "2026-10-24", "status": "draft"},
                      {"title": "J", "publisher": "University Press"},
                      "https://e.example/x/")
        self.assertIn('"creativeWorkStatus": "Draft"', j)
        self.assertNotIn("<b>", j)            # breakout chars neutralized
        self.assertIn("\\u003c", j)
        self.assertIn('"name": "University Press"', j)   # publisher, not title

    def test_corrected_with_todo_marker_errors(self):
        # corrected is a version of record too, so unresolved notes are rejected.
        page = self._META % "corrected" + (
            '<aside class="status-banner status-corrected">x</aside>'
            "<p><strong>TODO:</strong> verify</p>")
        self.assertTrue(any("TODO edit-marker" in m for m in self._lint(page)))

    def test_todo_group_prose_not_flagged(self):
        # "TODO Group" (the FOSS org) in bold prose is not an edit-marker.
        page = self._META % "published" + "<p><strong>TODO Group</strong> x</p>"
        self.assertEqual(self._lint(page), [])

    def _lint(self, page):
        f = c.Findings()
        c.check_release_state(page, "p.html", f)
        return [m for _lvl, _p, m in f.errors]

    _META = '<meta name="article_status" content="%s">'

    def test_published_with_todo_marker_errors(self):
        page = self._META % "published" + "<p><strong>TODO:</strong> fix</p>"
        self.assertTrue(any("TODO edit-marker" in m for m in self._lint(page)))

    def test_published_with_nonbold_todo_marker_errors(self):
        # Regression: a marker that lost its bold (here in a heading) must still
        # block a publish -- the old bold-only gate missed exactly this.
        page = self._META % "published" + "<h3>TODO: resolve the DOI</h3>"
        self.assertTrue(any("TODO edit-marker" in m for m in self._lint(page)))

    def test_published_plaintext_todo_marker_errors(self):
        page = self._META % "published" + "<p>TODO(editorial): tighten this</p>"
        self.assertTrue(any("TODO edit-marker" in m for m in self._lint(page)))

    def test_published_todo_in_code_example_ok(self):
        # A genuine "# TODO:" inside a code example is not an unresolved note.
        page = (self._META % "published"
                + "<pre><code># TODO: handle EOF</code></pre>")
        self.assertEqual(self._lint(page), [])

    def test_published_todo_group_plaintext_not_flagged(self):
        # Non-bold "TODO Group" (the FOSS org) must still pass the broadened scan.
        page = self._META % "published" + "<p>maintained by the TODO Group.</p>"
        self.assertEqual(self._lint(page), [])

    def test_published_clean_ok(self):
        page = self._META % "published" + "<p>clean body</p>"
        self.assertEqual(self._lint(page), [])

    def test_draft_without_banner_errors(self):
        page = self._META % "draft" + "<p>body</p>"
        self.assertTrue(any("not-peer-reviewed banner" in m
                            for m in self._lint(page)))

    def test_draft_with_banner_ok(self):
        page = (self._META % "draft"
                + '<aside class="status-banner status-draft">x</aside>')
        self.assertEqual(self._lint(page), [])

    def test_missing_status_meta_errors(self):
        self.assertTrue(any("missing article_status" in m
                            for m in self._lint("<p>no meta</p>")))


class TestEnDash(unittest.TestCase):
    def test_html_prose_dash(self):
        self.assertEqual(g._endash_html("<p>a -- b</p>"), "<p>a &ndash; b</p>")

    def test_html_code_preserved(self):
        out = g._endash_html("<code>cmd -- arg</code> x -- y")
        self.assertIn("<code>cmd -- arg</code>", out)
        self.assertIn("x &ndash; y", out)

    def test_md_prose_dash(self):
        self.assertEqual(g._endash_md("a -- b"), "a " + chr(0x2013) + " b")

    def test_md_fence_preserved(self):
        out = g._endash_md("```\nx -- y\n```\na -- b")
        self.assertIn("x -- y", out)            # fenced: untouched
        self.assertIn("a " + chr(0x2013) + " b", out)

    def test_md_inline_code_preserved(self):
        self.assertEqual(g._endash_md("run `foo -- bar` now -- then"),
                         "run `foo -- bar` now " + chr(0x2013) + " then")

    def test_md_tilde_fence_preserved(self):
        out = g._endash_md("~~~sh\ncmd -- arg\n~~~\na -- b")
        self.assertIn("cmd -- arg", out)            # tilde-fenced: untouched
        self.assertIn("a " + chr(0x2013) + " b", out)


class TestRefLinksAndMeta(unittest.TestCase):
    def test_citation_backlink_and_anchor(self):
        src = ("<p>see [1] and again [1].</p>"
               "<h2>References</h2><p>[1] A. Author. Title.</p>")
        out = g._linkify_citations(src)
        self.assertIn('id="cite-1"', out)          # first mention anchored
        self.assertEqual(out.count('id="cite-1"'), 1)
        self.assertIn('href="#ref-1"', out)        # forward link
        self.assertIn('href="#cite-1"', out)        # backlink from the entry
        self.assertIn('<p id="ref-1">', out)

    def test_reference_url_linkified(self):
        src = ("<p>x [1].</p><h2>References</h2>"
               "<p>[1] Title. https://e.example/a/b (accessed).</p>")
        out = g._linkify_citations(src)
        self.assertIn('<a href="https://e.example/a/b">https://e.example/a/b</a>',
                      out)

    def test_reference_doi_linkified(self):
        src = ("<p>x [1].</p><h2>References</h2>"
               "<p>[1] Title. doi: 10.1109/ABC.2020.123.</p>")
        out = g._linkify_citations(src)
        self.assertIn('href="https://doi.org/10.1109/ABC.2020.123"', out)

    def test_reference_url_href_escaped(self):
        # A '"' in a reference URL must be escaped, not smuggle an attribute past
        # the sanitizer (linkify runs after _sanitize_html).
        src = ('<p>x [1].</p><h2>References</h2>'
               '<p>[1] P. https://e.example/x"onmouseover=alert(1)</p>')
        out = g._linkify_citations(src)
        self.assertNotIn('"onmouseover=', out)
        self.assertIn("&quot;onmouseover=", out)

    def test_reference_url_balanced_paren(self):
        # A ')' that closes a '(' in the URL stays inside the link.
        src = ("<p>x [1].</p><h2>References</h2>"
               "<p>[1] P. https://en.wikipedia.org/wiki/Foo_(bar)</p>")
        out = g._linkify_citations(src)
        self.assertIn('href="https://en.wikipedia.org/wiki/Foo_(bar)"', out)

    def test_linkify_citations_skips_code(self):
        # An array index inside <code> is not a citation.
        src = ('<p>claim [1]. <code>arr[2]</code></p>'
               '<h2>References</h2><p>[1] A.</p>')
        out = g._linkify_citations(src)
        self.assertIn('href="#ref-1"', out)
        self.assertNotIn('href="#ref-2"', out)
        self.assertIn("<code>arr[2]</code>", out)

    def test_linkify_citations_combined_and_range(self):
        # [1, 2] and [3-5] linkify every number so parity sees them cited.
        src = ("<p>a [1, 2] b [3-5].</p><h2>References</h2>"
               "<p>[1] A.</p><p>[2] B.</p><p>[3] C.</p><p>[4] D.</p><p>[5] E.</p>")
        out = g._linkify_citations(src)
        for n in ("1", "2", "3", "4", "5"):
            self.assertIn('href="#ref-%s"' % n, out)
        f = c.Findings()
        c.check_citation_parity(out, "p", f)
        self.assertEqual(f.errors, [])

    def test_csp_meta_present(self):
        page = g.render_homepage([], dict(JOURNAL), [])
        self.assertIn("Content-Security-Policy", page)
        self.assertIn("default-src 'none'", page)
        self.assertIn("script-src 'self'", page)        # one self-hosted bundle
        self.assertIn("require-trusted-types-for 'script'", page)
        self.assertIn("trusted-types 'none'", page)
        self.assertNotIn("unsafe-inline", page)        # no inline escape hatch
        self.assertNotIn("unsafe-eval", page)          # no eval / wasm
        self.assertIn("journal.js", page)              # bundle referenced
        self.assertNotIn("frame-ancestors", g._csp_meta())  # meta cannot set it

    def test_security_headers_and_headers_file(self):
        with tempfile.TemporaryDirectory() as d:
            g.write_headers(d)
            with open(os.path.join(d, "_headers"), encoding="utf-8") as fh:
                h = fh.read()
            self.assertTrue(h.startswith("/*\n"))
            self.assertIn("frame-ancestors 'none'", h)   # header-only directive
            self.assertIn("Permissions-Policy:", h)
            self.assertIn("Cross-Origin-Opener-Policy: same-origin", h)
            self.assertIn("X-Frame-Options: DENY", h)
            self.assertIn("clipboard-write=(self)", h)   # copy buttons need it

    def test_js_bundle_is_tt_safe(self):
        from jmaker import templates
        js = templates.JOURNAL_JS
        # Trusted-Types-safe: no DOM-XSS sinks, so it runs under trusted-types 'none'.
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML",
                     "document.write", "eval(", "new Function"):
            self.assertNotIn(sink, js)
        self.assertIn("navigator.clipboard", js)        # copy
        self.assertIn('setAttribute("title"', js)        # hover preview
        self.assertIn('"lightbox"', js)                  # figure lightbox

    def test_opengraph_tags(self):
        og = g._opengraph({"title": "T"}, {"title": "J"}, "https://e.example/x/",
                          "An abstract.")
        self.assertIn('property="og:title" content="T"', og)
        self.assertIn('name="twitter:card" content="summary"', og)

    def test_write_feed(self):
        with tempfile.TemporaryDirectory() as d:
            arts = [{"volume": 1, "issue": 1, "slug": "x", "title": "T",
                     "date": "2026-10-24", "abstract": "A long enough abstract."}]
            g.write_feed(arts, dict(JOURNAL), d)
            with open(os.path.join(d, "feed.xml"), encoding="utf-8") as fh:
                xml = fh.read()
            self.assertIn("<item>", xml)
            self.assertIn("<title>T</title>", xml)
            self.assertIn("2026", xml)


class TestIdentityAndCite(unittest.TestCase):
    _M = {"title": "T", "authors": [{"name": "Jane Doe"}], "date": "2026-10-24",
          "volume": 1, "issue": 2, "abstract": "An abstract."}

    def test_authors_orcid(self):
        m = {"authors": [{"name": "Jane Doe",
                          "orcid": "0000-0002-1825-0097"}]}
        out = g._authors_html(m)
        self.assertIn("https://orcid.org/0000-0002-1825-0097", out)
        self.assertIn("Jane Doe", out)

    def test_authors_no_orcid(self):
        self.assertEqual(g._authors_html({"authors": [{"name": "Jane Doe"}]}),
                         "Jane Doe")

    def test_history_line(self):
        self.assertIn("Received 2026-01-01",
                      g._history_line({"received": "2026-01-01",
                                       "date": "2026-10-24"}))
        self.assertEqual(g._history_line({"date": "2026-10-24"}), "")

    def test_subjects_line(self):
        self.assertIn("cs.CR", g._subjects_line({"subjects": ["cs.CR"]}))
        self.assertEqual(g._subjects_line({}), "")

    def test_license_footer(self):
        out = g._license_footer(self._M, {"license": "CC-BY-4.0",
                                          "license_url": "https://e.example/by"})
        self.assertIn("cc-badge", out)
        self.assertIn("(c) 2026", out)
        self.assertEqual(g._license_footer(self._M, {}), "")

    def test_statements(self):
        out = g._statements({"data_availability": "No new data.",
                             "conflicts": "None."})
        self.assertIn("Data and Code Availability", out)
        self.assertIn("Conflicts of Interest", out)
        self.assertEqual(g._statements({}), "")

    def test_cite_box_formats(self):
        box = g._cite_box(self._M, {"title": "J"}, "https://e.example/x/", "2026")
        for label in ("IEEE", "APA", "BibTeX", "RIS"):
            self.assertIn(">%s<" % label, box)
        self.assertIn("TY  - JOUR", box)

    def test_article_number_in_cites(self):
        m = dict(self._M)
        m["article_number"] = "CSR-2026-001"
        self.assertIn("Art. no. CSR-2026-001",
                      g._ieee_cite(m, {"title": "J"}, "2026"))
        self.assertIn("Article CSR-2026-001", g._apa(m, {"title": "J"}, "2026"))
        self.assertIn("M1  - CSR-2026-001",
                      g._ris(m, {"title": "J"}, "https://e.example/x/"))

    def test_bad_article_number_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            os.makedirs(ad)
            with open(os.path.join(ad, "meta.toml"), "w") as fh:
                fh.write('volume=1\nissue=1\ndate="2026-10-24"\n'
                         'authors=[{name="A"}]\narticle_number="CSR 2026 001"\n')
            with open(os.path.join(ad, "paper.md"), "w") as fh:
                fh.write("# T\n\n## Abstract\n\nLong enough abstract here now.\n\n"
                         "## 1. X\n\nBody.\n")
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_bad_orcid_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            os.makedirs(ad)
            with open(os.path.join(ad, "meta.toml"), "w") as fh:
                fh.write('volume=1\nissue=1\ndate="2026-10-24"\n'
                         'authors=[{name="A", orcid="bad"}]\n')
            with open(os.path.join(ad, "paper.md"), "w") as fh:
                fh.write("# T\n\n## Abstract\n\nLong enough abstract here now.\n\n"
                         "## 1. X\n\nBody.\n")
            with self.assertRaises(g.BuildError):
                g.load_article(ad)


class TestBrowseNav(unittest.TestCase):
    def _art(self, slug, vol, iss, kws, author):
        return {"slug": slug, "volume": vol, "issue": iss, "title": slug.upper(),
                "keywords": kws, "authors": [{"name": author}],
                "abstract": "An abstract."}

    def test_order_key(self):
        a = self._art("b", 1, 2, [], "X")
        b = self._art("a", 1, 1, [], "Y")
        self.assertEqual([m["slug"] for m in sorted([a, b], key=g._order_key)],
                         ["a", "b"])

    def test_article_nav_both(self):
        prev = self._art("a", 1, 1, [], "X")
        nxt = self._art("c", 1, 3, [], "Z")
        out = g._article_nav((prev, nxt), "../../../")
        self.assertIn('rel="prev" href="../../../v1/i1/a/"', out)
        self.assertIn('rel="next" href="../../../v1/i3/c/"', out)

    def test_article_nav_alone(self):
        self.assertEqual(g._article_nav(None, "../../../"), "")
        self.assertEqual(g._article_nav((None, None), "../../../"), "")

    def test_browse_groups(self):
        arts = [self._art("a", 1, 1, ["crypto", "mobile"], "Jane Doe"),
                self._art("b", 1, 2, ["mobile"], "Rick Roe")]
        page = g.render_browse(arts, dict(JOURNAL))
        self.assertIn("By keyword", page)
        self.assertIn("By author", page)
        self.assertIn("<strong>mobile</strong>", page)
        self.assertIn('href="../v1/i1/a/"', page)


class TestHeaderNavRoot(unittest.TestCase):
    def test_site_root_host_root(self):
        self.assertEqual(g._site_root({"base_url": "https://e.example"}), "/")

    def test_site_root_subpath(self):
        self.assertEqual(g._site_root({"base_url": "https://e.example/j"}), "/j/")

    def test_header_uses_absolute_root(self):
        from jmaker import templates
        out = templates.site_header("J", "/")
        self.assertIn('<nav><a href="/index.html">Home</a></nav>', out)
        # absolute => identical on every page => check_nav sees a consistent nav


class TestFooterNav(unittest.TestCase):
    def test_footer_nav_relative_and_absolute(self):
        from jmaker import templates
        j = {"title": "J", "issn": "",
             "footer_links": [{"title": "About", "href": "about/"},
                              {"title": "Src", "href": "https://e.example/x"}]}
        out = templates.site_footer(j, "../../../")
        self.assertIn('href="../../../about/">About', out)   # relative prefixed
        self.assertIn('href="https://e.example/x">Src', out)  # absolute as-is
        self.assertIn("footer-nav", out)

    def test_footer_no_links(self):
        from jmaker import templates
        out = templates.site_footer({"title": "J", "issn": "",
                                     "footer_links": []}, "")
        self.assertNotIn("footer-nav", out)

    def _journal(self, d, body):
        jt = os.path.join(d, "journal.toml")
        with open(jt, "w", encoding="utf-8") as fh:
            fh.write('title="J"\nbase_url="https://e.example"\n' + body)
        return jt

    def test_leading_slash_footer_link_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            jt = self._journal(d, 'footer_links=[{title="X", href="/abs"}]\n')
            with self.assertRaises(g.BuildError):
                g.load_journal(jt)

    def test_traversal_footer_link_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            jt = self._journal(d, 'footer_links=[{title="X", href="../up/"}]\n')
            with self.assertRaises(g.BuildError):
                g.load_journal(jt)

    def test_valid_footer_links(self):
        with tempfile.TemporaryDirectory() as d:
            jt = self._journal(d,
                               'footer_links=[{title="Home", href="index.html"}]\n')
            self.assertEqual(len(g.load_journal(jt)["footer_links"]), 1)


class TestNoVendorRefs(unittest.TestCase):
    def _run(self, text, allow=()):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".github"))
            with open(os.path.join(d, ".github", "vendor-allowlist.json"),
                      "w", encoding="utf-8") as fh:
                json.dump({"": list(allow)}, fh)   # root-dir file allowlist
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(text)
            f = c.Findings()
            c.check_no_vendor_refs(d, f)
            return [m for _l, _p, m in f.errors]

    def test_per_file_isolation(self):
        # a phrase allow-listed for dir a/ does NOT license it in dir b/
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".github"))
            os.makedirs(os.path.join(d, "a"))
            os.makedirs(os.path.join(d, "b"))
            with open(os.path.join(d, ".github", "vendor-allowlist.json"),
                      "w", encoding="utf-8") as fh:
                json.dump({"a": ["Whonix security guide"]}, fh)
            for sub in ("a", "b"):
                with open(os.path.join(d, sub, "index.html"), "w",
                          encoding="utf-8") as fh:
                    fh.write("<p>the Whonix security guide</p>")
            f = c.Findings()
            c.check_no_vendor_refs(d, f)
            errs = [p for _l, p, _m in f.errors]
            self.assertTrue(any(p.endswith(os.path.join("b", "index.html"))
                                for p in errs))
            self.assertFalse(any(p.endswith(os.path.join("a", "index.html"))
                                 for p in errs))

    def test_github_dir_not_scanned(self):
        # the manifest itself holds vendor phrases; .github must be skipped
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".github"))
            with open(os.path.join(d, ".github", "vendor-allowlist.json"),
                      "w", encoding="utf-8") as fh:
                json.dump({"x": ["Kicksecure and Whonix"]}, fh)
            f = c.Findings()
            c.check_no_vendor_refs(d, f)
            self.assertEqual([m for _l, _p, m in f.errors], [])

    def test_whonix_mention_flagged(self):
        self.assertTrue(self._run("<p>built on Whonix</p>"))

    def test_kicksecure_mention_flagged(self):
        self.assertTrue(self._run("<p>see Kicksecure</p>"))

    def test_allowlisted_phrase_passes(self):
        self.assertEqual(
            self._run('<p>cites the Whonix security guide [3]</p>',
                      allow=["Whonix security guide"]), [])

    def test_standalone_still_flagged_despite_allowlist(self):
        # an allow-listed phrase does not pardon a separate bare mention
        self.assertTrue(self._run("<p>Whonix security guide. Also Whonix.</p>",
                                  allow=["Whonix security guide"]))

    def test_clean_passes(self):
        self.assertEqual(self._run("<p>neutral android content</p>"), [])


class TestNoInternalRefs(unittest.TestCase):
    def _run(self, text):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(text)
            f = c.Findings()
            c.check_no_internal_refs(d, f)
            return [m for _l, _p, m in f.errors]

    def test_forbidden_link_flagged(self):
        errs = self._run('<a href="https://github.com/org-ai-assisted/x">x</a>')
        self.assertTrue(any("org-ai-assisted" in m for m in errs))

    def test_forbidden_mention_case_insensitive(self):
        self.assertTrue(self._run("<p>built by Org-AI-Assisted</p>"))

    def test_clean_output_passes(self):
        self.assertEqual(self._run("<p>vendor-neutral content</p>"), [])


if __name__ == "__main__":
    unittest.main()
