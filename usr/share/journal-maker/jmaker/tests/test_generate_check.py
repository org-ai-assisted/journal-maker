#!/usr/bin/python3 -Bsu
import json
import os
import re
import subprocess
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
        self.assertEqual(g._rel_dir(META), "x")
        self.assertEqual(g._root_rel("x"), "../")

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
        # A self-published preview is a technical report, not a journal article.
        self.assertIn('name="citation_technical_report_institution" content="CSR"',
                      meta)
        self.assertNotIn("citation_journal_title", meta)
        self.assertNotIn("citation_issn", meta)
        # empty doi / absent report number must be omitted, not emitted blank
        self.assertNotIn("citation_doi", meta)
        self.assertNotIn("citation_technical_report_number", meta)

    def test_citation_meta_report_number(self):
        m = dict(META)
        m["article_number"] = "CSR-2026-001"
        meta = g.citation_meta(m, JOURNAL, "https://e.example/x/",
                               "https://e.example/x/x.pdf")
        self.assertIn('name="citation_technical_report_number" '
                      'content="CSR-2026-001"', meta)


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
        # A web preview, not a journal article.
        self.assertIn("@misc{", bt)
        self.assertNotIn("@article{", bt)
        self.assertNotIn("journal =", bt)
        self.assertIn("howpublished = {Computer Security Research}", bt)
        self.assertIn("url = {https://h/v1/i1/x/}", bt)
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
        # Technical report, not a journal article: no journal_* fields.
        self.assertEqual(out["publication_type"], "report")
        self.assertEqual(out["description"], "An abstract.")
        self.assertEqual(out["license"], "cc-by-4.0")
        self.assertNotIn("journal_title", out)
        self.assertNotIn("journal_issn", out)
        self.assertNotIn("journal_pages", out)
        # publisher survives as the report's imprint (else Zenodo defaults it).
        self.assertEqual(out["imprint_publisher"], "CSR")
        self.assertEqual(len(out["creators"]), 2)
        self.assertEqual(out["creators"][0]["affiliation"], "U")

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
                stderr = ""   # mirror subprocess.CompletedProcess
            return R()
        orig = g._run
        setattr(g, "_run", fake_run)
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
                zenodo.reserve(d, "site.toml", zenodo.SANDBOX, "tok")
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
            with open(pdf, "wb") as pf:
                pf.write(b"%PDF-1.4 dummy")
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
        setattr(zenodo, "_api", rec)
        setattr(zenodo, "_pdf_text",
                lambda p: "title ... DOI: 10.5281/zenodo.123 ... body")
        self.addCleanup(lambda: setattr(zenodo, "_api", orig_api))
        self.addCleanup(lambda: setattr(zenodo, "_pdf_text", orig_txt))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".zenodo.json"), "w", encoding="utf-8") as fh:
                json.dump({"deposition_id": 1, "doi": "10.5281/zenodo.123",
                           "bucket": "https://sandbox.zenodo.org/api/files/x",
                           "base": zenodo.SANDBOX}, fh)
            pdf = os.path.join(d, "a.pdf")
            with open(pdf, "wb") as pf:
                pf.write(b"%PDF-1.4 dummy")
            self.assertEqual(zenodo.publish(d, pdf, zenodo.SANDBOX, "tok"), 0)
        self.assertEqual(len(calls), 2)

    def test_publish_rejects_prefix_doi(self):
        # A PDF whose only DOI-like token is a SUPERSTRING of the reserved DOI
        # (10.5281/zenodo.123 vs ...1234) must not be accepted.
        from jmaker import zenodo

        def boom(*a, **k):
            raise RuntimeError("_api must not be called when refusing")
        orig_api, orig_txt = zenodo._api, zenodo._pdf_text
        zenodo._api = boom
        zenodo._pdf_text = lambda p: "DOI: 10.5281/zenodo.1234\n"
        self.addCleanup(lambda: setattr(zenodo, "_api", orig_api))
        self.addCleanup(lambda: setattr(zenodo, "_pdf_text", orig_txt))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".zenodo.json"), "w", encoding="utf-8") as fh:
                json.dump({"deposition_id": 1, "doi": "10.5281/zenodo.123",
                           "bucket": "https://sandbox.zenodo.org/api/files/x",
                           "base": zenodo.SANDBOX}, fh)
            pdf = os.path.join(d, "a.pdf")
            with open(pdf, "wb") as pf:
                pf.write(b"%PDF-1.4 dummy")
            with self.assertRaises(zenodo.ZenodoError):
                zenodo.publish(d, pdf, zenodo.SANDBOX, "tok")

    def test_pdf_text_timeout_is_zenodo_error(self):
        # A hung pdftotext raises TimeoutExpired (not an OSError); it must surface
        # as a ZenodoError, not an uncaught traceback.
        from jmaker import zenodo

        def timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="pdftotext", timeout=120)
        orig = subprocess.run
        subprocess.run = timeout
        self.addCleanup(lambda: setattr(subprocess, "run", orig))
        with self.assertRaises(zenodo.ZenodoError):
            zenodo._pdf_text("/nonexistent.pdf")

    def test_pdf_text_nonzero_exit_fails_closed(self):
        # A nonzero pdftotext exit must raise, not return partial text that could
        # pass the DOI guard before an irreversible publish.
        from jmaker import zenodo

        class R:
            returncode = 1
            stdout = "DOI: 10.5281/zenodo.123"
            stderr = "Syntax Error: broken xref"
        orig = subprocess.run
        setattr(subprocess, "run", lambda *a, **k: R())
        self.addCleanup(lambda: setattr(subprocess, "run", orig))
        with self.assertRaises(zenodo.ZenodoError):
            zenodo._pdf_text("/some.pdf")


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
            jt = os.path.join(d, "site.toml")
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

    def test_numeric_slug_coerced_to_str(self):
        # A bare `slug = 123` passes the string-form regex but, left an int,
        # reaches _rel_dir -> _root_rel (.count) and crashes rendering with
        # AttributeError. load_article must coerce it to str.
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, 'slug = 123\ndate = "2026-10-24"\n'
                              'authors = [{name = "A"}]\n')
            m = g.load_article(ad)
            self.assertIsInstance(m["slug"], str)
            self.assertEqual(m["slug"], "123")
            # the crash site must tolerate the coerced slug
            self.assertEqual(g._root_rel(g._rel_dir(m)), "../")

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

    def test_ccs_concepts_string_rejected(self):
        # A bare string is a truthy iterable: _ccs_line would walk it character
        # by character and ship garbage. Reject non-list ccs_concepts at load.
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, 'date = "2026-10-24"\nauthors = [{name = "A"}]\n'
                              'ccs_concepts = "Security and privacy"\n')
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_ccs_concepts_scalar_rejected(self):
        # A non-iterable scalar would raise an uncaught TypeError mid-build.
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            self._article(ad, 'date = "2026-10-24"\nauthors = [{name = "A"}]\n'
                              'ccs_concepts = 2026\n')
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_out_overlapping_articles_refused(self):
        with tempfile.TemporaryDirectory() as d:
            jt = os.path.join(d, "site.toml")
            with open(jt, "w", encoding="utf-8") as fh:
                fh.write('title = "J"\nbase_url = "https://e.example"\n')
            arts = os.path.join(d, "articles")
            os.makedirs(arts)
            with self.assertRaises(g.BuildError):
                g.build(arts, jt, arts)  # out == articles dir

    def test_base_url_requires_authority(self):
        with tempfile.TemporaryDirectory() as d:
            jt = os.path.join(d, "site.toml")
            with open(jt, "w", encoding="utf-8") as fh:
                fh.write('title = "J"\nbase_url = "https:///"\n')
            with self.assertRaises(g.BuildError):
                g.load_journal(jt)

    def _write_site_toml(self, body):
        d = tempfile.mkdtemp()
        jt = os.path.join(d, "site.toml")
        with open(jt, "w", encoding="utf-8") as fh:
            fh.write(body)
        return jt

    def test_unusable_publisher_falls_back_to_title(self):
        # Absent/blank/whitespace/non-string publisher must fall back to the
        # required title, never leave the Scholar institution / RIS PB / Zenodo
        # imprint blank or non-string. Canary: fails on the old truthiness-only
        # handling for the whitespace and unquoted-date (TOML date) cases.
        base = 'title = "J"\nbase_url = "https://e.example"\n'
        for extra in ('publisher = ""\n', 'publisher = "   "\n',
                      "publisher = 2026-10-29\n", ""):
            j = g.load_journal(self._write_site_toml(base + extra))
            self.assertEqual(j["publisher"], "J", extra)

    def test_source_base_url_validated(self):
        base = 'title = "J"\nbase_url = "https://e.example"\n'
        # absent -> ""
        self.assertEqual(g.load_journal(self._write_site_toml(base))
                         ["source_base_url"], "")
        # valid kept, trailing slash stripped
        self.assertEqual(
            g.load_journal(self._write_site_toml(
                base + 'source_base_url = "https://github.com/o/r/blob/master/"\n'))
            ["source_base_url"], "https://github.com/o/r/blob/master")
        # non-absolute rejected
        with self.assertRaises(g.BuildError):
            g.load_journal(self._write_site_toml(
                base + 'source_base_url = "not a url"\n'))

    def test_nonstring_required_key_rejected(self):
        # An unquoted title parses as a TOML date (non-string); reject early with
        # a clear error, not a later TypeError in a string/JSON context.
        jt = self._write_site_toml(
            'title = 2026-10-29\nbase_url = "https://e.example"\n')
        with self.assertRaises(g.BuildError):
            g.load_journal(jt)

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
            jt = os.path.join(d, "site.toml")
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

    # citeproc DOM: in-text <a href="#ref-KEY">, reference list
    # <div id="ref-KEY" class="csl-entry">. Keys are stable @citekeys.
    def test_clean(self):
        page = ('<span class="citation"><a href="#ref-selinux">[1]</a></span>'
                '<div id="ref-selinux" class="csl-entry">X.</div>')
        self.assertEqual(self._run(page), [])

    def test_dangling_citation(self):
        # An undefined [@key] citeproc renders as "key?" with a live #ref-key link
        # but no matching .csl-entry.
        page = ('<span class="citation"><a href="#ref-ghost">ghost?</a></span>'
                '<div id="ref-selinux" class="csl-entry">X.</div>')
        msgs = self._run(page)
        self.assertTrue(any("no reference entry" in m for m in msgs))
        self.assertTrue(any("ghost" in m for m in msgs))

    def test_uncited_reference(self):
        page = ('<span class="citation"><a href="#ref-selinux">[1]</a></span>'
                '<div id="ref-selinux" class="csl-entry">X.</div>'
                '<div id="ref-unused" class="csl-entry">Y.</div>')
        self.assertTrue(any("never cited" in m for m in self._run(page)))

    def test_duplicate_reference(self):
        page = ('<a href="#ref-selinux">[1]</a>'
                '<div id="ref-selinux" class="csl-entry">X.</div>'
                '<div id="ref-selinux" class="csl-entry">dup.</div>')
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

    def test_published_numeric_entity_todo_marker_errors(self):
        # Regression: a visible marker whose colon is a numeric entity (TODO&#58;,
        # as a browser renders "TODO:") must still block -- the scan decodes
        # numeric entities, not just the fixed named set in _unescape.
        page = self._META % "published" + "<p><strong>TODO&#58;</strong> fix</p>"
        self.assertTrue(any("TODO edit-marker" in m for m in self._lint(page)))

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
    def test_csp_meta_present(self):
        page = g.render_homepage([], dict(JOURNAL), [])
        self.assertIn("Content-Security-Policy", page)
        self.assertIn("default-src 'none'", page)
        self.assertIn("script-src 'self'", page)        # one self-hosted bundle
        self.assertIn("require-trusted-types-for 'script'", page)
        self.assertIn("trusted-types 'none'", page)
        self.assertNotIn("unsafe-inline", page)        # no inline escape hatch
        self.assertNotIn("unsafe-eval", page)          # no eval / wasm
        self.assertIn("site.js", page)                 # bundle referenced
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
        js = templates.SITE_JS
        # Trusted-Types-safe: no DOM-XSS sinks, so it runs under trusted-types 'none'.
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML",
                     "document.write", "eval(", "new Function"):
            self.assertNotIn(sink, js)
        self.assertIn("navigator.clipboard", js)        # copy
        self.assertIn('setAttribute("title"', js)        # hover preview
        self.assertIn('"lightbox"', js)                  # figure lightbox
        # hovercard nav is on TOP (nav appended before body) and keyboard-steppable
        self.assertLess(js.index("appendChild(cnav)"), js.index("appendChild(cbody)"))
        self.assertIn("ArrowLeft", js)
        self.assertIn("ArrowRight", js)
        self.assertIn('querySelector(".csl-quote")', js)  # clone the inline quote
        self.assertIn("titleSrc", js)  # native tooltip excludes the inlined quote
        # hovercard is draggable by its nav bar, single-pointer (no multi-touch hijack)
        self.assertIn("setPointerCapture", js)
        self.assertIn("activeId", js)
        self.assertIn("e.pointerId !== activeId", js)

    def test_hovercard_separator_css_escape(self):
        from jmaker import templates
        css = templates.STYLE_CSS
        # The venue separator must emit the CSS escape \00B7\20 (middot + space); a
        # single backslash in the non-raw STYLE_CSS would be a NUL/control char.
        self.assertIn(r"\00B7\20", css)
        self.assertNotIn("\x00", css)
        # separator renders only when a name precedes the venue span
        self.assertIn(".rl:not(:first-child)::before", css)

    def test_opengraph_tags(self):
        og = g._opengraph("T", "An abstract.", "https://e.example/x/",
                          {"title": "J", "language": "en",
                           "base_url": "https://e.example"}, og_type="article")
        self.assertIn('property="og:title" content="T"', og)
        self.assertIn('property="og:type" content="article"', og)
        self.assertIn('property="og:locale" content="en_US"', og)
        self.assertIn('property="og:image" content="https://e.example/assets/og.png"', og)
        self.assertIn('name="twitter:card" content="summary_large_image"', og)
        self.assertIn('name="twitter:image"', og)

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

    def test_ccs_line(self):
        # CCS concepts render under their OWN label, kept separate from subjects.
        out = g._ccs_line({"ccs_concepts": ["Security and privacy -> X"]})
        self.assertIn("CCS Concepts:", out)
        self.assertIn("Security and privacy -&gt; X", out)
        self.assertNotIn("Subjects:", out)
        self.assertEqual(g._ccs_line({}), "")

    def test_license_footer(self):
        out = g._license_footer(self._M, {"license": "CC-BY-4.0",
                                          "license_url": "https://e.example/by"})
        self.assertIn("cc-badge", out)
        self.assertIn("(c) 2026", out)
        self.assertIn("Licensed under", out)
        self.assertEqual(g._license_footer(self._M, {}), "")

    def test_license_footer_rights_statement(self):
        # A bare rights statement (no license URL) is NOT "Licensed under X";
        # it is rendered as the statement itself.
        out = g._license_footer(self._M, {"license": "All rights reserved",
                                          "license_url": ""})
        self.assertIn("All rights reserved", out)
        self.assertNotIn("Licensed under", out)

    def test_statements(self):
        out = g._statements({"data_availability": "No new data.",
                             "conflicts": "None."})
        self.assertIn("Data and Code Availability", out)
        self.assertIn("Conflicts of Interest", out)
        self.assertEqual(g._statements({}), "")

    def test_cite_box_formats(self):
        box = g._cite_box(self._M, {"title": "J", "publisher": "J"},
                          "https://e.example/x/", "2026")
        for label in ("IEEE", "APA", "BibTeX", "RIS"):
            self.assertIn(">%s<" % label, box)
        self.assertIn("TY  - ELEC", box)

    def test_cite_box_not_a_journal(self):
        # A self-published web preview must never be cited as a journal article:
        # no @article/journal= (BibTeX) and no TY JOUR/JO (RIS).
        box = g._cite_box(self._M, {"title": "CSR", "publisher": "CSR"},
                          "https://e.example/x/", "2026")
        self.assertNotIn("@article", box)
        self.assertNotIn("journal =", box)
        self.assertNotIn("TY  - JOUR", box)
        self.assertNotIn("JO  - ", box)
        self.assertIn("@misc{", box)
        self.assertIn("TY  - ELEC", box)
        self.assertIn("howpublished = {CSR}", box)
        # every format carries a retrieval URL
        self.assertEqual(box.count("https://e.example/x/"), 4)

    def test_article_number_in_cites(self):
        m = dict(self._M)
        m["article_number"] = "CSR-2026-001"
        self.assertIn("Art. no. CSR-2026-001",
                      g._ieee_cite(m, {"title": "J"}, "https://e.example/x/", "2026"))
        self.assertIn("Article CSR-2026-001",
                      g._apa(m, {"title": "J"}, "https://e.example/x/", "2026"))
        self.assertIn("M1  - CSR-2026-001",
                      g._ris(m, {"title": "J", "publisher": "J"},
                             "https://e.example/x/"))

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
        out = g._article_nav((prev, nxt), "../")
        self.assertIn('rel="prev" href="../a/"', out)
        self.assertIn('rel="next" href="../c/"', out)

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
        self.assertIn('href="../a/"', page)


class TestHeaderNavRoot(unittest.TestCase):
    def test_site_root_host_root(self):
        self.assertEqual(g._site_root({"base_url": "https://e.example"}), "/")

    def test_site_root_subpath(self):
        self.assertEqual(g._site_root({"base_url": "https://e.example/j"}), "/j/")

    def test_header_uses_absolute_root(self):
        from jmaker import templates
        out = templates.site_header("J", "/")
        self.assertIn('<nav aria-label="Site"><a href="/">Home</a></nav>', out)
        self.assertIn('<a class="brand" href="/">', out)
        # absolute + clean (no index.html) => identical on every page => consistent nav


class TestFooterNav(unittest.TestCase):
    def test_footer_nav_relative_and_absolute(self):
        from jmaker import templates
        j = {"title": "J", "issn": "",
             "footer_links": [{"title": "Home", "href": "./"},
                              {"title": "About", "href": "about/"},
                              {"title": "Src", "href": "https://e.example/x"}]}
        out = templates.site_footer(j, "/")
        # resolved against site_root (absolute), same convention as the header nav
        self.assertIn('href="/">Home', out)                   # "./" -> site root
        self.assertIn('href="/about/">About', out)            # relative prefixed
        self.assertIn('href="https://e.example/x">Src', out)  # absolute as-is
        self.assertIn("footer-nav", out)

    def test_footer_no_links(self):
        from jmaker import templates
        out = templates.site_footer({"title": "J", "issn": "",
                                     "footer_links": []}, "")
        self.assertNotIn("footer-nav", out)

    def _journal(self, d, body):
        jt = os.path.join(d, "site.toml")
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

    def test_backslash_footer_link_rejected(self):
        # A backslash can be browser-normalized into a protocol-relative "//"
        # (off-origin) once resolved against site_root -- reject at load.
        with tempfile.TemporaryDirectory() as d:
            jt = self._journal(d, r'footer_links=[{title="X", href=".\\evil"}]' + "\n")
            with self.assertRaises(g.BuildError):
                g.load_journal(jt)

    def test_whitespace_footer_link_rejected(self):
        # A leading control/whitespace byte is stripped by the browser, exposing a
        # protocol-relative "//" -- reject it rather than emit an off-origin link.
        with tempfile.TemporaryDirectory() as d:
            jt = self._journal(d, 'footer_links=[{title="X", href="\\n//evil"}]\n')
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


class TestPdfFonts(unittest.TestCase):
    HDR = ("name                 type              encoding  emb sub uni object ID\n"
           "-------------------- ----------------- --------- --- --- --- ---------\n")

    def test_type3_detected(self):
        out = self.HDR + "ABCDEF+Foo           Type 3            Custom    yes yes no   5 0\n"
        self.assertTrue(c._has_type3_font(out))

    def test_vector_fonts_pass(self):
        out = (self.HDR
               + "ABCDEF+LMRoman10     Type 1C           Custom    yes yes no   5 0\n"
               + "GHIJKL+LMMono10      Type 1            Custom    yes yes no   6 0\n")
        self.assertFalse(c._has_type3_font(out))

    def test_empty_font_list_passes(self):
        self.assertFalse(c._has_type3_font(self.HDR))


class TestIndexPolicy(unittest.TestCase):
    NOINDEX = '<meta name="robots" content="noindex">'
    DISALLOW = "User-agent: *\nDisallow: /\n"
    ALLOW = "User-agent: *\nAllow: /\n\nSitemap: https://e.example/sitemap.xml\n"
    NOINDEX_ROBOTS = ("User-agent: *\nAllow: /\nDisallow: /*.pdf$\n"
                      "Disallow: /*.tex$\nDisallow: /*.bib$\n\n"
                      "Sitemap: https://e.example/sitemap.xml\n")

    def _check(self, robots, home, extra=None):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "robots.txt"), "w", encoding="utf-8") as fh:
                fh.write(robots)
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(home)
            for rel, body in (extra or {}).items():
                p = os.path.join(d, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(body)
            f = c.Findings()
            c.check_index_policy(d, f)
            return [m for _l, _p, m in f.errors]

    def test_noindex_consistent_ok(self):
        # A no-index build = per-page noindex meta + Allow robots (crawler must
        # fetch to read the meta) + Disallow PDFs (they carry no meta).
        self.assertEqual(
            self._check(self.NOINDEX_ROBOTS, "<html>" + self.NOINDEX + "</html>"), [])

    def test_indexable_consistent_ok(self):
        self.assertEqual(self._check(self.ALLOW, "<html>clean</html>"), [])

    def test_noindex_without_pdf_disallow_errors(self):
        # A no-index build whose robots does not Disallow PDFs leaves them
        # indexable -- a PDF carries no noindex meta and Pages has no X-Robots-Tag.
        self.assertTrue(any("must Disallow" in m for m in
                            self._check(self.ALLOW, "<html>" + self.NOINDEX + "</html>")))

    def test_noindex_with_only_pdf_disallow_errors(self):
        # The LaTeX source + .bib are served non-HTML artifacts too; a no-index
        # robots that blocks only the PDF leaves them crawlable -- flagged stale.
        robots = ("User-agent: *\nAllow: /\nDisallow: /*.pdf$\n\n"
                  "Sitemap: https://e.example/sitemap.xml\n")
        errs = self._check(robots, "<html>" + self.NOINDEX + "</html>")
        self.assertTrue(any(".tex" in m and ".bib" in m for m in errs), errs)

    def test_published_with_any_disallow_errors(self):
        # A published (indexable) build must Disallow NOTHING -- not the PDF rule
        # kept for no-index, nor any other path.
        self.assertTrue(any("must not Disallow anything" in m for m in
                            self._check(self.NOINDEX_ROBOTS, "<html>clean</html>")))
        robots = ("User-agent: *\nAllow: /\nDisallow: /x/\n\n"
                  "Sitemap: https://e.example/sitemap.xml\n")
        self.assertTrue(any("must not Disallow anything" in m for m in
                            self._check(robots, "<html>clean</html>")))

    def test_published_empty_disallow_line_not_flagged(self):
        # An empty "Disallow:" line is not a rule. The gate must not false-positive
        # by letting \s* cross the newline to match the next line's token.
        robots = ("User-agent: *\nAllow: /\nDisallow:\n\n"
                  "Sitemap: https://e.example/sitemap.xml\n")
        self.assertFalse(any("must not Disallow anything" in m for m in
                             self._check(robots, "<html>clean</html>")))

    def test_published_page_with_noindex_meta_errors(self):
        # A published build must carry NO noindex meta on ANY page; an inner page
        # that still has one (homepage does not) is flagged.
        errs = self._check(self.ALLOW, "<html>clean</html>",
                           extra={"sub/index.html": "<html>" + self.NOINDEX + "</html>"})
        self.assertTrue(any("carries a noindex meta" in m for m in errs))

    def test_robots_disallow_with_noindex_errors(self):
        # Disallow is always wrong: it blocks the crawler from reading the
        # noindex meta, defeating it rather than reinforcing it.
        self.assertTrue(any("must Allow" in m for m in
                            self._check(self.DISALLOW, "<html>" + self.NOINDEX + "</html>")))

    def test_indexable_but_robots_disallow_errors(self):
        self.assertTrue(any("must Allow" in m for m in
                            self._check(self.DISALLOW, "<html>clean</html>")))

    def test_published_todo_on_standalone_page_errors(self):
        errs = self._check(self.ALLOW, "<html>clean</html>",
                           extra={"about/index.html": "<p><strong>TODO:</strong> finish</p>"})
        self.assertTrue(any("TODO edit-marker" in m for m in errs))

    def test_published_draft_article_todo_skipped(self):
        # An article page carries article_status and is governed by
        # check_release_state (a draft may keep TODO notes); the index-policy
        # scan must SKIP it, not error on the published build.
        art = ('<meta name="article_status" content="draft">'
               '<aside class="status-banner status-draft">x</aside>'
               '<p><strong>TODO:</strong> add numbers</p>')
        errs = self._check(self.ALLOW, "<html>clean</html>",
                           extra={"v1/i1/art/index.html": art})
        self.assertEqual(errs, [])

    def test_noindex_build_allows_todo(self):
        # A no-index build keeps TODO edit-markers; the inner page still carries
        # the noindex meta (a real no-index page does), so only the TODO-allowance
        # is under test here.
        errs = self._check(self.NOINDEX_ROBOTS, "<html>" + self.NOINDEX + "</html>",
                           extra={"about/index.html": "<html>" + self.NOINDEX +
                                  "<p><strong>TODO:</strong> finish</p></html>"})
        self.assertEqual(errs, [])

    def test_noindex_build_inner_page_without_noindex_errors(self):
        # robots Allows crawling, so EVERY page of a no-index build must carry the
        # noindex meta; an inner page that lost it (homepage keeps it) would be
        # crawled AND indexed. Mirror of the published-page scan.
        errs = self._check(self.NOINDEX_ROBOTS, "<html>" + self.NOINDEX + "</html>",
                           extra={"sub/index.html": "<html>clean</html>"})
        self.assertTrue(any("lacks a noindex meta" in m for m in errs))


class TestNoIndexDefault(unittest.TestCase):
    def test_write_robots_noindex_disallows_artifacts(self):
        # Exact bytes must match dist_ai.webcheck.site.render_robots (the webcheck
        # 'previews' policy re-derives and compares). Both modes Allow (HTML
        # de-indexes via the per-page meta); a no-index build ALSO Disallows the
        # non-HTML served artifacts -- PDF, LaTeX source, .bib (no meta possible,
        # no X-Robots-Tag on Pages).
        base = "User-agent: *\nAllow: /\n"
        tail = "\nSitemap: https://e.example/sitemap.xml\n"
        disallows = "Disallow: /*.pdf$\nDisallow: /*.tex$\nDisallow: /*.bib$\n"
        cases = {True: base + disallows + tail,
                 False: base + tail}
        with tempfile.TemporaryDirectory() as d:
            for noindex, expect in cases.items():
                g.write_robots({"_no_index": noindex,
                                "base_url": "https://e.example"}, d)
                with open(os.path.join(d, "robots.txt"), encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), expect)

    def test_write_sitemap_always_populated_and_sorted(self):
        # The sitemap lists every page regardless of the no-index state (no-index
        # lives in the per-page meta), SORTED to byte-match webcheck's
        # render_sitemap (sorted(seo_page_urls(...))). Feed unsorted input.
        urls = ["https://e.example/b/", "https://e.example/", "https://e.example/a/"]
        with tempfile.TemporaryDirectory() as d:
            g.write_sitemap(urls, d)
            with open(os.path.join(d, "sitemap.xml"), encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(),
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                    '  <url><loc>https://e.example/</loc></url>\n'
                    '  <url><loc>https://e.example/a/</loc></url>\n'
                    '  <url><loc>https://e.example/b/</loc></url>\n'
                    '</urlset>\n')

    def test_default_build_non_indexable_publish_opts_in(self):
        with tempfile.TemporaryDirectory() as d:
            jt = os.path.join(d, "site.toml")
            with open(jt, "w", encoding="utf-8") as fh:
                fh.write('title = "J"\nbase_url = "https://e.example"\n'
                         'publisher = "P"\nissn = ""\nlicense = "CC-BY-4.0"\n'
                         'license_url = "https://e.example/by/4.0/"\nlanguage = "en"\n'
                         'footer_links = [{ title = "Home", href = "index.html" }]\n')
            ad = os.path.join(d, "articles", "art")
            os.makedirs(ad)
            with open(os.path.join(ad, "meta.toml"), "w", encoding="utf-8") as fh:
                fh.write('authors = [{ name = "A" }]\ndate = "2026-10-24"\n'
                         'volume = 1\nissue = 1\n')
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation purposes here.\n\n## 1. Intro\n\nBody.\n")
            arts = os.path.join(d, "articles")
            out1 = os.path.join(d, "s1")
            g.build(arts, jt, out1, skip_pdf=True)                 # default (no-index)
            out2 = os.path.join(d, "s2")
            g.build(arts, jt, out2, skip_pdf=True, publish=True)   # opt in (publish)
            # Both Allow + advertise the sitemap. Differences: the default
            # (no-index) build carries the per-page noindex meta AND Disallows
            # PDFs (no meta possible); the published build does neither.
            for out in (out1, out2):
                with open(os.path.join(out, "robots.txt"), encoding="utf-8") as fh:
                    r = fh.read()
                self.assertIn("Allow: /", r)
                self.assertIn("Sitemap:", r)
                self.assertNotIn("Disallow: /\n", r)  # never a blanket disallow
            with open(os.path.join(out1, "robots.txt"), encoding="utf-8") as fh:
                self.assertIn("Disallow: /*.pdf$", fh.read())
            with open(os.path.join(out2, "robots.txt"), encoding="utf-8") as fh:
                self.assertNotIn("Disallow:", fh.read())
            with open(os.path.join(out1, "index.html"), encoding="utf-8") as fh:
                self.assertIn('name="robots" content="noindex"', fh.read())
            with open(os.path.join(out2, "index.html"), encoding="utf-8") as fh:
                self.assertNotIn('name="robots" content="noindex"', fh.read())


class TestCheckSiteDiscovery(unittest.TestCase):
    def _site(self, d, article_slug="art", pages=None):
        jt = os.path.join(d, "site.toml")
        with open(jt, "w", encoding="utf-8") as fh:
            fh.write('title = "J"\nbase_url = "https://e.example"\n'
                     'publisher = "P"\nlicense = "All rights reserved"\n'
                     'license_url = ""\nlanguage = "en"\n'
                     'footer_links = [{ title = "Home", href = "./" }]\n')
        ad = os.path.join(d, "articles", article_slug)
        os.makedirs(ad)
        with open(os.path.join(ad, "meta.toml"), "w", encoding="utf-8") as fh:
            fh.write('authors = [{ name = "A" }]\ndate = "2026-10-24"\n')
        with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
            fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                     "validation purposes here.\n\n## 1. Intro\n\nBody.\n")
        for slug in (pages or []):
            pdir = os.path.join(d, "pages")
            os.makedirs(pdir, exist_ok=True)
            with open(os.path.join(pdir, slug + ".md"), "w",
                      encoding="utf-8") as fh:
                fh.write("# %s\n\nBody.\n" % slug)
        return jt

    def test_a11y_unique_nav_landmarks_and_cite_distinction(self):
        # axe landmark-unique: the header, TOC, and footer <nav> landmarks each
        # carry a UNIQUE aria-label (two unnamed navs would collide). axe
        # link-in-text-block: inline citation links are distinguished from body
        # text without relying on color (a dotted underline), per WCAG 1.4.1.
        import glob
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            # >=3 body H2 sections so a TOC nav is emitted (_build_toc threshold);
            # the landmark-unique collision only arises with header + TOC navs.
            with open(os.path.join(d, "articles", "art", "paper.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation purposes here.\n\n## 1. Intro\n\nBody.\n\n"
                         "## 2. More\n\nMore.\n\n## 3. End\n\nEnd.\n")
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn('<nav aria-label="Site">', page)
            self.assertIn('<nav class="toc" aria-label="Contents">', page)
            self.assertIn('aria-label="Footer"', page)
            css = ""
            for p in glob.glob(os.path.join(out, "assets", "*.css")):
                with open(p, encoding="utf-8") as fh:
                    css += fh.read()
            self.assertIn(".citation a { text-decoration: underline dotted", css)

    def test_pdf_only_adds_pdfs_without_rebuilding(self):
        # Deploy path: --pdf-only renders PDFs into an already-built tree without
        # wiping it (no rmtree) and without touching the committed HTML.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            arts = os.path.join(d, "articles")
            out = os.path.join(d, "s")
            g.build(arts, jt, out, skip_pdf=True)   # committed text tree, no PDF
            html = os.path.join(out, "art", "index.html")
            with open(html, encoding="utf-8") as fh:
                before = fh.read()
            self.assertFalse(os.path.exists(os.path.join(out, "art", "art.pdf")))
            orig = g.md_to_pdf
            g.md_to_pdf = lambda m, j, p: open(p, "wb").write(b"%PDF-1.5 stub\n")
            self.addCleanup(lambda: setattr(g, "md_to_pdf", orig))
            g.build(arts, jt, out, pdf_only=True)
            self.assertTrue(os.path.exists(os.path.join(out, "art", "art.pdf")))
            self.assertTrue(os.path.exists(os.path.join(out, "art", "art.pdf.sha256")))
            with open(html, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), before)   # HTML untouched (no rebuild)

    def test_pdf_only_refuses_missing_tree(self):
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with self.assertRaises(g.BuildError) as cm:
                g.build(os.path.join(d, "articles"), jt,
                        os.path.join(d, "nope"), pdf_only=True)
            self.assertIn("existing built tree", str(cm.exception))

    def test_symlinked_source_tex_is_not_overwritten(self):
        # Security: a committed symlink named <slug>.tex in the article SOURCE
        # dir must NOT have its target truncated -- the .tex is written into
        # _site (build output), never the source dir. (Fails on the pre-fix code,
        # which wrote <slug>.tex into m["_dir"] and followed the symlink.)
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)                       # article slug "art"
            sentinel = os.path.join(d, "sentinel.txt")
            with open(sentinel, "w", encoding="utf-8") as fh:
                fh.write("DO-NOT-OVERWRITE\n")
            os.symlink(sentinel, os.path.join(d, "articles", "art", "art.tex"))
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(sentinel, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "DO-NOT-OVERWRITE\n")   # untouched
            site_tex = os.path.join(out, "art", "art.tex")
            self.assertTrue(os.path.isfile(site_tex))
            self.assertFalse(os.path.islink(site_tex))

    def test_latex_link_points_to_committed_tex_on_source_host(self):
        # With source_base_url set, the LaTeX-source link targets the committed
        # .tex in the published _site tree on the source host (not the relative
        # served copy).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with open(jt, "a", encoding="utf-8") as fh:
                fh.write('source_base_url = "https://example.com/r/blob/master"\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn(
                '<a class="sources-aid" '
                'href="https://example.com/r/blob/master/_site/art/art.tex">'
                "LaTeX source</a>", page)

    def test_inline_styles_stripped_and_favicon_linked(self):
        # Strict CSP style-src 'self' blocks inline styles (pandoc emits them on
        # aligned/sized table cells); the page must carry none. Every page links a
        # favicon so the browser never probes /favicon.ico (a strict-CSP console
        # error) -- the asset ships too.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with open(os.path.join(d, "articles", "art", "paper.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation purposes here.\n\n## 1. Intro\n\n"
                         "| a | b |\n|:-:|:-:|\n| 1 | 2 |\n")
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            self.assertNotIn("style=", page)
            self.assertIn('rel="icon"', page)
            self.assertTrue(
                os.path.isfile(os.path.join(out, "assets", "favicon.svg")))

    def test_sanitize_strips_style_outside_code_keeps_inside(self):
        # A table col's inline style is stripped; a displayed HTML sample inside a
        # code span keeps its literal style="..." (pandoc entity-escapes quotes in
        # code, but the skip is explicit).
        self.assertNotIn("style=", g._sanitize_html('<col style="width: 50%">'))
        self.assertIn('style="x"', g._sanitize_html('<pre>a style="x" b</pre>'))

    def test_sanitize_is_tag_scoped_not_prose_eating(self):
        # The attribute strip must act only inside REAL tags, never on the literal
        # sequence in running prose -- a security journal quotes these constantly,
        # and a blind text regex silently deletes reader-visible text (the #33
        # content-loss regression). Pandoc escapes '<'/'>' in text content, so a
        # quoted-attribute phrase in a <p> body is plain text.
        for prose in (
                '<p>The payload sets style="width:0;height:0" to hide it.</p>',
                "<p>Use the style='color:red' attribute, or onclick=\"f()\".</p>",
                '<p>A link href="javascript:void(0)" in the sample.</p>'):
            self.assertEqual(g._sanitize_html(prose), prose,
                             "prose must survive verbatim: %r" % prose)
        # A real tag still has its style / event / dangerous-URL attribute stripped,
        # even when its quoted value contains a '>'.
        self.assertEqual(g._sanitize_html('<td style="a>b">x</td>'), '<td>x</td>')
        self.assertNotIn("onclick", g._sanitize_html('<a onclick="e()">x</a>'))
        neutralized = g._sanitize_html('<a href="javascript:evil()">x</a>')
        self.assertNotIn("javascript:", neutralized)
        self.assertIn('href="#', neutralized)

    def test_named_footnotes_number_by_appearance_not_definition(self):
        # Authors key footnotes by stable name ([^name]), never by number: pandoc
        # numbers them by inline-reference order, so inserting one mid-text
        # renumbers automatically with no manual edit. Guards the whole fragment
        # pipeline (md_to_html_fragment -> _sanitize_html -> _endash_html): a
        # future sanitizer tightening must not strip the footnote anchors or
        # disturb the ordering.
        base = ("A.[^alpha] B.[^beta] C.[^gamma]\n\n"
                "[^gamma]: third defined first.\n"
                "[^alpha]: first.\n"
                "[^beta]: second.\n")
        html = g.md_to_html_fragment(base)
        # Definition order is scrambled; markers still number 1,2,3 by the order
        # the references appear in the prose, and the anchors survive sanitizing.
        self.assertEqual(re.findall(r"<sup>(\d+)</sup>", html), ["1", "2", "3"])
        self.assertIn("footnote-ref", html)
        for text in ("first.", "second.", "third defined first."):
            self.assertIn(text, html)
        # Inserting a named footnote mid-text renumbers to 1..4 with no edit to
        # the others -- the churn the stable-name scheme exists to avoid.
        inserted = ("A.[^alpha] NEW.[^delta] B.[^beta] C.[^gamma]\n\n"
                    "[^gamma]: g.\n[^alpha]: a.\n[^beta]: b.\n[^delta]: d.\n")
        self.assertEqual(
            re.findall(r"<sup>(\d+)</sup>", g.md_to_html_fragment(inserted)),
            ["1", "2", "3", "4"])

    def test_citeproc_full_build_numbers_and_checks_clean(self):
        # End-to-end: a paper citing [@key] from refs.bib builds, the built page
        # numbers in-text cites by first appearance, and the citation-parity gate
        # passes on the citeproc DOM.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation purposes here.\n\n## 1. Intro\n\n"
                         "First [@beta]. Second [@alpha]. Reuse [@beta].\n\n"
                         "## 2. References\n\n::: {#refs}\n:::\n")
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"),
                      encoding="utf-8") as fh:
                page = fh.read()
            self.assertEqual(
                re.findall(r'role="doc-biblioref">\[(\d+)\]', page),
                ["1", "2", "1"])
            self.assertIn('<div id="ref-beta" class="csl-entry"', page)
            f = c.Findings()
            c.check_citation_parity(page, "p", f)
            self.assertEqual([m for _l, _p, m in f.errors], [])

    def test_abstract_citation_rejected(self):
        # A [@key] in the abstract cannot render (no citeproc there; it is the
        # plain-text meta/OG description) -- the build must fail, not ship literal.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA long enough abstract that cites "
                         "prior work [@alpha] right here.\n\n## 1. Intro\n\n"
                         "Body [@beta].\n\n## 2. References\n\n::: {#refs}\n:::\n")
            out = os.path.join(d, "s")
            with self.assertRaises(g.BuildError) as cm:
                g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            self.assertIn("abstract", str(cm.exception))

    def test_linkless_reference_fails_build(self):
        # A refs.bib entry with neither url nor doi fails the build loud (house
        # style: every cited source must be independently checkable). Guards the
        # build-path wiring, not only the pure checker.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write("@article{nolinkref, author={A}, title={{T}}, "
                         "journal={{J}}, year={2004}}\n")
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation purposes here.\n\n## 1. Intro\n\n"
                         "Body [@nolinkref].\n\n## 2. References\n\n"
                         "::: {#refs}\n:::\n")
            out = os.path.join(d, "s")
            with self.assertRaises(g.BuildError) as cm:
                g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            self.assertIn("source link", str(cm.exception))
            self.assertIn("nolinkref", str(cm.exception))

    def test_body_citation_requires_bib(self):
        # A [@key] in the body with no refs.bib is a build error (no silent
        # literal "[@key]" shipping).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with open(os.path.join(d, "articles", "art", "paper.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation purposes here.\n\n## 1. Intro\n\n"
                         "A cite [@nobib] with no bibliography.\n")
            out = os.path.join(d, "s")
            with self.assertRaises(g.BuildError):
                g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)

    def test_sitemap_excludes_pdfs_in_full_build(self):
        # The sitemap lists HTML navigable pages only -- byte-identical to
        # dist_ai.webcheck.site.seo_page_urls, which the 'previews' policy
        # re-derives and byte-compares. A full build still SERVES the PDF (+ its
        # .sha256); it is simply not advertised in the sitemap, so a no-index
        # build's robots Disallow: /*.pdf$ never contradicts the sitemap.
        def _stub_pdf(_m, _journal, pdf_path):
            with open(pdf_path, "wb") as fh:
                fh.write(b"%PDF-1.4 stub\n")

        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            orig = g.md_to_pdf
            g.md_to_pdf = _stub_pdf
            try:
                out = os.path.join(d, "s")
                g.build(os.path.join(d, "articles"), jt, out, skip_pdf=False)
            finally:
                g.md_to_pdf = orig
            with open(os.path.join(out, "sitemap.xml"), encoding="utf-8") as fh:
                sitemap = fh.read()
            self.assertNotIn(".pdf", sitemap)
            pdfs = [os.path.join(b, n) for b, _dirs, files in os.walk(out)
                    for n in files if n.endswith(".pdf")]
            self.assertTrue(pdfs, "a full build still generates the PDF")
            self.assertTrue(os.path.isfile(pdfs[0] + ".sha256"))

    def test_og_and_jsonld_on_all_page_types(self):
        # Every page type carries OpenGraph + Twitter + og:locale + a JSON-LD
        # block of the right schema.org @type (not article-only).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d, pages=["about"])
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            want = {"index.html": "WebSite", "about/index.html": "WebPage",
                    "browse/index.html": "CollectionPage",
                    "art/index.html": "ScholarlyArticle"}
            for rel, ld_type in want.items():
                with open(os.path.join(out, rel), encoding="utf-8") as fh:
                    page = fh.read()
                self.assertIn('property="og:title"', page, rel)
                self.assertIn('property="og:locale"', page, rel)
                self.assertIn('name="twitter:card"', page, rel)
                self.assertIn('"@type": "%s"' % ld_type, page, rel)

    def test_pwa_icons_manifest_and_csp(self):
        # Icon set + og card rasterized, manifest emitted + linked, CSP allows it
        # (manifest-src 'self'), and every head carries the icon/PWA tags.
        import json as _json
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            a = os.path.join(out, "assets")
            for name in ("favicon.svg", "favicon.png", "icon-192.png",
                         "icon-maskable.png", "og.png", "manifest.webmanifest"):
                self.assertTrue(os.path.isfile(os.path.join(a, name)), name)
            with open(os.path.join(a, "manifest.webmanifest"), encoding="utf-8") as fh:
                man = _json.load(fh)
            self.assertEqual(man["display"], "standalone")
            self.assertTrue(any(i.get("purpose") == "maskable"
                                for i in man["icons"]))
            with open(os.path.join(out, "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            for frag in ('rel="manifest"', 'rel="apple-touch-icon"',
                         'rel="mask-icon"', 'name="theme-color"',
                         'property="og:image"', "manifest-src 'self'"):
                self.assertIn(frag, page, frag)
            # start_url/scope track base_url's path: host-root -> "/", a
            # subpath/project-page deploy -> "/repo/" (not the origin root).
            self.assertEqual(man["start_url"], "/")
            with tempfile.TemporaryDirectory() as sd:
                os.makedirs(os.path.join(sd, "assets"))
                g.write_icons(sd, {"title": "S", "publisher": "P",
                                   "base_url": "https://ex.github.io/repo"})
                with open(os.path.join(sd, "assets", "manifest.webmanifest"),
                          encoding="utf-8") as fh:
                    sub = _json.load(fh)
                self.assertEqual(sub["start_url"], "/repo/")
                self.assertEqual(sub["scope"], "/repo/")

    def test_discovers_flat_article(self):
        # Article landing pages live at a FLAT <slug>/index.html (no v<N>/i<M>);
        # check_site must discover them from the build manifest, not by path.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            self.assertTrue(os.path.isfile(os.path.join(out, "art", "index.html")))
            self.assertTrue(os.path.isfile(
                os.path.join(out, ".github", "articles.json")))
            _f, found = c.check_site(out)
            self.assertEqual(found, 1)

    def test_skip_pdf_omits_pdf_download_anchors(self):
        # build() gates PDF + sha256 generation on skip_pdf, so a --skip-pdf tree
        # has neither file; the page must then carry NO <a> link to them, or a
        # link-checker scanning the skip-pdf tree reports two dangling internal
        # links (regression: the family-wide website-tests gate failed on exactly
        # android-insecurity.pdf + .sha256). The citation_pdf_url meta (absolute,
        # canonical) is a separate concern and stays.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            self.assertNotIn('href="art.pdf"', page)
            self.assertNotIn('href="art.pdf.sha256"', page)
            self.assertNotIn(">Download PDF</a>", page)
            # render_article is the single source: a FULL build still offers both.
            journal = g.load_journal(jt)
            m = g.load_article(os.path.join(d, "articles", "art"))
            _rel, _name, full = g.render_article(m, journal, skip_pdf=False)
            self.assertIn('href="art.pdf"', full)
            self.assertIn('href="art.pdf.sha256"', full)
            self.assertIn(">Download PDF</a>", full)

    def test_discovery_independent_of_status_marker(self):
        # An article page that LOST its article_status meta must still be
        # discovered (via the manifest) and reported, never silently skipped --
        # discovery cannot depend on the marker check_article validates.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            page = os.path.join(out, "art", "index.html")
            with open(page, encoding="utf-8") as fh:
                html_text = fh.read()
            html_text = re.sub(r'<meta name="article_status"[^>]*>', "", html_text)
            with open(page, "w", encoding="utf-8") as fh:
                fh.write(html_text)
            f, found = c.check_site(out)
            self.assertEqual(found, 1)  # still discovered, not skipped
            self.assertTrue(any("article_status" in m for _l, _p, m in f.items))

    def test_noindex_build_sitemap_is_populated(self):
        # A no-index build (default) still ships a POPULATED sitemap listing its
        # real pages (no-index is a per-page meta concern), so check_site finds no
        # "lists no URLs" error and the sitemap carries a <loc>.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            f, _ = c.check_site(out)
            self.assertFalse(any("lists no URLs" in m for _l, _p, m in f.items))
            with open(os.path.join(out, "sitemap.xml"), encoding="utf-8") as fh:
                self.assertIn("<loc>", fh.read())

    def test_rejects_article_slug_colliding_with_page(self):
        # Flat namespace: an article slug that equals a standalone page slug
        # would overwrite it -- the build must refuse.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d, article_slug="about", pages=["about"])
            out = os.path.join(d, "s")
            with self.assertRaises(g.BuildError):
                g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)

    _TOML = ('[alpha]\nlabel = "Alpha source"\n'
             'claims = [{ section = "Sec. 3", text = "the alpha claim" }]\n'
             'quotes = [{ text = "the alpha verbatim text" }]\n'
             '[gamma]\nno_quote = "paywalled; no free full text."\n')

    def test_source_quotes_cards_published_and_linked(self):
        # A per-article source-quotes.toml is published as quotation cards at
        # <slug>/sources/, linked from the article, carrying the no-index meta.
        # Attribution comes from refs.bib (via pandoc CSL-JSON). check_site stays
        # clean (the sidecar is a non-article page, exempt from citation parity).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nBody [@alpha] and "
                         "[@gamma].\n\n## 2. References\n\n::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write(self._TOML)
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            spage = os.path.join(out, "art", "sources", "index.html")
            self.assertTrue(os.path.isfile(spage))
            with open(spage, encoding="utf-8") as fh:
                sources = fh.read()
            self.assertIn('<article class="qcard" id="alpha">', sources)
            self.assertIn("the alpha verbatim text", sources)
            self.assertIn('<a class="qkey" href="#alpha">[@alpha]</a>', sources)
            self.assertIn('href="../#cite-alpha" aria-label="Sec. 3 in the paper, '
                          'reference alpha">Sec. 3', sources)   # claim pill
            # attribution from refs.bib (CSL-JSON): author "Org A", linked title
            self.assertIn('<span class="nm">Org A</span>', sources)
            self.assertIn('href="https://a.example/x" aria-label="Alpha page, '
                          'Org A">Alpha page</a>', sources)
            self.assertIn("retrieved 2026-01-01", sources)
            # gamma has no quote -> Remaining references, not a card
            self.assertIn("Remaining references", sources)
            self.assertIn("paywalled", sources)
            # contents nav: links each card + the Remaining section to its anchor
            self.assertIn('<nav class="sources-toc"', sources)
            self.assertIn('<a href="#alpha">[@alpha]</a>', sources)
            self.assertIn('href="#sources-remaining">Remaining references (1)', sources)
            self.assertIn('id="sources-remaining"', sources)
            self.assertIn('name="robots" content="noindex"', sources)
            self.assertIn('href="../"', sources)            # back to the paper
            with open(os.path.join(out, "art", "index.html"),
                      encoding="utf-8") as fh:
                self.assertIn('href="sources/"', fh.read())  # article links it
            # in the sitemap like every navigable page (byte-parity with webcheck)
            with open(os.path.join(out, "sitemap.xml"), encoding="utf-8") as fh:
                self.assertIn("<loc>https://e.example/art/sources/</loc>",
                              fh.read())
            f, found = c.check_site(out)
            self.assertEqual(found, 1)
            self.assertFalse(any("sources" in p for _l, p, _m in f.errors),
                             [i for i in f.errors])

    def test_sidecar_neutralizes_dangerous_url(self):
        # A dangerous scheme in a refs.bib url must be neutralized on the sources
        # page (the hand-assembled card HTML runs through _sanitize_html).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write('@misc{alpha, author={{Org}}, title={{T}}, '
                         'url={javascript:alert(1)}}\n')
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[alpha]\nquotes = [{ text = "q" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "sources", "index.html"),
                      encoding="utf-8") as fh:
                sources = fh.read()
            # _sanitize_html rewrites the dangerous scheme to '#', so no live
            # javascript: href survives.
            self.assertNotIn("javascript:", sources)
            self.assertIn('class="src"><a href="#', sources)

    def test_reference_backlinks_and_source_links(self):
        # #6: the first in-text citation gets id=cite-KEY and the reference [n]
        # backlinks to it. #5: a reference whose key has a sidecar card links to
        # its sources/#KEY quote; one without does not. Parity stays clean.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nBody [@beta] then "
                         "[@alpha], reuse [@beta].\n\n## 2. References\n\n"
                         "::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[beta]\nquotes = [{ text = "b" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"),
                      encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn('<a id="cite-beta" href="#ref-beta"', page)   # #6 target
            self.assertEqual(page.count('id="cite-beta"'), 1)           # first only
            self.assertIn('<a class="csl-backref" href="#cite-beta"', page)
            self.assertIn('<a class="csl-source" href="sources/#beta"', page)  # #5
            # axe identical-links-same-purpose: the repeated "[n]" backref and
            # "full card" text get a unique per-reference aria-label.
            self.assertRegex(page, r'<a class="csl-backref" href="#cite-beta" '
                                   r'aria-label="Reference \d+, back to text">')
            self.assertRegex(page, r'<a class="csl-source" href="sources/#beta" '
                                   r'aria-label="full card for reference \d+">')
            self.assertNotIn('href="sources/#alpha"', page)   # alpha has no card
            # stable [@key] backlink (#21) on every cited key + the quote inlined
            # in beta's reference entry (#22); alpha (no card) has neither quote nor link
            self.assertIn('<a class="csl-citekey" href="#cite-beta">[@beta]</a>', page)
            self.assertIn('<a class="csl-citekey" href="#cite-alpha">[@alpha]</a>', page)
            self.assertIn('<div class="csl-quote">', page)
            self.assertIn('>full card</a>', page)
            f = c.Findings()
            c.check_citation_parity(page, "p", f)
            self.assertEqual([m for _l, _p, m in f.errors], [])

    @staticmethod
    def _link_collisions(page):
        """Links sharing an accessible name but pointing at different hrefs --
        exactly what axe-core identical-links-same-purpose (WCAG 2.4.9 AAA) flags.
        Accessible name = aria-label if present, else the whitespace-normalized
        visible text (entities decoded); the generator emits no nested <a>."""
        import re as _re
        import html as _h
        seen: dict = {}
        bad: list = []
        for mo in _re.finditer(r'<a\b([^>]*)>(.*?)</a>', page, _re.S):
            attrs, inner = mo.group(1), mo.group(2)
            hm = _re.search(r'href="([^"]*)"', attrs)
            if not hm:
                continue
            href = _h.unescape(hm.group(1))
            am = _re.search(r'aria-label="([^"]*)"', attrs)
            name = (am.group(1) if am
                    else _re.sub(r'<[^>]+>', '', inner))
            name = " ".join(_h.unescape(name).split())
            if not name:
                continue
            if name in seen and seen[name] != href:
                bad.append((name, seen[name], href))
            else:
                seen.setdefault(name, href)
        return bad

    @staticmethod
    def _label_in_name_bad(page):
        """Links whose aria-label does NOT contain their visible text -- axe-core
        label-content-name-mismatch (WCAG 2.5.3, level A, on by default). Normalize
        like axe: lowercase, non-alphanumeric runs -> single space, collapse; then
        the visible text must be a CONTIGUOUS substring of the accessible name."""
        import re as _re
        import html as _h

        def norm(s):
            return " ".join(_re.sub(r'[^0-9a-z]+', ' ', _h.unescape(s).lower()).split())

        bad: list = []
        for mo in _re.finditer(r'<a\b([^>]*)>(.*?)</a>', page, _re.S):
            attrs, inner = mo.group(1), mo.group(2)
            am = _re.search(r'aria-label="([^"]*)"', attrs)
            if not am:
                continue
            vis = norm(_re.sub(r'<[^>]+>', '', inner))
            if vis and vis not in norm(am.group(1)):
                bad.append((vis, am.group(1)))
        return bad

    def test_no_identical_links_same_purpose(self):
        # Regression for axe identical-links-same-purpose: the repeated-text nav
        # links the generator emits (reference "[n]" backref vs body marker, the
        # "full card" source links, the sources-page "Sec. N ->" pills, and the
        # attribution title link for two refs sharing a title) must each carry a
        # distinct accessible name. RED on pre-aria-label code.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(
                    "@misc{alpha, title={{Alpha page}}, author={{Org A}}, "
                    "url={https://a.example/x}, urldate={2026-01-01}}\n"
                    "@misc{beta, title={{Beta page}}, author={{Org B}}, "
                    "url={https://b.example/y}, urldate={2026-01-01}}\n"
                    # two entries deliberately sharing the title "microG"
                    "@misc{calyx-mg, title={{microG}}, author={{CalyxOS}}, "
                    "url={https://calyxos.example/microg}, urldate={2026-01-01}}\n"
                    "@misc{eos-mg, title={{microG}}, author={{e Foundation}}, "
                    "url={https://e.example/microg}, urldate={2026-01-01}}\n")
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nBody [@beta], "
                         "[@calyx-mg], [@eos-mg], and [@alpha].\n\n"
                         "## 2. References\n\n::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                # beta and calyx-mg both claim the SAME section -> same "Sec. 3 ->"
                # pill text, different #cite targets.
                fh.write('[beta]\nclaims = [{ section = "Sec. 3", text = "b" }]\n'
                         'quotes = [{ text = "bq" }]\n'
                         '[calyx-mg]\nclaims = [{ section = "Sec. 3", text = "c" }]\n'
                         'quotes = [{ text = "cq" }]\n'
                         '[eos-mg]\nquotes = [{ text = "eq" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            for rel in ("art/index.html", "art/sources/index.html"):
                with open(os.path.join(out, rel), encoding="utf-8") as fh:
                    page = fh.read()
                bad = self._link_collisions(page)
                self.assertEqual(bad, [], "%s: identical-links-same-purpose %r"
                                 % (rel, bad))
                # the aria-labels added for 2.4.9 must still satisfy 2.5.3
                lin = self._label_in_name_bad(page)
                self.assertEqual(lin, [], "%s: label-content-name-mismatch %r"
                                 % (rel, lin))

    def test_enhance_references_decodes_nonascii_key(self):
        # A non-ASCII citekey is ASCII-entity-encoded in body_html, but the sidecar
        # dict/set are keyed by the RAW key; _enhance_references must decode for the
        # lookups so the quote is still inlined (not silently dropped).
        body = ('<article class="body"><span class="citation">'
                '<a href="#ref-m&#252;ller" role="doc-biblioref">[1]</a>'
                '</span></article>'
                '<div id="ref-m&#252;ller" class="csl-entry">'
                '<div class="csl-left-margin">[1]</div>'
                '<div class="csl-right-inline">M&#252;ller, Title.</div></div>')
        k = "m" + chr(0xfc) + "ller"   # non-ASCII citekey, ASCII source
        out = g._enhance_references(body, {k},
                                   {k: "<blockquote>Q</blockquote>"})
        self.assertIn('id="cite-m&#252;ller"', out)                 # pretty anchor
        self.assertIn('<div class="csl-quote"><blockquote>Q</blockquote></div>', out)
        self.assertIn('href="sources/#m&#252;ller"', out)
        self.assertIn('>full card</a>', out)

    def test_citation_quote_store_for_hovercards(self):
        # The verbatim quote for a cited key is INLINED in that key's reference
        # entry (.csl-quote) -- one source, shared by the reference area and the
        # hovercard (which clones it); there is NO separate hidden store. An
        # uncited card key is absent from the reference list, so its quote never
        # appears.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nBody [@beta].\n\n"
                         "## 2. References\n\n::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[beta]\nquotes = [{ text = "verbatim beta quote" }]\n'
                         '[gamma]\nquotes = [{ text = "uncited quote" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"),
                      encoding="utf-8") as fh:
                page = fh.read()
            # quote inlined in the reference entry, not a hidden store
            self.assertNotIn('class="cite-quotes"', page)
            self.assertIn('<div class="csl-quote">', page)
            self.assertIn("verbatim beta quote", page)
            self.assertIn('blockquote class="quotation"', page)
            # stable [@key] backlink + visible [n] backref in the reference entry
            self.assertIn('<a class="csl-citekey" href="#cite-beta">[@beta]</a>', page)
            self.assertIn('<a class="csl-backref" href="#cite-beta"', page)
            # gamma has a card but is not cited -> not in the reference list at all
            self.assertNotIn("uncited quote", page)

    def test_source_links_use_dir_name_and_toml(self):
        # With source_base_url set, the article links to its paper.md and the
        # sources page to its source-quotes.toml, under articles/<DIR NAME> (not
        # the slug, which meta.toml can override).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with open(jt, "a", encoding="utf-8") as fh:
                fh.write('source_base_url = "https://github.com/o/r/blob/master"\n')
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "meta.toml"), "a", encoding="utf-8") as fh:
                fh.write('slug = "different-slug"\n')   # slug != dir name
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[alpha]\nquotes = [{ text = "y" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "different-slug", "index.html"),
                      encoding="utf-8") as fh:
                art = fh.read()
            # blob path uses the on-disk dir "art", never the slug
            self.assertIn('href="https://github.com/o/r/blob/master/articles/art/'
                          'paper.md"', art)
            self.assertNotIn("different-slug/paper.md", art)
            with open(os.path.join(out, "different-slug", "sources", "index.html"),
                      encoding="utf-8") as fh:
                self.assertIn('href="https://github.com/o/r/blob/master/articles/'
                              'art/source-quotes.toml"', fh.read())

    def test_no_sidecar_no_sources_page_or_link(self):
        # No source-quotes.toml -> no sources/ page and no link on the article.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            self.assertFalse(os.path.isdir(os.path.join(out, "art", "sources")))
            with open(os.path.join(out, "art", "index.html"),
                      encoding="utf-8") as fh:
                self.assertNotIn('href="sources/"', fh.read())

    def test_sources_page_inherits_article_vendor_allowance(self):
        # The card renders the quote verbatim; a vendor phrase the article
        # allow-lists and that is quoted in the sidecar must be allowed on the
        # sources page too (its dir is a distinct per-file key).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "meta.toml"), "a", encoding="utf-8") as fh:
                fh.write('allow_vendor_mentions = ["Kicksecure wiki"]\n')
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[alpha]\nquotes = [{ text = '
                         '"see the Kicksecure wiki for details" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, ".github", "vendor-allowlist.json"),
                      encoding="utf-8") as fh:
                manifest = json.load(fh)
            self.assertIn("art/sources", manifest)
            f = c.Findings()
            c.check_no_vendor_refs(out, f)
            self.assertEqual([m for _l, p, m in f.errors], [])

    def test_section_pill_key_must_be_cited(self):
        # A sidecar claim with a `section` renders a ../#cite-KEY pill; if the key
        # is not cited in paper.md that anchor never exists, so the build fails
        # rather than emit a dead pill (the default _site paper.md cites nothing).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[alpha]\nclaims = [{ section = "Sec. 1", text = "c" }]\n'
                         'quotes = [{ text = "q" }]\n')
            with self.assertRaises(g.BuildError) as cm:
                g.build(os.path.join(d, "articles"), jt, os.path.join(d, "s"),
                        skip_pdf=True)
            self.assertIn("does not cite", str(cm.exception))

    def test_narrative_citation_satisfies_section_pill(self):
        # F1 regression: a NARRATIVE "@beta showed" (no brackets) is a real pandoc
        # citation -> #cite-beta exists, so a section pill for beta is valid. The
        # old bracket-only pre-scan wrongly failed this; the check now reads the
        # rendered body.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nAs @beta showed, it "
                         "held.\n\n## 2. References\n\n::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[beta]\nclaims = [{ section = "Sec. 1", text = "c" }]\n'
                         'quotes = [{ text = "q" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)  # no raise
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                self.assertIn('id="cite-beta"', fh.read())

    def test_nonascii_cited_key_builds(self):
        # A non-ASCII cited key: body_html entity-encodes it, so the stamped anchor
        # is cite-m&#xfc;ller; the cited-key validation must encode the key too, or
        # the build spuriously fails "does not cite". Section pill -> key must cite.
        key = "m" + chr(0xfc) + "ller"
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write("@misc{%s, author={{X}}, title={{T}}, "
                         "url={https://e.example/x}}\n" % key)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nBody [@%s].\n\n"
                         "## 2. References\n\n::: {#refs}\n:::\n" % key)
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('["%s"]\nclaims = [{ section = "S", text = "c" }]\n'
                         'quotes = [{ text = "q" }]\n' % key)
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)  # no raise
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                self.assertIn('id="cite-m&#xfc;ller"', fh.read())

    def test_indented_code_citation_does_not_satisfy_pill(self):
        # F2 regression: a [@beta] ONLY inside a 4-space indented code block is not
        # a citation to pandoc (no #cite-beta), so a section pill for beta must fail
        # -- the old _MD_CODE_RE missed indented code and wrongly passed it.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\n    sample [@beta] "
                         "here\n\nmore.\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[beta]\nclaims = [{ section = "Sec. 1", text = "c" }]\n'
                         'quotes = [{ text = "q" }]\n')
            with self.assertRaises(g.BuildError) as cm:
                g.build(os.path.join(d, "articles"), jt, os.path.join(d, "s"),
                        skip_pdf=True)
            self.assertIn("does not cite", str(cm.exception))

    def test_remaining_reference_key_must_be_cited(self):
        # A no_quote ("Remaining references") entry presents itself as a cited
        # source ("cited but no verbatim text"), so paper.md must cite it; an
        # uncited one fails the build rather than publish a false claim.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)   # default paper.md cites nothing
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[gamma]\nno_quote = "paywalled; no free full text."\n')
            with self.assertRaises(g.BuildError) as cm:
                g.build(os.path.join(d, "articles"), jt, os.path.join(d, "s"),
                        skip_pdf=True)
            self.assertIn("does not cite", str(cm.exception))

    def test_leftover_source_quotes_md_rejected(self):
        # A leftover source-quotes.md (superseded by .toml) is no longer read; fail
        # loudly rather than silently drop the sources page/link/sitemap entry.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "source-quotes.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("## [@alpha] label\n")
            with self.assertRaises(g.BuildError) as cm:
                g.build(os.path.join(d, "articles"), jt, os.path.join(d, "s"),
                        skip_pdf=True)
            self.assertIn("source-quotes.md", str(cm.exception))

    def test_sidecar_key_without_csl_entry_rejected(self):
        # A key in the raw refs.bib scan but not emitted by pandoc CSL-JSON (an
        # @comment block) would render a card with empty attribution; fail instead.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write("@comment{alpha, url={https://e.example/x}}\n"
                         "@misc{beta, author={{B}}, title={{T}}, "
                         "url={https://e.example/b}}\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[alpha]\nquotes = [{ text = "q" }]\n')
            with self.assertRaises(g.BuildError) as cm:
                g.build(os.path.join(d, "articles"), jt, os.path.join(d, "s"),
                        skip_pdf=True)
            self.assertIn("CSL-JSON", str(cm.exception))


_BIB = (
    "@misc{alpha, title={{Alpha page}}, author={{Org A}}, "
    "url={https://a.example/x}, urldate={2026-01-01}}\n"
    "@misc{beta, title={{Beta page}}, author={{Org B}}, "
    "url={https://b.example/y}, urldate={2026-01-01}}\n"
    "@article{gamma, author={R. Writer}, title={Paper}, "
    "journal={J. Testing}, volume={2}, number={3}, pages={1--28}, year={2004}, "
    "doi={10.1000/example.gamma}}\n"
    "@misc{delta, title={{DOI item}}, author={A. Author}, year={2020}, "
    "doi={10.1000/example.doi}}\n"
)


def _refsdoc(body):
    return body + "\n\n## References\n\n::: {#refs}\n:::\n"


class TestCiteprocFragment(unittest.TestCase):
    """The real pandoc --citeproc path (needs pandoc + the IEEE CSL)."""

    def _frag(self, md):
        with tempfile.TemporaryDirectory() as d:
            bib = os.path.join(d, "refs.bib")
            with open(bib, "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            return g.md_to_html_fragment(md, bib)

    def test_numbered_by_first_appearance(self):
        # beta is cited first (1), alpha next (2); a grouped cite renders both in
        # number order; a reuse repeats the number. Inserting a cite never
        # renumbers because numbers follow first appearance, not the bib order.
        html = self._frag(_refsdoc(
            "X [@beta]. Y [@alpha]. Z [@beta; @alpha]. Reuse [@beta]."))
        self.assertEqual(
            re.findall(r'role="doc-biblioref">\[(\d+)\]', html),
            ["1", "2", "1", "2", "1"])
        # bib entry order follows first citation (beta before alpha).
        self.assertLess(html.index('id="ref-beta"'), html.index('id="ref-alpha"'))

    def test_reference_url_and_doi_linkified(self):
        # citeproc (link-bibliography) linkifies the bib URL and the DOI itself --
        # the generator no longer hand-rolls this.
        html = self._frag(_refsdoc("U [@alpha]. D [@delta]."))
        self.assertIn('href="https://a.example/x"', html)
        self.assertIn('href="https://doi.org/10.1000/example.doi"', html)

    def test_output_is_ascii_entities(self):
        # The IEEE style emits an en dash in the page range and curly quotes; the
        # ASCII gate must still pass, so the fragment is byte-ASCII with the
        # typographic chars folded to numeric HTML entities.
        html = self._frag(_refsdoc("G [@gamma]."))
        self.assertTrue(all(ord(ch) < 128 for ch in html))
        self.assertIn("&#x2013;", html)   # en dash (pp. 1-28)
        self.assertIn("&#x201c;", html)   # left curly quote

    def test_nocase_marker_stripped(self):
        # {{double-braced}} bib titles make citeproc emit <span class="nocase">;
        # it is a no-op marker and must be stripped (the check_site gate rejects a
        # sole class with no CSS rule), while the title casing is preserved.
        html = self._frag(_refsdoc("A [@alpha]."))
        self.assertNotIn('class="nocase"', html)
        self.assertIn("Alpha page", html)   # casing preserved (not "alpha page")

    def test_undefined_citation_fails_loud(self):
        # citeproc EXITS 0 on an undefined [@key]; the generator promotes its
        # stderr warning to a hard failure so a dangling cite cannot ship.
        with self.assertRaises(g.BuildError) as cm:
            self._frag(_refsdoc("Bad [@no-such-key]."))
        self.assertIn("no-such-key", str(cm.exception))


class TestSidecar(unittest.TestCase):
    """Structured source-quotes.toml: load + validate (pure, no pandoc), the
    refs.bib CSL attribution logic, and the card builders."""

    def _dir(self, bib=_BIB, toml=None):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        if bib is not None:
            with open(os.path.join(d, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(bib)
        if toml is not None:
            with open(os.path.join(d, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write(toml)
        return d

    def test_no_sidecar_is_ok(self):
        self.assertIsNone(g._load_sidecar(self._dir()))

    def test_valid_sidecar_loads_in_order(self):
        d = self._dir(toml='[beta]\nquotes = [{ text = "b" }]\n'
                           '[alpha]\nquotes = [{ text = "a" }]\n')
        data = g._load_sidecar(d)
        self.assertEqual(list(data), ["beta", "alpha"])   # file order preserved
        self.assertEqual(data["alpha"]["quotes"][0]["text"], "a")

    def test_symlinked_sidecar_rejected(self):
        import shutil as _sh
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: _sh.rmtree(d))
        with open(os.path.join(d, "refs.bib"), "w", encoding="utf-8") as fh:
            fh.write(_BIB)
        secret = os.path.join(d, "secret.toml")
        with open(secret, "w", encoding="utf-8") as fh:
            fh.write('[alpha]\nquotes = [{ text = "x" }]\n')
        os.symlink(secret, os.path.join(d, "source-quotes.toml"))
        with self.assertRaises(g.BuildError) as cm:
            g._load_sidecar(d)
        self.assertIn("symlink", str(cm.exception))

    def test_toml_parse_error_rejected(self):
        d = self._dir(toml='[alpha]\nquotes = [ bad\n')
        with self.assertRaises(g.BuildError):
            g._load_sidecar(d)

    def test_empty_sidecar_rejected(self):
        # An empty source-quotes.toml ({}) with no refs.bib must fail as a clean
        # BuildError, not reach pandoc and surface a raw subprocess error.
        d = self._dir(bib=None, toml="")
        with self.assertRaises(g.BuildError) as cm:
            g._load_sidecar(d)
        self.assertIn("no entries", str(cm.exception))

    def test_key_not_in_bib_rejected(self):
        d = self._dir(toml='[ghost]\nquotes = [{ text = "x" }]\n')
        with self.assertRaises(g.BuildError) as cm:
            g._load_sidecar(d)
        self.assertIn("ghost", str(cm.exception))

    def test_entry_needs_quotes_or_no_quote(self):
        d = self._dir(toml='[alpha]\nclaims = [{ section = "Sec. 1", text = "c" }]\n')
        with self.assertRaises(g.BuildError) as cm:
            g._load_sidecar(d)
        self.assertIn("quotes or", str(cm.exception))

    def test_empty_quote_text_rejected(self):
        d = self._dir(toml='[alpha]\nquotes = [{ text = "  " }]\n')
        with self.assertRaises(g.BuildError):
            g._load_sidecar(d)

    def test_no_quote_entry_ok(self):
        d = self._dir(toml='[alpha]\nno_quote = "paywalled"\n')
        self.assertIn("alpha", g._load_sidecar(d))

    def test_bad_key_charset_rejected(self):
        # A key with HTML-unsafe chars (would break out of id/href) is refused.
        d = self._dir(toml='["a<b"]\nquotes = [{ text = "x" }]\n')
        with self.assertRaises(g.BuildError) as cm:
            g._load_sidecar(d)
        self.assertIn("[\\w:.-]+", str(cm.exception))

    def test_nonstring_fields_rejected(self):
        # Every rendered field must be a string -- else html.escape crashes with
        # an AttributeError the CLI does not catch. Validate at load as BuildError.
        for toml in ('[alpha]\nlabel = 1\nquotes = [{ text = "x" }]\n',
                     '[alpha]\nquotes = [{ text = "x", label = 2 }]\n',
                     '[alpha]\nquotes = [{ text = "x", note = 1 }]\n',
                     '[alpha]\nclaims = [{ section = 3, text = "c" }]\n'
                     'quotes = [{ text = "x" }]\n',
                     '[alpha]\nno_quote = true\n',
                     '[alpha]\nno_quote = ""\n'):
            d = self._dir(toml=toml)
            with self.assertRaises(g.BuildError):
                g._load_sidecar(d)

    # --- refs.bib CSL attribution (pure: hand-built CSL-JSON entries) ---
    def test_csl_attribution_author_venue_retrieved(self):
        att = g._csl_attribution({
            "author": [{"family": "Doe", "given": "J."}, {"literal": "Org"}],
            "title": "T", "URL": "https://e.example/p",
            "container-title": "Proc X", "issued": {"date-parts": [[2022]]},
            "accessed": {"date-parts": [[2026, 10, 31]]}})
        self.assertEqual(att["name"], "J. Doe; Org")
        self.assertEqual(att["venue"], "Proc X, 2022")
        self.assertEqual(att["link"], "https://e.example/p")
        self.assertEqual(att["retrieved"], "2026-10-31")

    def test_csl_attribution_publisher_name_and_doi_link(self):
        # no author -> name from publisher; no URL -> link from DOI; no accessed.
        att = g._csl_attribution({"title": "Patent",
                                  "publisher": "U.S. Patent US1", "DOI": "10.1/x"})
        self.assertEqual(att["name"], "U.S. Patent US1")
        self.assertEqual(att["venue"], "")       # publisher is the name, not venue
        self.assertEqual(att["link"], "https://doi.org/10.1/x")
        self.assertEqual(att["retrieved"], "")

    def test_csl_date_partial(self):
        self.assertEqual(g._csl_date([[2014, 5]]), "2014-05")
        self.assertEqual(g._csl_date([[2019]]), "2019")
        self.assertEqual(g._csl_date(None), "")

    # --- card builders (pure) ---
    _ATT = {"name": "N", "venue": "V", "title": "Ti",
            "link": "https://e.example/p", "retrieved": "2026-10-31"}

    def test_card_single_claim(self):
        entry = {"label": "Lbl", "claims": [{"section": "Sec. 3", "text": "cl"}],
                 "quotes": [{"text": "qt", "label": "abstract"}]}
        card = g._sources_card("alpha", entry, self._ATT)
        self.assertIn('<article class="qcard" id="alpha">', card)
        self.assertIn('<a class="qkey" href="#alpha">[@alpha]</a>', card)
        self.assertIn("Lbl", card)
        self.assertIn('href="../#cite-alpha" aria-label="Sec. 3 in the paper, '
                      'reference alpha">Sec. 3', card)   # claim -> paper citation
        self.assertIn('<span class="qlabel-tag">abstract</span>', card)
        self.assertIn("qt", card)
        self.assertIn('<span class="nm">N</span>', card)
        self.assertIn('href="https://e.example/p" aria-label="Ti, N, V">Ti</a>', card)
        self.assertIn("retrieved 2026-10-31", card)

    def test_card_multi_claim_list(self):
        entry = {"claims": [{"section": "Sec. 7", "text": "a"},
                            {"section": "Sec. 13", "text": "b"}],
                 "quotes": [{"text": "q"}]}
        card = g._sources_card("k", entry,
                               {"name": "", "venue": "", "title": "",
                                "link": "", "retrieved": ""})
        self.assertIn("qclaim-list", card)
        self.assertEqual(card.count('href="../#cite-k"'), 2)

    def test_card_claim_without_section_no_empty_pill(self):
        # A claim with no section emits NO pill (not an empty <a> pill).
        entry = {"claims": [{"text": "sectionless claim"}],
                 "quotes": [{"text": "q"}]}
        card = g._sources_card("k", entry,
                               {"name": "", "venue": "", "title": "",
                                "link": "", "retrieved": ""})
        self.assertNotIn("qclaim-sec", card)
        self.assertIn("sectionless claim", card)

    def test_csl_authors_keeps_particles_and_suffix(self):
        att = g._csl_attribution({"title": "T", "author": [
            {"given": "Vincent", "non-dropping-particle": "van",
             "family": "Gogh"},
            {"given": "Martin Luther", "family": "King", "suffix": "Jr."}]})
        self.assertEqual(att["name"], "Vincent van Gogh; Martin Luther King, Jr.")

    def test_bib_keys_parsed(self):
        d = self._dir()
        self.assertEqual(g._bib_keys(os.path.join(d, "refs.bib")),
                         {"alpha", "beta", "gamma", "delta"})

    def test_citekeys_in(self):
        self.assertEqual(g._citekeys_in("see [@a-b] and [@c.d; @e:f]"),
                         {"a-b", "c.d", "e:f"})
        self.assertEqual(g._citekeys_in("email a@b.com, no bracket"), set())

    def test_non_utf8_bib_no_crash(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        with open(os.path.join(d, "refs.bib"), "wb") as fh:
            fh.write(b"@article{mueller, author={M\xfcller}, title={T}, year={2020}}\n")
        self.assertEqual(g._bib_keys(os.path.join(d, "refs.bib")), {"mueller"})

    def test_unknown_entry_field_rejected(self):
        # A misspelled entry field (e.g. `cliams`) is silently dropped otherwise.
        d = self._dir(toml='[alpha]\nquotes = [{ text = "x" }]\ncliams = "y"\n')
        with self.assertRaises(g.BuildError) as cm:
            g._load_sidecar(d)
        self.assertIn("unknown field", str(cm.exception))

    def test_unknown_claim_and_quote_field_rejected(self):
        for toml in ('[alpha]\nclaims = [{ section = "S", text = "c", oops = "z" }]\n'
                     'quotes = [{ text = "x" }]\n',
                     '[alpha]\nquotes = [{ text = "x", bogus = "z" }]\n'):
            d = self._dir(toml=toml)
            with self.assertRaises(g.BuildError) as cm:
                g._load_sidecar(d)
            self.assertIn("unknown field", str(cm.exception))

    def test_no_quote_entry_with_claims_rejected(self):
        # A no_quote entry renders no card, so claims on it would be dropped.
        d = self._dir(toml='[alpha]\nno_quote = "paywalled"\n'
                           'claims = [{ section = "S", text = "c" }]\n')
        with self.assertRaises(g.BuildError) as cm:
            g._load_sidecar(d)
        self.assertIn("cannot carry claims", str(cm.exception))

    def test_csl_attribution_editor_before_publisher(self):
        # No author: credit editors (with an ed./eds. tag) before the publisher.
        one = g._csl_attribution({"title": "T", "publisher": "Pub",
                                  "editor": [{"given": "A", "family": "Ed"}]})
        self.assertEqual(one["name"], "A Ed (ed.)")
        two = g._csl_attribution({"title": "T", "publisher": "Pub", "editor": [
            {"given": "A", "family": "Ed"}, {"given": "B", "family": "Em"}]})
        self.assertEqual(two["name"], "A Ed; B Em (eds.)")

    def test_attribution_link_without_title_uses_url(self):
        # A titleless entry with a url still renders a link (url as the text).
        att = {"name": "", "venue": "", "title": "",
               "link": "https://e.example/x", "retrieved": ""}
        self.assertIn('href="https://e.example/x">https://e.example/x</a>',
                      g._attribution_html(att))
        self.assertIn('href="https://e.example/x">https://e.example/x</a>',
                      g._sources_remaining("k", {"no_quote": "r"}, att))

    def test_quote_block_splits_paragraphs(self):
        # A blank-line-separated quote becomes one <p> per paragraph; the label
        # tags only the first (separate paragraphs must not merge into one run).
        blk = g._quote_block([{"text": "para one\n\npara two", "label": "L"}],
                             {"name": "", "venue": "", "title": "",
                              "link": "", "retrieved": ""})
        self.assertEqual(blk.count("<p>"), 2)
        self.assertEqual(blk.count('<span class="qlabel-tag">L</span>'), 1)
        self.assertIn('<span class="qlabel-tag">L</span> para one</p>', blk)
        self.assertIn("<p>para two</p>", blk)

    def test_quote_note_rendered_separately(self):
        # A per-quote note is retrieval provenance -- rendered as a separate
        # <div class="qnote">, NEVER mixed into the verbatim quote <p>.
        blk = g._quote_block(
            [{"text": "the quote", "note": "retrieved via headless chromium render"}],
            {"name": "", "venue": "", "title": "", "link": "", "retrieved": ""})
        self.assertIn("<p>the quote</p>", blk)
        self.assertIn('<div class="qnote">retrieved via headless chromium render'
                      '</div>', blk)
        self.assertNotIn("render</p>", blk)   # note is not inside the quote paragraph

    def test_quote_note_field_accepted(self):
        d = self._dir(toml='[alpha]\nquotes = [{ text = "x", note = "n" }]\n')
        self.assertIn("alpha", g._load_sidecar(d))

    def test_sanitize_url_allowlist_blocks_obfuscated_scheme(self):
        # The href/src guard allow-lists schemes (http/https/mailto + relative),
        # so a control-char-obfuscated dangerous scheme (browsers strip the tab/
        # newline) is neutralized where a named-token blocklist would miss it.
        san = g._sanitize_html
        self.assertIn('href="#"', san('<a href="javascript:alert(1)">x</a>'))
        self.assertIn('href="#"', san('<a href="java\tscript:alert(1)">x</a>'))
        self.assertIn('href="#"', san('<a href="jav\nascript:alert(1)">x</a>'))
        self.assertIn('href="#"', san('<a href="data:text/html,x">x</a>'))
        # safe schemes + relative URLs are preserved unchanged
        self.assertIn('href="https://e.example/p"',
                      san('<a href="https://e.example/p">x</a>'))
        self.assertIn('href="../#cite-k"', san('<a href="../#cite-k">x</a>'))
        self.assertIn('href="mailto:a@e.example"',
                      san('<a href="mailto:a@e.example">x</a>'))

    def test_csl_date_nonnumeric_part_no_crash(self):
        # A CSL date-part may be a string; render it verbatim rather than raising
        # an uncaught ValueError (the CLI catches only BuildError).
        self.assertEqual(g._csl_date([["2020a"]]), "2020a")
        self.assertEqual(g._csl_date([[2020, "spring"]]), "2020-spring")


class TestBibLinkPresence(unittest.TestCase):
    """_entries_missing_link: every reference carries a resolvable source link
    (url or doi), else the build fails. Pure; no pandoc."""

    def _missing(self, bib):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        p = os.path.join(d, "refs.bib")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(bib)
        return g._entries_missing_link(p)

    def test_url_and_doi_both_count_as_links(self):
        self.assertEqual(self._missing(_BIB), [])

    def test_entry_with_neither_is_flagged(self):
        bib = ("@article{bare, author={A}, title={{T}}, journal={{J}}, "
               "year={2004}}\n")
        self.assertEqual(self._missing(bib), ["bare"])

    def test_urldate_is_not_mistaken_for_url(self):
        # urldate without url must still flag: url needs = right after it.
        bib = ("@misc{x, title={{T}}, author={{A}}, urldate={2026-01-01}}\n")
        self.assertEqual(self._missing(bib), ["x"])

    def test_empty_value_does_not_count(self):
        bib = ("@misc{x, title={{T}}, url={}}\n"
               "@misc{y, title={{T}}, doi={  }}\n")
        self.assertEqual(sorted(self._missing(bib)), ["x", "y"])

    def test_nolink_opt_out_with_reason(self):
        bib = ("@misc{offline, title={{Print only}}, "
               "nolink={out-of-print book, no online edition}}\n")
        self.assertEqual(self._missing(bib), [])

    def test_multiline_entry_fields(self):
        # The real refs.bib layout: one field per line.
        good = ("@inproceedings{p,\n  author = {A},\n  title = {{T}},\n"
                "  year = {2019},\n  url = {https://e.example/p},\n"
                "  urldate = {2026-10-31},\n}\n")
        bad = ("@inproceedings{q,\n  author = {A},\n  title = {{T}},\n"
               "  year = {2019},\n}\n")
        self.assertEqual(self._missing(good + bad), ["q"])

    def test_at_sign_in_field_value_does_not_split_entry(self):
        # An @ inside a value must not be read as a new entry start.
        bib = ("@misc{e, title={{Contact a@b.example}}, "
               "url={https://e.example}}\n")
        self.assertEqual(self._missing(bib), [])

    def test_link_as_first_field_counts(self):
        # The entry-split consumes the post-key comma, so a url/doi placed as
        # the FIRST field has no leading comma in the body -- it must still count
        # (else a valid url-first entry falsely fails the build).
        bib = ("@misc{x, url={https://e.example}, title={{T}}}\n"
               "@inproceedings{y,\n  doi = {10.1/z},\n  title = {{T}},\n}\n")
        self.assertEqual(self._missing(bib), [])

    def test_urldate_as_first_field_still_flags(self):
        # The start-of-body anchor must not let a first-field urldate pass as url.
        bib = ("@misc{x, urldate={2026-01-01}, title={{T}}}\n")
        self.assertEqual(self._missing(bib), ["x"])


class TestAsciiEntities(unittest.TestCase):
    def test_folds_non_ascii(self):
        self.assertEqual(g._ascii_entities_html("a" + chr(0x2013) + "b"),
                         "a&#x2013;b")
        self.assertEqual(g._ascii_entities_html(chr(0x201c) + "q" + chr(0x201d)),
                         "&#x201c;q&#x201d;")

    def test_preserves_ascii(self):
        s = '<div class="x">plain &amp; safe</div>'
        self.assertEqual(g._ascii_entities_html(s), s)


class TestTexSource(unittest.TestCase):
    """md_to_tex: natbib + refs.bib submission source, ASCII, refs-div stripped."""

    def _capture(self, body, with_bib=True):
        captured = {}

        def fake_run(argv, **kw):
            captured["argv"] = argv
            captured["kw"] = kw
            # md_to_tex post-processes the -o file; write a stub for it to edit.
            out = argv[argv.index("-o") + 1]
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("\\bibliography{refs.bib}\n")
            class R:
                stdout = ""
                stderr = ""
            return R()
        orig = g._run
        setattr(g, "_run", fake_run)
        self.addCleanup(lambda: setattr(g, "_run", orig))
        with tempfile.TemporaryDirectory() as d:
            if with_bib:
                with open(os.path.join(d, "refs.bib"), "w", encoding="utf-8") as fh:
                    fh.write("@misc{k, title={{T}}, url={https://e/}}\n")
            m = dict(META)
            m["doi"] = ""
            m["_dir"] = d
            m["_body_md"] = body
            out_tex = os.path.join(d, "x.tex")
            g.md_to_tex(m, JOURNAL, out_tex)
            with open(out_tex, encoding="utf-8") as fh:
                captured["out"] = fh.read()
        return captured

    def test_uses_natbib_numeric_from_article_dir(self):
        cap = self._capture("Body [@k].\n\n## References\n\n::: {#refs}\n:::\n")
        argv = cap["argv"]
        self.assertIn("--natbib", argv)
        self.assertIn("latex", argv)              # -t latex
        self.assertIn("--standalone", argv)
        self.assertIn("biblio-style=unsrtnat", argv)
        self.assertIn("natbiboptions=numbers", argv)
        # bare basename + cwd=article dir -> \bibliography{refs}, not an abs path
        self.assertEqual(argv[argv.index("--bibliography") + 1], "refs.bib")
        self.assertTrue(cap["kw"].get("cwd"))  # run from the article dir

    def test_strips_references_section(self):
        cap = self._capture("Body [@k].\n\n## References\n\n::: {#refs}\n:::\n")
        sent = cap["kw"]["input"]
        self.assertNotIn("## References", sent)
        self.assertNotIn("{#refs}", sent)
        self.assertIn("Body [@k].", sent)

    def test_keeps_ascii_double_hyphen_not_endash(self):
        # LaTeX renders "--" itself; the source must stay ASCII (check_ascii gate).
        cap = self._capture("A -- B [@k].\n\n## References\n\n::: {#refs}\n:::\n")
        self.assertIn("A -- B", cap["kw"]["input"])
        self.assertNotIn("\u2013", cap["kw"]["input"])

    def test_bibliography_basename_rewritten(self):
        cap = self._capture("Body [@k].\n\n## References\n\n::: {#refs}\n:::\n")
        self.assertIn("\\bibliography{refs}", cap["out"])
        self.assertNotIn("refs.bib}", cap["out"])


class TestVendorScanCoversTex(unittest.TestCase):
    def test_tex_file_is_vendor_scanned(self):
        # .tex/.bib are served text, so the vendor-neutral gate must read them.
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.tex"), "w", encoding="utf-8") as fh:
                fh.write("\\section{Intro} Whonix is named here.\n")
            f = c.Findings()
            c.check_no_vendor_refs(d, f)
            msgs = [m for _lvl, _p, m in f.errors]
            self.assertTrue(any("whonix" in m.lower() for m in msgs), msgs)


class TestReviewFixes(unittest.TestCase):
    """Regression guards for the PR #45 reviewer findings."""

    def _tex_input(self, body):
        cap = {}

        def fake_run(argv, **kw):
            cap["input"] = kw.get("input")
            out = argv[argv.index("-o") + 1]
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("\\bibliography{refs.bib}\n")

            class R:
                stdout = ""
                stderr = ""
            return R()
        orig = g._run
        setattr(g, "_run", fake_run)
        self.addCleanup(lambda: setattr(g, "_run", orig))
        with tempfile.TemporaryDirectory() as d:
            m = dict(META)
            m["doi"] = ""
            m["_dir"] = d
            m["_body_md"] = body
            g.md_to_tex(m, JOURNAL, os.path.join(d, "x.tex"))
        return cap["input"]

    def test_tex_strip_keeps_appendix_after_references(self):
        # The refs strip removes ONLY the heading + ::: {#refs} div; an appendix
        # after References is preserved (finding: strip-to-EOF dropped it).
        sent = self._tex_input(
            "Body [@k].\n\n## References\n\n::: {#refs}\n:::\n\n"
            "## Appendix\n\nKept text.\n")
        self.assertNotIn("{#refs}", sent)
        self.assertNotIn("## References", sent)
        self.assertIn("## Appendix", sent)
        self.assertIn("Kept text.", sent)

    def test_reject_symlinked_bib(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "real.bib")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("@misc{k, title={{T}}, url={https://e/}}\n")
            os.symlink(target, os.path.join(d, "refs.bib"))
            m = dict(META)
            m["_dir"] = d
            with self.assertRaises(g.BuildError) as cm:
                g._reject_symlinked_bib(m)
            self.assertIn("symlink", str(cm.exception))

    def test_check_ascii_exempts_tex_and_bib(self):
        # .tex/.bib are UTF-8 LaTeX/BibTeX source -> not ASCII-gated; HTML is.
        with tempfile.TemporaryDirectory() as d:
            for name in ("x.tex", "y.bib", "z.html"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    fh.write("Jos\u00e9 \u2014 accent\n")
            f = c.Findings()
            c.check_ascii(d, f)
            flagged = " ".join(p for _l, p, _m in f.errors)
            self.assertIn("z.html", flagged)
            self.assertNotIn("x.tex", flagged)
            self.assertNotIn("y.bib", flagged)

    def test_skip_pdf_and_pdf_only_are_mutually_exclusive(self):
        from jmaker import cli
        parser = cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["build", "--skip-pdf", "--pdf-only"])


if __name__ == "__main__":
    unittest.main()
