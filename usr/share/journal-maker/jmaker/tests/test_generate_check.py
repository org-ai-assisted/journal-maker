#!/usr/bin/python3 -Bsu
import json
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
import email.message
import urllib.error
import urllib.request

from jmaker import archive as a
from jmaker import check as c
from jmaker import cli
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

    def test_claim_section_nums(self):
        f = g._claim_section_nums
        self.assertEqual(f("Sec. 1"), [1])
        self.assertEqual(f("Sec. 8, 12"), [8, 12])
        self.assertEqual(f("Secs. 5, 7"), [5, 7])
        self.assertEqual(f("Sec. 10"), [10])
        # multiple "Sec." runs across a slash
        self.assertEqual(f("Sec. 2/Sec. 3,13"), [2, 3, 13])
        # "Table N" is not a section run
        self.assertEqual(f("Sec. 13, Table 4"), [13])
        # Oxford comma must keep the trailing number (was dropped)
        self.assertEqual(f("Secs. 1, 2, and 3"), [1, 2, 3])
        self.assertEqual(f("Secs. 5, 7 and 9"), [5, 7, 9])
        self.assertEqual(f("Secs. 1, 2 & 3"), [1, 2, 3])
        # a range is expanded to every section it spans
        self.assertEqual(f("Secs. 1 through 5"), [1, 2, 3, 4, 5])
        self.assertEqual(f("Sec. 1-3"), [1, 2, 3])
        self.assertEqual(f("Secs. 1 to 3"), [1, 2, 3])
        self.assertEqual(f("Secs. 1-3, 7"), [1, 2, 3, 7])
        # an implausibly wide range fails loud instead of OOMing the build
        with self.assertRaises(g.BuildError):
            f("Secs. 1-10000000")
        self.assertEqual(f("Secs. 1-50"), list(range(1, 51)))   # at the cap: ok
        # a word-boundary: an ordinal "4th" is not section 4
        self.assertEqual(f("Sec. 3, 4th"), [3])
        # "Sec" must be its own word, not a suffix ("mySec.")
        self.assertEqual(f("mySec. 4"), [])
        # a dotted subsection number is not integer section 3 (run breaks at 3.5)
        self.assertEqual(f("Sec. 3.5"), [])
        self.assertEqual(f(""), [])

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

    def test_pdf_doi_and_citation_links(self):
        # PDF link parity with HTML: the DOI renders as a clickable markdown link
        # (-> hyperref \href) and in-text citations link to their reference entry
        # (link-citations). RED before doi_line became a link / before link-citations.
        captured = {}

        def fake_run(argv, **kw):
            captured["argv"] = argv
            captured["input"] = kw.get("input", "")

            class R:
                stdout = ""
                stderr = ""
            return R()
        orig = g._run
        setattr(g, "_run", fake_run)
        self.addCleanup(lambda: setattr(g, "_run", orig))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write("@misc{k, title={T}}\n")
            m = dict(META)
            m["doi"] = "10.1234/foo.bar"
            m["_body_md"] = "Body [@k].\n"
            m["_dir"] = d
            g.md_to_pdf(m, JOURNAL, "/dev/null")
        self.assertIn("link-citations=true", captured["argv"])
        self.assertIn("link-bibliography=true", captured["argv"])
        self.assertIn("DOI: [10.1234/foo.bar](https://doi.org/10.1234/foo.bar)",
                      captured["input"])

    def test_doi_md_link_safe_against_injection_and_specials(self):
        # An author-supplied DOI must not break out of the markdown link or inject a
        # foreign href; a real SICI DOI (< >) must still make a single doi.org link.
        # RED before _doi_md_link percent-encoded the href + escaped the visible text.
        evil = g._doi_md_link("10.1000/x](https://evil.example/phish)")
        self.assertIn(r"10.1000/x\]", evil)   # the ] is escaped -> cannot close early
        # the ONLY link href is the percent-encoded doi.org URL (the evil url is folded
        # into the doi.org path, never a standalone markdown href):
        self.assertIn(
            "](https://doi.org/10.1000/x%5D%28https%3A//evil.example/phish%29)", evil)
        sici = g._doi_md_link("10.1002/(SICI)1097<737>")
        self.assertIn("https://doi.org/10.1002/%28SICI%291097%3C737%3E", sici)
        self.assertEqual(sici.count("https://doi.org/"), 1)

    def test_source_date_epoch_year_only_and_invalid(self):
        # load_article accepts a bare YYYY (and a regex-only YYYY-MM-DD), so the epoch
        # helper must not crash: pad a year to Jan 1, fall back on a bad day. RED
        # before the try/pad (strptime raised ValueError, crashing the full build).
        self.assertEqual(g._source_date_epoch({"date": "2026"}),
                         g._source_date_epoch({"date": "2026-01-01"}))
        self.assertEqual(g._source_date_epoch({"date": "2024-02-31"}),
                         g._source_date_epoch({"date": "2024-01-01"}))
        # Year 0000 is the one 4-digit year the regex accepts that datetime cannot
        # represent; the fallback must clamp it, not re-raise. RED before the clamp
        # (the fallback re-ran strptime on "0000-01-01" -> ValueError escaped).
        self.assertEqual(g._source_date_epoch({"date": "0000"}),
                         g._source_date_epoch({"date": "0001-01-01"}))
        self.assertEqual(g._source_date_epoch({"date": "0000-13-40"}),
                         g._source_date_epoch({"date": "0001-01-01"}))

    def test_pdf_reproducible_env(self):
        # Bit-for-bit reproducible PDF: pin pdfTeX's dates (SOURCE_DATE_EPOCH = the
        # article date in UTC, FORCE_SOURCE_DATE=1) and the trailer /ID (\pdftrailerid,
        # which SOURCE_DATE_EPOCH does NOT cover). RED before the env + \pdftrailerid.
        captured = {}

        def fake_run(argv, **kw):
            captured["env"] = kw.get("env", {})
            hdr = argv[argv.index("--include-in-header") + 1]
            with open(hdr, encoding="utf-8") as fh:
                captured["hdr"] = fh.read()

            class R:
                stdout = ""
                stderr = ""
            return R()
        orig = g._run
        setattr(g, "_run", fake_run)
        self.addCleanup(lambda: setattr(g, "_run", orig))
        m = dict(META)
        m["doi"] = ""
        m["_body_md"] = "body\n"
        m["_dir"] = "/nonexistent/my-slug"
        g.md_to_pdf(m, JOURNAL, "/dev/null")
        expected = str(g._source_date_epoch(m))
        self.assertEqual(captured["env"].get("SOURCE_DATE_EPOCH"), expected)
        self.assertEqual(captured["env"].get("FORCE_SOURCE_DATE"), "1")
        self.assertIn("\\pdftrailerid{journal-maker-my-slug}", captured["hdr"])

    def test_docx_reproducible_env(self):
        # Reproducible docx: pandoc stamps docProps created/modified + zip entry mtimes
        # from SOURCE_DATE_EPOCH (the article date, UTC). RED before md_to_docx passed
        # the env.
        captured = {}

        def fake_run(argv, **kw):
            captured["env"] = kw.get("env", {})

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
            m["_body_md"] = "body\n"
            m["_dir"] = d
            g.md_to_docx(m, JOURNAL, os.path.join(d, "x.docx"))
        expected = str(g._source_date_epoch(m))
        self.assertEqual(captured["env"].get("SOURCE_DATE_EPOCH"), expected)

    def test_docx_reader_disables_raw_attribute_and_cites(self):
        # The Word writer shares the PDF's hardened reader (fenced ```{=latex} /
        # author raw TeX stay literal, never engine passthrough) and runs citeproc
        # when a refs.bib is present, so the .docx carries a resolved reference
        # list like the HTML/PDF.
        captured = {}

        def fake_run(argv, **kw):
            captured["argv"] = argv
            class R:
                stdout = ""
                stderr = ""
            return R()
        orig = g._run
        setattr(g, "_run", fake_run)
        self.addCleanup(lambda: setattr(g, "_run", orig))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write("@misc{k, title={T}}\n")
            out_docx = os.path.join(d, "x.docx")
            m = dict(META)
            m["doi"] = ""
            m["_body_md"] = "body\n"
            m["_dir"] = d
            g.md_to_docx(m, JOURNAL, out_docx)
            argv = captured["argv"]
            fmt = argv[argv.index("-f") + 1]
            self.assertIn("-raw_attribute", fmt)
            self.assertEqual(argv[argv.index("-o") + 1], out_docx)
            self.assertIn("--citeproc", argv)
            self.assertIn("--csl", argv)

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


class TestDocxCanary(unittest.TestCase):
    def _check(self, data):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.docx")
            with open(path, "wb") as fh:
                fh.write(data)
            f = c.Findings()
            c.check_docx(path, f)
            return [m for _lvl, _p, m in f.errors]

    def _docx(self, extra=None):
        # Minimal valid OOXML zip: word/document.xml plus any extra members.
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", "<w:document/>")
            for name, body in (extra or {}).items():
                z.writestr(name, body)
        return buf.getvalue()

    def test_not_a_zip_errors(self):
        self.assertTrue(any("ZIP" in m for m in self._check(b"hello")))

    def test_prepended_junk_rejected(self):
        # Junk before the ZIP local-header magic is rejected (parallels the PDF).
        self.assertTrue(any("ZIP" in m for m in self._check(b"<x>\nPK\x03\x04")))

    def test_valid_minimal_docx_passes(self):
        self.assertEqual(self._check(self._docx()), [])

    def test_missing_document_xml_errors(self):
        # A zip with no word/document.xml is not a Word document.
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("other.xml", "x")
        self.assertTrue(any("word/document.xml" in m
                            for m in self._check(buf.getvalue())))

    def test_vba_macro_rejected(self):
        data = self._docx({"word/vbaProject.bin": "MZ"})
        self.assertTrue(any("active content" in m for m in self._check(data)))

    def test_ole_embedding_rejected(self):
        data = self._docx({"word/embeddings/oleObject1.bin": "x"})
        self.assertTrue(any("active content" in m for m in self._check(data)))

    def test_encrypted_entry_is_clean_failure_not_crash(self):
        # An encrypted entry makes zipfile raise RuntimeError on read/testzip; it
        # must be caught as a gate failure, never propagate and crash check_site.
        # writestr clobbers a manual flag_bits, so set the encrypted GP-flag bit
        # (0x01) directly in every central-directory header (offset +8) of the
        # built zip -- zipfile reads flag_bits from there, so open() then raises
        # "File is encrypted".
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", "<w:document/>")
        raw = bytearray(buf.getvalue())
        i = 0
        while True:
            j = raw.find(b"PK\x01\x02", i)
            if j < 0:
                break
            raw[j + 8] |= 0x01
            i = j + 4
        errs = self._check(bytes(raw))  # must not raise
        self.assertTrue(any("unencrypted zip" in m for m in errs), repr(errs))

    def test_zip_bomb_rejected_before_decompress(self):
        # A highly compressible payload: tiny compressed (under MAX_DOCX_BYTES) but
        # a huge uncompressed total. The gate must refuse on the decompressed
        # bound BEFORE testzip expands it.
        import io
        import zipfile
        bomb = b"\0" * (c.MAX_DOCX_UNCOMPRESSED_BYTES + 1024)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", "<w:document/>")
            z.writestr("big.bin", bomb)
        errs = self._check(buf.getvalue())
        self.assertTrue(any("zip bomb" in m for m in errs), repr(errs))


class TestDocxFrontmatter(unittest.TestCase):
    def test_partial_affiliation_is_numbered(self):
        # One author WITH an institution + one WITHOUT: the institution must be
        # numbered and marked on ITS author only, never printed unnumbered (which
        # reads as shared by both). Canary: the pre-fix multi=len(institutions)>1
        # left this single institution unnumbered.
        m = {"authors": [{"name": "Jane Doe", "institution": "Example U"},
                         {"name": "Rick Roe"}]}
        names, legend, _corr = g._docx_frontmatter(m)
        self.assertEqual(names, ["Jane Doe^1^", "Rick Roe"])
        self.assertEqual(legend, ["^1^Example U"])

    def test_single_shared_institution_unnumbered(self):
        # All authors share ONE institution -> no marker needed.
        m = {"authors": [{"name": "Jane Doe", "institution": "Example U"},
                         {"name": "Rick Roe", "institution": "Example U"}]}
        names, legend, _corr = g._docx_frontmatter(m)
        self.assertEqual(names, ["Jane Doe", "Rick Roe"])
        self.assertEqual(legend, ["Example U"])

    def test_markdown_specials_escaped(self):
        # Name/institution/email markdown specials become literal text; the
        # affiliation superscript marker stays live (added after escaping).
        m = {"authors": [{"name": "A*Lab", "institution": "Dept [X] <Y>",
                          "email": "a_b@e.org"},
                         {"name": "Plain"}]}
        names, legend, corr = g._docx_frontmatter(m)
        self.assertEqual(names[0], r"A\*Lab^1^")
        self.assertEqual(names[1], "Plain")
        self.assertEqual(legend[0], r"^1^Dept \[X\] \<Y\>")
        self.assertIn(r"a\_b@e.org", corr)


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

    def test_footnote_hovercard_shares_nav_and_drag(self):
        from jmaker import templates
        js = templates.SITE_JS
        # Citation + footnote cards share ONE builder (no duplicated nav/drag block):
        # defined once, called twice.
        self.assertEqual(js.count("function makeHovercard("), 1)
        self.assertEqual(js.count("makeHovercard({"), 2)
        # Footnote card now has prev/next (RED before: the footnote IIFE had no nav).
        self.assertIn('"Previous footnote"', js)
        self.assertIn('"Next footnote"', js)
        self.assertIn('"Previous reference"', js)
        self.assertIn('"Next reference"', js)
        # Footnote card stays a DECORATIVE preview: aria-hidden, and its nav buttons are
        # kept out of tab order (tabindex=-1) so an aria-hidden card is never an a11y
        # trap; its body links keep href stripped.
        self.assertIn("decorative: true", js)
        self.assertIn('card.setAttribute("aria-hidden"', js)
        self.assertIn("cprev.tabIndex = -1; cnext.tabIndex = -1;", js)
        self.assertIn('removeAttribute("href")', js)
        # Citation card is the keyboard-reachable dialog (decorative: false).
        self.assertIn("decorative: false", js)
        self.assertIn('card.setAttribute("role", "dialog")', js)

    def test_hovercard_keyboard_and_drag_edge_cases(self):
        from jmaker import templates
        js = templates.SITE_JS
        # Arrow stepping is scoped to focus (on a marker or inside the card), not a bare
        # `pinned` or a shared token, so one keypress never advances a second card and a
        # pinned-but-unfocused card never hijacks arrows from another focused control.
        self.assertIn("card.contains(ae) || anchors.indexOf(ae) >= 0", js)
        self.assertNotIn("pinned || card.contains(ae)", js)
        self.assertNotIn("activeHovercard", js)
        # End buttons use aria-disabled, NOT the disabled property: a disabled button
        # that holds focus makes the browser drop focus to <body>, stalling keyboard
        # arrow stepping at an end. aria-disabled keeps the button focusable (step()
        # no-ops out of range), so stepping survives reaching an end.
        self.assertIn('setAttribute("aria-disabled", "true")', js)
        self.assertNotIn("cprev.disabled", js)
        self.assertNotIn("cnext.disabled", js)
        # Stepping while a body link held focus (e.g. a reference DOI/URL) removes it on
        # populate; focus is kept in the card (moved to the direction's nav button) so
        # arrow stepping does not stall.
        self.assertIn("hadFocusInside", js)
        # Footnote clones drop copy buttons addCopy injected into a note's <pre> (dead
        # duplicate + focusable control inside the aria-hidden card), like .footnote-back.
        self.assertIn(".footnote-back, .copy-btn", js)
        # Modified arrows (selection / history / word jump) are left to the browser.
        self.assertIn("e.altKey || e.ctrlKey || e.metaKey || e.shiftKey", js)
        # A single-target card keeps its nav bar as a drag grip (only the step controls
        # hide); the whole nav is never hidden, so a lone card stays draggable.
        self.assertIn("cprev.hidden = single", js)
        self.assertNotIn("cnav.hidden", js)
        # A decorative card's nav buttons never take focus (focus must not land inside
        # an aria-hidden subtree, and a disabled focused button would drop focus to body).
        self.assertIn('cprev.addEventListener("mousedown"', js)
        self.assertIn('cnext.addEventListener("mousedown"', js)

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

    def test_normalized_authors_dedup_and_indices(self):
        # Shared venue-frontmatter model: institutions de-duplicate in first-seen
        # order; each author carries 1-based indices into that list (and [] when
        # unaffiliated). The venue .tex + docx emitters all consume this.
        m = {"authors": [
            {"name": "A", "institution": "U1", "email": "a@x"},
            {"name": "B", "institution": "U2"},
            {"name": "C", "institution": "U1"},
            {"name": "D"},
        ]}
        authors, institutions = g.normalized_authors(m)
        self.assertEqual(institutions, ["U1", "U2"])
        self.assertEqual([a["affil_indices"] for a in authors],
                         [[1], [2], [1], []])
        self.assertEqual(authors[0]["email"], "a@x")
        self.assertIsNone(authors[1]["email"])
        self.assertEqual(authors[3]["institution"], None)

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
        out = g._statements({"data_availability": "No new data."})
        self.assertIn("Data and Code Availability", out)
        # Funding and COI are separate submission fields, never in the preview.
        self.assertNotIn("Funding", out)
        self.assertNotIn("Conflicts of Interest", out)
        self.assertEqual(g._statements({"funding": "x"}), "")
        self.assertEqual(g._statements({"conflicts": "x"}), "")
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

    def test_bad_institution_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            os.makedirs(ad)
            with open(os.path.join(ad, "meta.toml"), "w") as fh:
                fh.write('date="2026-10-24"\n'
                         'authors=[{name="A", institution=""}]\n')
            with open(os.path.join(ad, "paper.md"), "w") as fh:
                fh.write("# T\n\n## Abstract\n\nLong enough abstract here now.\n\n"
                         "## 1. X\n\nBody.\n")
            with self.assertRaises(g.BuildError):
                g.load_article(ad)

    def test_bad_email_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ad = os.path.join(d, "art")
            os.makedirs(ad)
            with open(os.path.join(ad, "meta.toml"), "w") as fh:
                fh.write('date="2026-10-24"\n'
                         'authors=[{name="A", email=5}]\n')
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

    def test_dangerous_scheme_footer_link_rejected(self):
        # javascript:/data:/vbscript: have no "://" and would slip a ://-keyed
        # check; the footer is emitted without the body URL sanitizer, so a bad
        # scheme would be live (stored XSS). Must be rejected at load.
        for bad in ("javascript:alert(1)", "data:text/html,<script>x</script>",
                    "vbscript:msgbox"):
            with tempfile.TemporaryDirectory() as d:
                jt = self._journal(d,
                                   'footer_links=[{title="X", href="%s"}]\n' % bad)
                with self.assertRaises(g.BuildError):
                    g.load_journal(jt)

    def test_mailto_and_tel_footer_links_allowed(self):
        # The safe absolute schemes a site legitimately uses for a contact link.
        with tempfile.TemporaryDirectory() as d:
            jt = self._journal(d,
                               'footer_links=[{title="M", href="mailto:x@e.example"},'
                               '{title="T", href="tel:+10000000000"}]\n')
            self.assertEqual(len(g.load_journal(jt)["footer_links"]), 2)

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
                      "Disallow: /*.tex$\nDisallow: /*.bib$\n"
                      "Disallow: /*.docx$\n\n"
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
        # Both modes Allow (HTML de-indexes via the per-page meta); a no-index
        # build ALSO Disallows the non-HTML served artifacts -- PDF, LaTeX
        # source, .bib, and the Word .docx (no meta possible, no X-Robots-Tag on
        # Pages). Byte-identical to dist_ai.webcheck.site.render_robots under the
        # CSR policy (its per-policy artifact-ext set adds docx last); the docx
        # line stays off the family/wiki default there.
        base = "User-agent: *\nAllow: /\n"
        tail = "\nSitemap: https://e.example/sitemap.xml\n"
        disallows = ("Disallow: /*.pdf$\nDisallow: /*.tex$\n"
                     "Disallow: /*.bib$\nDisallow: /*.docx$\n")
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
            # Both binary FORMATS (PDF + Word) are absent from the committed text
            # tree and rendered only by the deploy pass.
            self.assertFalse(os.path.exists(os.path.join(out, "art", "art.pdf")))
            self.assertFalse(os.path.exists(os.path.join(out, "art", "art.docx")))
            orig, orig_docx = g.md_to_pdf, g.md_to_docx
            # Both emitters resolve via globals() in Fmt.emit, so a module-attr
            # monkeypatch takes effect; stub them so no pandoc/pdflatex is needed.
            g.md_to_pdf = lambda m, j, p: open(p, "wb").write(b"%PDF-1.5 stub\n")
            g.md_to_docx = lambda m, j, p: open(p, "wb").write(b"PK\x03\x04stub")
            self.addCleanup(lambda: setattr(g, "md_to_pdf", orig))
            self.addCleanup(lambda: setattr(g, "md_to_docx", orig_docx))
            g.build(arts, jt, out, pdf_only=True)
            for ext in ("pdf", "docx"):
                self.assertTrue(os.path.exists(
                    os.path.join(out, "art", "art.%s" % ext)))
                self.assertTrue(os.path.exists(
                    os.path.join(out, "art", "art.%s.sha512" % ext)))
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
        # With source_base_url set, each LaTeX menu item targets the committed
        # .tex in the published _site tree on the source host (not the relative
        # served copy). The variants live inside the single <details> pop-over.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with open(jt, "a", encoding="utf-8") as fh:
                fh.write('source_base_url = "https://example.com/r/blob/master"\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn(
                '<a href="https://example.com/r/blob/master/_site/art/art.tex">'
                'Neutral (natbib) <span class="ext">.tex</span></a>', page)
            self.assertIn(
                '<a href="https://example.com/r/blob/master/_site/'
                'art/art-elsarticle.tex">'
                'Elsevier <span class="ext">-elsarticle.tex</span></a>', page)

    def test_latex_sources_fold_into_one_no_js_details_menu(self):
        # The five LaTeX variants collapse into ONE <details> pop-over (no JS),
        # not five flat links. The old flat top-level links must be gone, and the
        # actions container must be a <div> (a <details> would implicitly close a
        # <p>, splitting the row).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            journal = g.load_journal(jt)
            m = g.load_article(os.path.join(d, "articles", "art"))
            _rel, _name, full = g.render_article(m, journal, skip_pdf=False)
            self.assertEqual(full.count('<details class="latex-dl">'), 1)
            self.assertEqual(full.count('class="latex-menu"'), 1)
            # One summary trigger labelled "LaTeX"; every variant inside the menu.
            self.assertIn("<summary>LaTeX", full)
            for label in ("Neutral (natbib)", "Elsevier", "IEEE", "ACM", "Springer"):
                self.assertIn('<span class="ext">', full)
                self.assertIn(label + " <span", full)
            # The pre-menu flat links are gone.
            self.assertNotIn(">LaTeX source</a>", full)
            self.assertNotIn(">LaTeX (Elsevier)</a>", full)
            self.assertNotIn('<p class="actions">', full)
            self.assertIn('<div class="actions">', full)

    def test_checksum_is_glyph_link_with_sha512_label(self):
        # The integrity link is an icon-only lock glyph (ASCII HTML entity so the
        # HTML stays ASCII-gated), carrying the SHA-512 sidecar and a distinct
        # per-format accessible name. No visible "SHA-256"/"SHA-512" text, no
        # legacy .sha256 href.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            journal = g.load_journal(jt)
            m = g.load_article(os.path.join(d, "articles", "art"))
            _rel, _name, full = g.render_article(m, journal, skip_pdf=False)
            self.assertIn(
                '<a class="checksum" href="art.pdf.sha512" '
                'title="SHA-512 checksum" '
                'aria-label="SHA-512 checksum for PDF">&#x1F510;</a>', full)
            self.assertIn('aria-label="SHA-512 checksum for Word"', full)
            self.assertNotIn(".sha256", full)
            self.assertNotIn(">SHA-256<", full)
            self.assertNotIn(">SHA-512<", full)

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
        # .sha512); it is simply not advertised in the sitemap, so a no-index
        # build's robots Disallow: /*.pdf$ never contradicts the sitemap.
        def _stub_pdf(_m, _journal, pdf_path):
            with open(pdf_path, "wb") as fh:
                fh.write(b"%PDF-1.4 stub\n")

        def _stub_docx(_m, _journal, docx_path):
            with open(docx_path, "wb") as fh:
                fh.write(b"PK\x03\x04stub")

        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            orig, orig_docx = g.md_to_pdf, g.md_to_docx
            g.md_to_pdf = _stub_pdf
            g.md_to_docx = _stub_docx
            try:
                out = os.path.join(d, "s")
                g.build(os.path.join(d, "articles"), jt, out, skip_pdf=False)
            finally:
                g.md_to_pdf = orig
                g.md_to_docx = orig_docx
            with open(os.path.join(out, "sitemap.xml"), encoding="utf-8") as fh:
                sitemap = fh.read()
            # Neither binary artifact is advertised in the sitemap.
            self.assertNotIn(".pdf", sitemap)
            self.assertNotIn(".docx", sitemap)
            for ext in ("pdf", "docx"):
                arts = [os.path.join(b, n) for b, _dirs, files in os.walk(out)
                        for n in files if n.endswith("." + ext)]
                self.assertTrue(arts, "a full build still generates the %s" % ext)
                self.assertTrue(os.path.isfile(arts[0] + ".sha512"))

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
        # build() gates PDF + sha512 generation on skip_pdf, so a --skip-pdf tree
        # has neither file; the page must then carry NO <a> link to them, or a
        # link-checker scanning the skip-pdf tree reports two dangling internal
        # links (regression: the family-wide website-tests gate failed on exactly
        # android-insecurity.pdf + .sha512). The citation_pdf_url meta (absolute,
        # canonical) is a separate concern and stays.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            self.assertNotIn('href="art.pdf"', page)
            self.assertNotIn('href="art.pdf.sha512"', page)
            self.assertNotIn(">Download PDF</a>", page)
            # render_article is the single source: a FULL build still offers both.
            journal = g.load_journal(jt)
            m = g.load_article(os.path.join(d, "articles", "art"))
            _rel, _name, full = g.render_article(m, journal, skip_pdf=False)
            self.assertIn('href="art.pdf"', full)
            self.assertIn('href="art.pdf.sha512"', full)
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
             'claims = [{ section = "Sec. 1", text = "the alpha claim" }]\n'
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
            self.assertIn('href="../#citesec-alpha-1" aria-label="Sec. 1 in the paper, '
                          'reference alpha">Sec. 1', sources)   # per-section claim pill
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

    def test_per_section_cite_anchor_and_pill(self):
        # A key cited in several sections gets a per-section anchor (cite-<key>-s<N>)
        # before its first citation in each, and a claim's "Sec. N" pill links there
        # -- so it jumps to THAT section's citation, not pandoc's document-wide first
        # (#cite-<key>). The document-wide anchor stays for the reference backref.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nFirst [@beta].\n\n"
                         "## 2. Background\n\nNothing here.\n\n## 3. Threat\n\n"
                         "Again [@beta].\n\n## 4. References\n\n::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[beta]\nclaims = [{ section = "Sec. 1", text = "a" },'
                         '{ section = "Sec. 3", text = "b" }]\n'
                         'quotes = [{ text = "q" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"),
                      encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn('id="citesec-beta-1"', page)      # per-section anchors
            self.assertIn('id="citesec-beta-3"', page)
            self.assertIn('id="cite-beta"', page)           # document-wide kept
            with open(os.path.join(out, "art", "sources", "index.html"),
                      encoding="utf-8") as fh:
                sources = fh.read()
            self.assertIn('href="../#citesec-beta-1"', sources)   # pills -> per-section
            self.assertIn('href="../#citesec-beta-3"', sources)

    def test_mislabeled_claim_section_fails_build(self):
        # Canary: a claim labeled with a section where its key is NOT cited must fail
        # the build (the pill would dead-link / mislead). RED on pre-check code,
        # which emits no such anchor check and builds without raising.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nOnly here [@beta].\n\n"
                         "## 2. Background\n\nNo citation.\n\n"
                         "## 3. References\n\n::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                # beta is cited only in Section 1, but the claim labels Section 2
                fh.write('[beta]\nclaims = [{ section = "Sec. 2", text = "x" }]\n'
                         'quotes = [{ text = "q" }]\n')
            out = os.path.join(d, "s")
            with self.assertRaises(g.BuildError):
                g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)

    def test_per_section_anchor_namespace_no_collision(self):
        # The per-section anchor lives in its own citesec- namespace, so key `beta`'s
        # Sec. 1 anchor (citesec-beta-1) never collides with a DIFFERENT key literally
        # named `beta-s1` whose document anchor is cite-beta-s1. (Old cite-<key>-s<N>
        # scheme produced a duplicate id + a false-pass.)
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write('@misc{beta, title={{B}}, author={{O}}, '
                         'url={https://b.example/y}, urldate={2026-01-01}}\n'
                         '@misc{beta-s1, title={{B1}}, author={{O}}, '
                         'url={https://b.example/z}, urldate={2026-01-01}}\n')
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nBoth [@beta] and "
                         "[@beta-s1].\n\n## 2. References\n\n::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[beta]\nclaims = [{ section = "Sec. 1", text = "x" }]\n'
                         'quotes = [{ text = "q" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"),
                      encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn('id="cite-beta-s1"', page)        # beta-s1's doc anchor
            self.assertEqual(page.count('id="cite-beta-s1"'), 1)   # no duplicate
            self.assertIn('id="citesec-beta-1"', page)      # beta's per-section anchor

    def test_citation_under_unnumbered_heading_not_section_attributed(self):
        # A citation under an UNnumbered heading maps to no section, so a claim that
        # labels it with a numbered section fails the build (old code leaked it into
        # the preceding numbered section and the mislabel passed).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nNo citation here.\n\n"
                         "## Notes\n\nOnly here [@beta].\n\n"
                         "## 2. References\n\n::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                # beta is cited only under the unnumbered "Notes" heading
                fh.write('[beta]\nclaims = [{ section = "Sec. 1", text = "x" }]\n'
                         'quotes = [{ text = "q" }]\n')
            out = os.path.join(d, "s")
            with self.assertRaises(g.BuildError):
                g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)

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
                # beta and calyx-mg both claim the SAME section (where they are cited)
                # -> same "Sec. 1 ->" pill text, different per-section #cite targets.
                fh.write('[beta]\nclaims = [{ section = "Sec. 1", text = "b" }]\n'
                         'quotes = [{ text = "bq" }]\n'
                         '[calyx-mg]\nclaims = [{ section = "Sec. 1", text = "c" }]\n'
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

    def test_linkify_section_refs(self):
        # In-text "Section N" references get the bare number linked to the matching
        # <h2> (pandoc keeps "N." in the heading text but strips it from the id).
        # RED before _linkify_section_refs existed. Covers: per-target-unique
        # aria-label, connective words/commas left intact, an unmapped number left
        # plain, an existing anchor not double-wrapped, the #refs container untouched.
        body = (
            '<h2 id="bg">8. Background</h2>'
            '<h2 id="detect">9. Detection</h2>'
            '<h2 id="eval">12. Evaluation</h2>'
            '<p>See Section 9 and Sections 8 and 12. Section 99 is out of range. '
            'An <a href="#detect">existing Section 9 link</a> stays.</p>'
            '<div id="refs"><div class="csl-entry">Cites Section 9 here.</div></div>')
        out = g._linkify_cross_refs(body)
        # mapped numbers: only the digit linked, unique aria per target
        self.assertIn('See Section <a href="#detect" aria-label="Section 9">9</a> and',
                      out)
        self.assertIn('Sections <a href="#bg" aria-label="Section 8">8</a> and '
                      '<a href="#eval" aria-label="Section 12">12</a>', out)
        # unmapped number stays plain text (protects the broken-link gate)
        self.assertNotIn('aria-label="Section 99"', out)
        self.assertIn('Section 99 is out of range', out)
        # existing anchor untouched -- no nested/double link
        self.assertIn('<a href="#detect">existing Section 9 link</a>', out)
        # citeproc reference container left verbatim
        self.assertIn('<div id="refs"><div class="csl-entry">Cites Section 9 here.'
                      '</div></div>', out)
        # the added links are collision-safe (2.4.9) and label-in-name clean (2.5.3)
        self.assertEqual(self._link_collisions(out), [])
        self.assertEqual(self._label_in_name_bad(out), [])

    def test_linkify_section_refs_subsection_stays_plain(self):
        # Regression: "Section 3.5" is a pointer into a CITED EXTERNAL work, not this
        # paper's section 3 -- the linker must NOT match "Section 3" inside it (the
        # deployed android-insecurity bug: "(Section 3.5)" linked "3" to #threat-model,
        # leaving ".5" bare). A trailing ".<digit>" disqualifies the number; a
        # sentence-ending period does not. RED on the pre-guard regex.
        body = (
            '<h2 id="tm">3. Threat Model</h2>'
            '<h2 id="big">35. Big Section</h2>'
            '<p>Internal: see Section 3 alone. At the end Section 3. '
            'External: (Section 3.5) and Section 35.5 are sub-section refs.</p>')
        out = g._linkify_cross_refs(body)
        # bare top-level ref links; sentence-ending period still links
        self.assertIn('see Section <a href="#tm" aria-label="Section 3">3</a> alone', out)
        self.assertIn('the end Section <a href="#tm" aria-label="Section 3">3</a>. ', out)
        # sub-section refs into external works stay verbatim plain text
        self.assertIn('(Section 3.5) and Section 35.5 are', out)
        # the exact reported defect: no partial wrap of the top-level digit
        self.assertNotIn('aria-label="Section 3">3</a>.5', out)
        self.assertNotIn('aria-label="Section 35"', out)

    def test_linkify_section_refs_oxford_and_code(self):
        # Oxford-comma list must link EVERY section (regression: ", and" dropped the
        # trailing number -- live in android-insecurity "Sections 8, 10, and 13"); and
        # "Section N" inside <pre>/<code> is never rewritten. RED on the pre-fix code.
        body = (
            '<h2 id="s3">3. Model</h2><h2 id="s8">8. A</h2>'
            '<h2 id="s10">10. B</h2><h2 id="s13">13. C</h2>'
            '<p>As in Sections 8, 10, and 13 we note things. '
            'Run <code>grep Section 3 file</code> next.</p>'
            '<pre><code>see Section 3 for setup</code></pre>')
        out = g._linkify_cross_refs(body)
        # every number in the Oxford-comma run links; connectives stay intact
        self.assertIn('Sections <a href="#s8" aria-label="Section 8">8</a>, '
                      '<a href="#s10" aria-label="Section 10">10</a>, and '
                      '<a href="#s13" aria-label="Section 13">13</a> we note', out)
        # code spans untouched even though section 3 is in the map
        self.assertIn('<code>grep Section 3 file</code>', out)
        self.assertIn('<pre><code>see Section 3 for setup</code></pre>', out)
        self.assertNotIn('aria-label="Section 3"', out)

    def test_linkify_section_refs_subsection_heading_not_mapped(self):
        # A subsection H2 ("3.2. ...") must NOT register as this paper's section 3, so a
        # prose "Section 3" with no top-level section-3 heading stays plain rather than
        # jumping to the 3.2 heading. RED on the pre-(?!\d)-guard _SECTION_H2_RE.
        body = ('<h2 id="sub">3.2. Methods detail</h2>'
                '<p>As discussed in Section 3 above.</p>')
        out = g._linkify_cross_refs(body)
        self.assertIn('in Section 3 above', out)
        self.assertNotIn('<a href="#sub"', out)
        self.assertNotIn('aria-label="Section 3"', out)

    def test_section_refs_linked_in_full_build(self):
        # Wiring guard: render_article must call _linkify_cross_refs, so a numbered
        # section referenced in prose is clickable in the built page. RED if the
        # call-site is removed (the helper-only test would still pass).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with open(os.path.join(d, "articles", "art", "paper.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation purposes here.\n\n## 1. Intro\n\n"
                         "See Section 2 for details.\n\n## 2. More\n\nMore.\n\n"
                         "## 3. End\n\nEnd.\n")
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"),
                      encoding="utf-8") as fh:
                page = fh.read()
        self.assertIn('aria-label="Section 2">2</a>', page)
        self.assertIn('Section <a href="#', page)

    def test_linkify_cross_refs_appendix_after_refs(self):
        # Regression: an appendix follows the citeproc <div id="refs"> container, and
        # its in-text "Section N" refs must still linkify. RED on the old prefix/suffix
        # split, which linkified only the text BEFORE the refs div and appended the
        # rest (the appendices) verbatim -- so Appendix B section mentions were plain.
        body = (
            '<h2 id="s7">7. Storage</h2><h2 id="s9">9. Rootkits</h2>'
            '<h2 id="s13">13. Inspection</h2>'
            '<p>Body ref to Section 7.</p>'
            '<h2 class="unnumbered" id="references">References</h2>'
            '<div id="refs"><div class="csl-entry">A work on Section 7.</div></div>'
            '<h2 class="unnumbered" id="app-b">Appendix B. Rooting</h2>'
            '<p>treated in the body (Sections 7, 9, 10, 11) and, as Section 13 notes.</p>')
        out = g._linkify_cross_refs(body)
        appb = out.split('id="app-b"', 1)[1]
        self.assertIn('<a href="#s7" aria-label="Section 7">7</a>', appb)
        self.assertIn('<a href="#s9" aria-label="Section 9">9</a>', appb)
        self.assertIn('<a href="#s13" aria-label="Section 13">13</a>', appb)
        # unmapped (no section-10/11 heading) stays plain -- broken-link gate honest
        self.assertNotIn('aria-label="Section 10"', appb)
        # the refs-div interior is still left verbatim
        self.assertIn('<div id="refs"><div class="csl-entry">A work on Section 7.'
                      '</div></div>', out)
        self.assertEqual(self._link_collisions(out), [])
        self.assertEqual(self._label_in_name_bad(out), [])

    def test_linkify_table_refs(self):
        # "Table N" references link to the matching caption paragraph (anchored
        # id="tbl-N"); only the digit links. The caption's OWN label does not
        # self-link, but a "Table M" the caption cites does; a sentence-ending period
        # still links; an unmapped number stays plain. RED before table linking.
        body = (
            '<p>As summarized in Table 2. See also Tables 1 and 2.</p>'
            '<p>Table 1. First caption.</p>'
            '<p>Table 2. Second, citing the Table 1 data.</p>')
        out = g._linkify_cross_refs(body)
        # prose refs link (incl. the sentence-ending "Table 2.")
        self.assertIn('summarized in Table <a href="#tbl-2" aria-label="Table 2">2</a>. ',
                      out)
        self.assertIn('Tables <a href="#tbl-1" aria-label="Table 1">1</a> and '
                      '<a href="#tbl-2" aria-label="Table 2">2</a>', out)
        # captions are anchored, and their leading label is NOT self-linked
        self.assertIn('<p id="tbl-1">Table 1. First caption.</p>', out)
        self.assertIn('<p id="tbl-2">Table 2. Second, citing', out)
        # the "Table 1" the caption CITES does link
        self.assertIn('citing the Table <a href="#tbl-1" aria-label="Table 1">1</a> data',
                      out)
        self.assertEqual(self._link_collisions(out), [])
        self.assertEqual(self._label_in_name_bad(out), [])

    def test_linkify_appendix_refs(self):
        # "Appendix X" references link to the matching appendix <h2>; only the letter
        # links. The appendix heading's OWN label does not self-link; an unmapped
        # letter stays plain. RED before appendix linking.
        body = (
            '<p>See Appendix A and Appendix B. Appendix C is absent.</p>'
            '<h2 class="unnumbered" id="app-a.-keys">Appendix A. Keys</h2>'
            '<p>Body.</p>'
            '<h2 class="unnumbered" id="app-b.-rooting">Appendix B. Rooting</h2>')
        out = g._linkify_cross_refs(body)
        self.assertIn('See Appendix <a href="#app-a.-keys" aria-label="Appendix A">A</a>',
                      out)
        self.assertIn('Appendix <a href="#app-b.-rooting" aria-label="Appendix B">B</a>',
                      out)
        # unmapped letter stays plain (no Appendix C heading)
        self.assertNotIn('aria-label="Appendix C"', out)
        # appendix headings are not self-linked
        self.assertIn('>Appendix A. Keys</h2>', out)
        self.assertIn('>Appendix B. Rooting</h2>', out)
        self.assertEqual(self._link_collisions(out), [])
        self.assertEqual(self._label_in_name_bad(out), [])

    def test_linkify_table_ref_trailing_letter_stays_plain(self):
        # Regression: "Table 1a" (a glued-letter figure label) must NOT wrap its "1" as
        # a link to Table 1; a bare "Table 1" still links. The (?!\.\d) guard only
        # blocks a dotted sub-number -- the trailing \b blocks the letter. RED without \b.
        body = (
            '<p>See Table 1a for the variant, and Table 1 for the base.</p>'
            '<p>Table 1. The caption.</p>')
        out = g._linkify_cross_refs(body)
        # glued-letter form left verbatim -- no partial wrap of "1"
        self.assertIn('See Table 1a for the variant', out)
        self.assertNotIn('aria-label="Table 1">1</a>a', out)
        # a plain "Table 1" still links to the caption
        self.assertIn('Table <a href="#tbl-1" aria-label="Table 1">1</a> for the base',
                      out)
        self.assertEqual(self._link_collisions(out), [])
        self.assertEqual(self._label_in_name_bad(out), [])

    def test_linkify_section_ref_trailing_letter_stays_plain(self):
        # Same-class as the table guard: "Section 1a" must NOT wrap "1" as a link to
        # section 1 (the trailing \b rejects the glued letter); a bare "Section 1"
        # still links. RED without \b on _SECTION_REF_RE.
        body = (
            '<h2 id="intro">1. Intro</h2>'
            '<p>See Section 1a (a figure label), but Section 1 is the intro.</p>')
        out = g._linkify_cross_refs(body)
        self.assertIn('See Section 1a (a figure label)', out)
        self.assertNotIn('aria-label="Section 1">1</a>a', out)
        self.assertIn('but Section <a href="#intro" aria-label="Section 1">1</a> is',
                      out)

    def test_linkify_appendix_h2_subheading_not_registered(self):
        # Regression: an "Appendix A.1. Details" SUB-heading must NOT register appendix
        # letter "A" (its id is a sub-section target, not the real Appendix A). With no
        # real "Appendix A" heading, prose "Appendix A" then stays plain rather than
        # linking to the A.1 heading. RED without the (?!\.[A-Za-z0-9]) guard on
        # _APPENDIX_H2_RE.
        body = (
            '<h2 class="unnumbered" id="app-a.1.-details">Appendix A.1. Details</h2>'
            '<p>See Appendix A for the overview.</p>')
        out = g._linkify_cross_refs(body)
        self.assertNotIn('aria-label="Appendix A"', out)
        self.assertNotIn('<a href="#app-a.1.-details"', out)
        self.assertIn('See Appendix A for the overview', out)

    def test_linkify_table_caption_in_body_blockquote_not_targeted(self):
        # Regression: a body quotation blockquote whose first paragraph begins "Table
        # N." must NOT be anchored id="tbl-N" -- it is quoted source, not a caption.
        # RED without the blockquote-span skip in _linkify_cross_refs.
        # (a) blockquote alone, no real caption -> no tbl-1 anchor emitted at all.
        body = ('<blockquote class="quotation"><p>Table 1. As quoted.</p></blockquote>'
                '<p>Body paragraph.</p>')
        out = g._linkify_cross_refs(body)
        self.assertNotIn('id="tbl-1"', out)
        self.assertIn('<blockquote class="quotation"><p>Table 1. As quoted.</p>'
                      '</blockquote>', out)
        # (b) collision: a real caption AND a body blockquote both begin "Table 1." ->
        # exactly ONE id="tbl-1" (the real caption); anchoring the blockquote too would
        # emit a duplicate id.
        body2 = ('<blockquote class="quotation"><p>Table 1. As quoted.</p></blockquote>'
                 '<p>Table 1. The real caption.</p>')
        out2 = g._linkify_cross_refs(body2)
        self.assertEqual(out2.count('id="tbl-1"'), 1)
        self.assertIn('<p id="tbl-1">Table 1. The real caption.</p>', out2)
        # the quotation's own "Table 1" is NOT linkified to the paper's table (a quoted
        # source's cross-ref is not ours) -- the blockquote is left verbatim.
        self.assertIn('<blockquote class="quotation"><p>Table 1. As quoted.</p>'
                      '</blockquote>', out2)
        self.assertEqual(self._link_collisions(out2), [])
        # (c) an unbalanced leading </blockquote> must not drive the span depth negative
        # and swallow the real quotation -> still exactly one id="tbl-1". RED on the
        # un-floored _blockquote_spans.
        body3 = ('</blockquote><blockquote class="quotation"><p>Table 1. Quoted.</p>'
                 '</blockquote><p>Table 1. The real caption.</p>')
        out3 = g._linkify_cross_refs(body3)
        self.assertEqual(out3.count('id="tbl-1"'), 1)
        self.assertIn('<p id="tbl-1">Table 1. The real caption.</p>', out3)

    def test_linkify_refs_in_blockquote_stay_plain(self):
        # A quotation (blockquote) that mentions "Section N"/"Table N" by number refers
        # to the QUOTED SOURCE's structure, not this paper's -- those must stay plain
        # even when the paper has a matching target. RED before <blockquote> joined the
        # protected-span set in _HTML_TAG_OR_ANCHOR_RE.
        body = (
            '<h2 id="intro">1. Intro</h2>'
            '<p>Table 1. Real caption.</p>'
            '<blockquote class="quotation"><p>The source discusses Section 1 and '
            'Table 1 at length.</p></blockquote>'
            '<p>Our prose cites Section 1 and Table 1.</p>')
        out = g._linkify_cross_refs(body)
        bq = out.split('<blockquote', 1)[1].split('</blockquote>', 1)[0]
        self.assertNotIn('<a ', bq)
        self.assertIn('discusses Section 1 and Table 1 at length', bq)
        # our own prose still links
        self.assertIn('cites Section <a href="#intro" aria-label="Section 1">1</a>', out)
        self.assertIn('Table <a href="#tbl-1" aria-label="Table 1">1</a>.', out)

    def test_cross_refs_linked_after_refs_in_full_build(self):
        # End-to-end wiring: a real citeproc refs div sits before the appendix, and a
        # table caption is a plain paragraph. The appendix's "Section 1" ref and a
        # "Table 1" ref must be clickable in the built page. RED if the refs-div-span
        # fix or the table/caption linking regresses.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            adir = os.path.join(d, "articles", "art")
            with open(os.path.join(adir, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write("@misc{k, title={{T}}, author={A}, year={2020}, "
                         "url={https://example.org}}\n")
            with open(os.path.join(adir, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write(
                    "# T\n\n## Abstract\n\nA sufficiently long abstract for the "
                    "validation step here.\n\n"
                    "## 1. Intro\n\nText [@k] and see Table 1.\n\n"
                    "Table 1. A caption.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
                    "## References\n\n::: {#refs}\n:::\n\n"
                    "## Appendix A. Extra\n\nAs Section 1 and Table 1 show.\n")
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
        appendix = page.split("Appendix A", 1)[1]
        # the appendix (after the refs div) links its Section 1 and Table 1 refs
        self.assertIn('aria-label="Section 1">1</a>', appendix)
        self.assertIn('aria-label="Table 1">1</a>', appendix)

    def test_headerlink_affordance(self):
        # Each table caption and each section/subsection/appendix heading gets a trailing
        # "#" permalink to its OWN id -- a separate child <a>, never a self-link of the
        # label. The href reuses the existing id (no new id is emitted); the refs-div
        # content is untouched; every permalink has a distinct aria-label (axe
        # identical-links-same-purpose) and the "#" normalizes away for label-in-name.
        # RED before the _add_headerlinks pass.
        body = (
            '<h2 id="intro">1. Introduction</h2>'
            '<p>Table <a href="#tbl-1" aria-label="Table 1">1</a> summarizes.</p>'
            '<p id="tbl-1">Table 1. Device attestation.</p>'
            '<h3 id="limits">Limitations</h3>'
            '<h2 id="app-a">Appendix A. Extra</h2>'
            '<div id="refs"><div class="csl-entry" id="ref-k">Table 9. A quote.'
            '</div></div>')
        out = g._add_headerlinks(body)
        # table caption: trailing permalink, leading label still plain (no self-link)
        self.assertIn('<p id="tbl-1">Table 1. Device attestation. '
                      '<a class="headerlink" href="#tbl-1" '
                      'aria-label="Permalink to Table 1">#</a></p>', out)
        # headings (h2, h3, appendix h2): trailing permalink carrying the unique id
        self.assertIn('<h2 id="intro">1. Introduction '
                      '<a class="headerlink" href="#intro" '
                      'aria-label="Permalink to 1. Introduction (section intro)">#</a>'
                      '</h2>', out)
        self.assertIn('<h3 id="limits">Limitations '
                      '<a class="headerlink" href="#limits" '
                      'aria-label="Permalink to Limitations (section limits)">#</a>'
                      '</h3>', out)
        self.assertIn('aria-label="Permalink to Appendix A. Extra (section app-a)">#</a>'
                      '</h2>', out)
        # no new id introduced (the href reuses the existing id)
        self.assertEqual(out.count('id="tbl-1"'), 1)
        # refs-div content is untouched (no permalink inside it)
        self.assertIn('<div id="refs"><div class="csl-entry" id="ref-k">'
                      'Table 9. A quote.</div></div>', out)
        # the pre-existing body-ref anchor is left intact
        self.assertIn('<p>Table <a href="#tbl-1" aria-label="Table 1">1</a> '
                      'summarizes.</p>', out)
        self.assertEqual(self._link_collisions(out), [])
        self.assertEqual(self._label_in_name_bad(out), [])

    def test_headerlink_duplicate_titled_headings_distinct_labels(self):
        # Pandoc gives same-titled headings distinct ids (overview, overview-1) but the
        # SAME visible text, so a bare "Permalink to <title>" accessible name would
        # collide under axe identical-links-same-purpose (WCAG 2.4.9). Carrying the
        # unique id in the name keeps each distinct. RED before the id-carrying label.
        body = ('<h3 id="overview">Overview</h3><p>a</p>'
                '<h3 id="overview-1">Overview</h3><p>b</p>')
        out = g._add_headerlinks(body)
        self.assertIn('href="#overview" '
                      'aria-label="Permalink to Overview (section overview)">#</a>', out)
        self.assertIn('href="#overview-1" '
                      'aria-label="Permalink to Overview (section overview-1)">#</a>',
                      out)
        self.assertEqual(self._link_collisions(out), [])
        self.assertEqual(self._label_in_name_bad(out), [])

    def test_headerlink_ordinal_forging_title_does_not_collide(self):
        # An occurrence-ordinal scheme would collide here: a third heading literally
        # titled "Overview (1)" would match the ordinal given to the first repeat. The
        # id-carrying name avoids it because the pandoc id is unique per document. This
        # is the exact input the reviewers flagged against the ordinal approach.
        body = ('<h3 id="a">Overview</h3><h3 id="b">Overview</h3>'
                '<h3 id="c">Overview (1)</h3>')
        out = g._add_headerlinks(body)
        self.assertEqual(self._link_collisions(out), [])
        self.assertEqual(self._label_in_name_bad(out), [])
        # a title differing only by an HTML entity that the accessible-name check
        # normalizes away is still distinguished by its id, not grouped on raw text
        body2 = ('<h2 id="x">A &amp; B</h2><h2 id="y">A &amp; B</h2>')
        out2 = g._add_headerlinks(body2)
        self.assertEqual(self._link_collisions(out2), [])
        self.assertEqual(self._label_in_name_bad(out2), [])

    def test_linkify_table_anchor_ignores_data_id_lookalike(self):
        # Existing-id detection must not treat a data-id value as a real element id: a
        # heading with data-id="tbl-1" must NOT make existing_ids suppress anchoring of
        # the real Table 1 caption. RED when _ID_ATTR_RE used \bid= (it matched the "id"
        # inside data-id).
        body = ('<h2 id="intro" data-id="tbl-1">1. Intro</h2>'
                '<p>See Table 1.</p>'
                '<p>Table 1. Caption.</p>')
        out = g._linkify_cross_refs(body)
        self.assertIn('<p id="tbl-1">Table 1. Caption.</p>', out)
        self.assertIn('Table <a href="#tbl-1" aria-label="Table 1">1</a>', out)

    def test_headerlink_id_match_excludes_data_id(self):
        # The heading-id regex must match the real id attribute, not the "id" inside a
        # neighbouring data-id (a word boundary sits after the hyphen). With \bid= plus a
        # greedy [^>]*, "<h3 id='actual' data-id='other'>" would target #other. RED on
        # the \bid= form.
        body = '<h3 id="actual" data-id="other">Overview</h3>'
        out = g._add_headerlinks(body)
        self.assertIn('href="#actual" '
                      'aria-label="Permalink to Overview (section actual)">#</a>', out)
        self.assertNotIn('href="#other"', out)

    def test_headerlinks_in_full_build(self):
        # End-to-end: the built page exposes a "#" permalink on the table caption AND on
        # section headings, the Contents nav does NOT ingest the glyph (headerlinks are
        # added AFTER the TOC is built), and the whole-page WCAG link helpers stay clean.
        # RED before the _add_headerlinks wiring.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            adir = os.path.join(d, "articles", "art")
            with open(os.path.join(adir, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write(
                    "# T\n\n## Abstract\n\nA sufficiently long abstract for the "
                    "validation step here.\n\n"
                    "## 1. Intro\n\nText and see Table 1.\n\n"
                    "Table 1. A caption.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
                    "## 2. More\n\nMore.\n\n## 3. End\n\nEnd.\n")
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
        # caption and heading permalinks present in the built page
        self.assertIn('<a class="headerlink" href="#tbl-1" '
                      'aria-label="Permalink to Table 1">#</a>', page)
        self.assertIn('<a class="headerlink" href="#intro" '
                      'aria-label="Permalink to 1. Intro (section intro)">#</a>', page)
        # the Contents nav did not ingest the "#" glyph
        toc = page.split('<nav class="toc"', 1)[1].split('</nav>', 1)[0]
        self.assertNotIn('class="headerlink"', toc)
        self.assertNotIn(' #</a>', toc)
        # whole-page WCAG link helpers stay clean with the new anchors
        self.assertEqual(self._link_collisions(page), [])
        self.assertEqual(self._label_in_name_bad(page), [])

    def test_linkify_table_caption_in_refs_not_targeted(self):
        # A source quote inside the citeproc refs container that begins "Table N."
        # must NOT be anchored as tbl-N, and a prose "Table N" with no REAL table must
        # stay plain. Caption discovery runs only outside _refs_div_span.
        body = ('<p>See Table 1.</p>'
                '<div id="refs"><div class="csl-quote"><blockquote>'
                '<p>Table 1. External source text.</p></blockquote></div></div>')
        out = g._linkify_cross_refs(body)
        self.assertNotIn('id="tbl-1"', out)
        self.assertNotIn('href="#tbl-1"', out)
        self.assertIn('<p>Table 1. External source text.</p>', out)

    def test_linkify_appendix_heading_not_self_linked_any_punctuation(self):
        # An appendix heading's own label must never self-link, regardless of trailing
        # punctuation ("Appendix A", "Appendix A:", "Appendix A."). The prose ref still
        # links.
        for head in ('<h2 id="app-a">Appendix A</h2>',
                     '<h2 id="app-a">Appendix A: Keys</h2>',
                     '<h2 id="app-a">Appendix A.</h2>'):
            out = g._linkify_cross_refs(head + '<p>See Appendix A here.</p>')
            heading, prose = out.split('</h2>', 1)
            self.assertNotIn('<a', heading)
            self.assertIn('<a href="#app-a" aria-label="Appendix A">A</a>', prose)

    def test_linkify_appendix_subref_stays_plain(self):
        # A dotted sub-appendix ref into an external work ("Appendix A.1") stays plain,
        # like Section/Table sub-refs; a sentence-ending "Appendix A." still links.
        body = ('<h2 id="app-a">Appendix A. Proofs</h2>'
                '<p>See Appendix A.1 in the source. But Appendix A. links.</p>')
        prose = g._linkify_cross_refs(body).split('</h2>', 1)[1]
        self.assertIn('See Appendix A.1 in the source', prose)
        self.assertIn('Appendix <a href="#app-a" aria-label="Appendix A">A</a>. links',
                      prose)

    def test_linkify_appendix_postcomma_capital_stays_plain(self):
        # A capitalized variable/pronoun after a comma ("In Appendix A, B is ...") must
        # NOT be linked as Appendix B even when Appendix B exists (appendix refs are
        # singular, no connective run).
        body = ('<h2 id="app-a">Appendix A. P</h2><h2 id="app-b">Appendix B. D</h2>'
                '<p>In Appendix A, B is the set.</p>')
        prose = g._linkify_cross_refs(body).split('Appendix B. D</h2>', 1)[1]
        self.assertIn('<a href="#app-a" aria-label="Appendix A">A</a>', prose)
        self.assertNotIn('href="#app-b"', prose)
        self.assertIn(', B is the set', prose)

    def test_linkify_no_cross_pass_splice(self):
        # Pathological: a heading id containing a space and the word "Appendix" must not
        # let the appendix pass rewrite inside the href the section pass just inserted.
        body = ('<h2 id="Appendix A">1. Intro</h2>'
                '<h2 id="app-a">Appendix A. Keys</h2><p>See Section 1.</p>')
        out = g._linkify_cross_refs(body)
        self.assertEqual(re.findall(r'href="#[^"]*<a', out), [])

    def test_linkify_table_caption_id_collision_skipped(self):
        # If a heading already carries id="tbl-N" (pandoc auto-id of a heading named
        # "Tbl N"), the caption is NOT re-anchored to the same id -- no duplicate id.
        body = ('<h2 id="tbl-1">2. Tbl 1</h2><p>See Table 1.</p>'
                '<p>Table 1. Real caption.</p>')
        out = g._linkify_cross_refs(body)
        self.assertEqual(out.count('id="tbl-1"'), 1)

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

    def test_enhance_references_footnote_cite_uses_marker_section(self):
        # A citation pandoc rendered inside a footnote DEFINITION (appended in the
        # unnumbered end-of-document footnotes <section>) must be attributed to the
        # section of its [^id] reference MARKER, not the def's position. Without this
        # a cite moved into a footnote maps to no section (None) -> no citesec anchor
        # -> the sources-card "Sec. N" pill and the claim gate break. RED before the
        # footnote-marker section attribution in _enhance_references.
        body = (
            '<h2 id="disc">14. Discussion</h2>'
            '<p>Verdict: No<a href="#fn1" class="footnote-ref" id="fnref1" '
            'role="doc-noteref"><sup>1</sup></a>.</p>'
            '<h2 id="refs-h" class="unnumbered">References</h2>'
            '<div id="refs"><div class="csl-entry">x</div></div>'
            '<section id="footnotes" class="footnotes footnotes-end-of-document" '
            'role="doc-endnotes"><ol><li id="fn1"><p>A locked bootloader refuses '
            'unsigned images <span class="citation">'
            '<a href="#ref-aosp" role="doc-biblioref">[1]</a></span>.</p></li>'
            '</ol></section>')
        out = g._enhance_references(body, {"aosp"}, {})
        # attributed to the marker's section 14, not the unnumbered footnotes block
        self.assertIn('id="citesec-aosp-14"', out)

    def test_enhance_references_footnote_cite_aside_wrapper(self):
        # pandoc 3.1.3 (Ubuntu 24.04 apt, the CSR selftest + content-deploy pandoc)
        # wraps the end-of-document footnotes in <aside ...>, not the <section ...> of
        # pandoc >= 3.1.11. The marker-section attribution must work for EITHER wrapper
        # -- the CSR pandoc is not version-pinned. RED before _footnotes_span matched
        # <aside> too (span not found -> in-footnote cite mapped to the wrong section,
        # no citesec-aosp-14; this is exactly the CI selftest failure on PR #65).
        body = (
            '<h2 id="disc">14. Discussion</h2>'
            '<p>Verdict: No<a href="#fn1" class="footnote-ref" id="fnref1" '
            'role="doc-noteref"><sup>1</sup></a>.</p>'
            '<h2 id="refs-h" class="unnumbered">References</h2>'
            '<div id="refs"><div class="csl-entry">x</div></div>'
            '<aside id="footnotes" class="footnotes footnotes-end-of-document" '
            'role="doc-endnotes"><ol><li id="fn1"><p>A locked bootloader refuses '
            'unsigned images <span class="citation">'
            '<a href="#ref-aosp" role="doc-biblioref">[1]</a></span>.</p></li>'
            '</ol></aside>')
        out = g._enhance_references(body, {"aosp"}, {})
        self.assertIn('id="citesec-aosp-14"', out)

    def test_footnote_cite_multi_section_refs_attributed_to_all(self):
        # A footnote referenced from MORE THAN ONE section (pandoc reuses #fn1 for each
        # marker) -- its cite must be attributed to EVERY referencing section, not just
        # the last marker's. RED before fn_marker_sec became a per-section list (the
        # overwrite dropped section 1, so a "Sec. 1" claim lost citesec-aosp-1).
        body = (
            '<h2 id="s1">1. Intro</h2>'
            '<p>One<a href="#fn1" class="footnote-ref" id="fnref1" '
            'role="doc-noteref"><sup>1</sup></a>.</p>'
            '<h2 id="s2">2. Method</h2>'
            '<p>Two<a href="#fn1" class="footnote-ref" id="fnref1-2" '
            'role="doc-noteref"><sup>1</sup></a>.</p>'
            '<h2 id="refs-h" class="unnumbered">References</h2>'
            '<div id="refs"><div class="csl-entry">x</div></div>'
            '<section id="footnotes" class="footnotes footnotes-end-of-document" '
            'role="doc-endnotes"><ol><li id="fn1"><p>Caveat <span class="citation">'
            '<a href="#ref-aosp" role="doc-biblioref">[1]</a></span>.</p></li>'
            '</ol></section>')
        out = g._enhance_references(body, {"aosp"}, {})
        self.assertIn('id="citesec-aosp-1"', out)
        self.assertIn('id="citesec-aosp-2"', out)

    def test_footnote_cite_counts_in_marker_section_full_build(self):
        # End-to-end (dev1355's scenario): a [@cite] moved INTO a footnote whose [^id]
        # marker sits in section 1, with a source-quotes claim naming "Sec. 1", must
        # BUILD -- the footnote cite is attributed to the marker's section so the claim
        # gate finds citesec-beta-1. RED before the footnote-marker attribution (build
        # raised BuildError: "@beta claims Sec. 1 but no #citesec-beta-1 anchor").
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            ad = os.path.join(d, "articles", "art")
            with open(os.path.join(ad, "refs.bib"), "w", encoding="utf-8") as fh:
                fh.write(_BIB)
            with open(os.path.join(ad, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nThe device is locked.[^fb]"
                         "\n\n[^fb]: A locked bootloader refuses unsigned images "
                         "[@beta].\n\n## 2. References\n\n::: {#refs}\n:::\n")
            with open(os.path.join(ad, "source-quotes.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write('[beta]\nclaims = [{ section = "Sec. 1", text = "x" }]\n'
                         'quotes = [{ text = "q" }]\n')
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)  # must not raise
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
        self.assertIn('id="citesec-beta-1"', page)

    def test_back_to_top_control_in_full_build(self):
        # The back-to-top control is emitted on every page (<body id="top"> target +
        # a fixed <a class="back-to-top" href="#top">), with its CSS in style.css and
        # its reveal/smooth-scroll JS in site.js. RED before the back-to-top wiring.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with open(os.path.join(d, "articles", "art", "paper.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nBody.\n")
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            with open(os.path.join(out, "assets", "style.css"), encoding="utf-8") as fh:
                css = fh.read()
            with open(os.path.join(out, "assets", "site.js"), encoding="utf-8") as fh:
                js = fh.read()
        self.assertIn('<body id="top">', page)
        self.assertIn('class="back-to-top" href="#top"', page)
        self.assertIn('aria-label="Back to top of the page"', page)
        self.assertIn('.back-to-top {', css)
        self.assertIn('.back-to-top', js)
        self.assertIn('scrollTo', js)
        # a11y: hide the control on blur near the top, so keyboard focus leaving it
        # does not leave it lingering until the next scroll.
        self.assertIn('btn.addEventListener("blur"', js)
        # No-JS reveal floor: a scroll-driven @supports animation reveals the control
        # past the same ~400px threshold, so a no-JS reader does not get it stuck
        # visible at the top. Must stay guarded so legacy browsers fall through visible.
        self.assertIn('@supports (animation-timeline: scroll())', css)
        self.assertIn('animation-timeline: scroll(root)', css)
        self.assertIn('@keyframes back-to-top-reveal', css)
        # JS-scoped (:root:not(.js)) so the floor is a pure no-JS fallback and never
        # fights the JS focus-guard; SITE_JS marks the document js-capable to disable it.
        self.assertIn(':root:not(.js) .back-to-top', css)
        self.assertIn('classList.add("js")', js)
        # Discrete visibility flip (no opacity fade) keeps the hidden control out of the
        # tab order / non-clickable, and never interactive-while-faint: the control is
        # either fully hidden or fully shown, matching the JS path's instant toggle.
        self.assertIn('visibility: hidden; animation: back-to-top-reveal', css)
        self.assertNotIn('opacity: 0; visibility: hidden; animation', css)
        # A focused no-JS control stays visible regardless of scroll (parity with the
        # JS focus-guard): visibility:hidden must not drop focus / its focus indicator.
        self.assertIn(':root:not(.js) .back-to-top:focus', css)
        # Phased fade (JS path): the control fades in/out via an eased opacity
        # transition (.btt-hidden toggled by the script), mirroring the production wiki
        # back-to-top, instead of the old binary [hidden]/display snap. RED before the
        # phased-fade rework (old code toggled btn.hidden = true/false).
        self.assertNotIn('btn.hidden', js)
        self.assertIn('classList.add("btt-hidden")', js)
        self.assertIn(':root.js .back-to-top.btt-hidden { opacity: 0; visibility: hidden; '
                      'pointer-events: none; }', css)
        self.assertIn('transition: opacity 0.3s ease', css)
        self.assertIn('.btt-anim.btt-hidden { transition: opacity 0.3s ease, '
                      'visibility 0s linear 0.3s', css)
        # Initial hide is committed under the base (no-opacity) transition via a forced
        # reflow BEFORE .btt-anim enables the fade, so a deferred script shows no fade-out
        # on load (a lone requestAnimationFrame batches both class adds into one style pass
        # and would still play the 300ms fade -- so the reflow, not rAF, is load-bearing).
        self.assertIn('void btn.offsetHeight', js)
        self.assertIn('btn.classList.add("btt-anim")', js)
        # a11y guards on the fade-out (visibility:hidden is delayed 0.3s so the fade is
        # seen, which leaves the control hit-testable/tabbable mid-fade): pointer-events
        # drops the click target at once, and a control focused mid-fade is held shown so
        # the delayed visibility:hidden cannot drop its focus.
        self.assertIn(':root.js .back-to-top.btt-hidden:focus', css)
        # Reduced-motion users get an instant toggle, not the fade.
        self.assertIn('@media (prefers-reduced-motion: reduce)', css)
        # Look: a translucent dark chip (production parity), inverted to a translucent LIGHT
        # chip in dark mode so a white chevron stays visible on a dark page.
        self.assertIn('.back-to-top { position: fixed;', css)
        self.assertIn('background: rgba(0, 0, 0, 0.35); color: #fff;', css)
        self.assertIn(':root[data-theme="dark"] .back-to-top { background: rgba(255, 255, 255, 0.32)', css)
        # Click: force an instant jump for reduced-motion ("auto" would honor a CSS smooth
        # scroll), then release focus so the control does not linger at the top catching clicks.
        self.assertIn('behavior: reduce ? "instant" : "smooth"', js)
        self.assertIn('if (e.detail > 0) { btn.blur(); }', js)

    def test_footnote_hovercard_in_full_build(self):
        # A footnote marker gets a hovercard preview of the note, reusing the
        # citation hovercard's .hovercard chrome; progressive (the marker stays a
        # working <a href="#fnN"> with no JS). The page must carry the marker and
        # site.js the footnote-hovercard wiring. RED before the footnote-hovercard
        # IIFE (site.js had no a.footnote-ref hovercard handler).
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with open(os.path.join(d, "articles", "art", "paper.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nThe device is "
                         "locked.[^fb]\n\n[^fb]: A locked bootloader refuses "
                         "unsigned images.\n")
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            with open(os.path.join(out, "assets", "site.js"), encoding="utf-8") as fh:
                js = fh.read()
        self.assertIn('class="footnote-ref"', page)   # pandoc emits the marker
        # the footnote-hovercard handler (distinct from the citation one)
        self.assertIn("a.footnote-ref[href^='#fn']", js)
        self.assertIn(".footnote-back", js)
        # a11y: the preview is decorative (aria-hidden) and its links are
        # neutralized (href stripped), so it is not a focusable-but-unreachable
        # tab trap -- the live links stay reachable via the marker's #fnN jump.
        self.assertIn('card.setAttribute("aria-hidden", "true")', js)
        self.assertIn('removeAttribute("href")', js)

    def test_no_fouc_or_reload_shift_invariants(self):
        # No content shift on reload / no FOUC, locked structurally (empirically
        # CLS=0 on reload). The three reflow/flash sources are kept eliminated:
        #   - CSS is a RENDER-BLOCKING same-origin <link> in <head> (styled first
        #     paint), never an async preload/print-media swap (a known FOUC pattern);
        #   - NO web fonts (system stack), so no font-swap reflow;
        #   - site.js is DEFERRED (enhancements run after paint; they insert only
        #     fixed/absolute/hidden nodes, so no flow shift).
        # RED if a regression makes the CSS async, adds a web font, or drops defer.
        with tempfile.TemporaryDirectory() as d:
            jt = self._site(d)
            with open(os.path.join(d, "articles", "art", "paper.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("# T\n\n## Abstract\n\nA sufficiently long abstract for "
                         "validation here.\n\n## 1. Intro\n\nBody.\n")
            out = os.path.join(d, "s")
            g.build(os.path.join(d, "articles"), jt, out, skip_pdf=True)
            with open(os.path.join(out, "art", "index.html"), encoding="utf-8") as fh:
                page = fh.read()
            with open(os.path.join(out, "assets", "style.css"), encoding="utf-8") as fh:
                css = fh.read()
        head = page[:page.index("</head>")]
        # render-blocking stylesheet in <head>, not an async/print swap
        self.assertIn('rel="stylesheet"', head)
        self.assertIn('assets/style.css"', head)
        self.assertNotIn('rel="preload"', head)
        self.assertNotIn('media="print"', head)
        # deferred JS (after first paint)
        self.assertIn('assets/site.js" defer>', page)
        # system-font stack: no web fonts anywhere -> no font-swap reflow
        for sink in ("@font-face", "fonts.googleapis", "fonts.gstatic", "@import"):
            self.assertNotIn(sink, css)
            self.assertNotIn(sink, head)

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
        self.assertIn('href="../#citesec-alpha-3" aria-label="Sec. 3 in the paper, '
                      'reference alpha">Sec. 3', card)   # per-section claim pill
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
        # each pill links to its own section's per-section anchor
        self.assertIn('href="../#citesec-k-7"', card)
        self.assertIn('href="../#citesec-k-13"', card)
        self.assertEqual(card.count('href="../#citesec-k-'), 2)

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


_GOOD_MEM = "https://web.archive.org/web/20260102030405/https://a.example/x"


class _FakeResp:
    def __init__(self, body):
        self._b = body.encode("utf-8")

    def read(self):
        return self._b

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """Serves queued response bodies (or raises a queued exception) for archive.py tests."""

    def __init__(self, responses):
        self._r = list(responses)

    def open(self, req, timeout=None):
        r = self._r.pop(0)
        if isinstance(r, Exception):
            raise r
        return _FakeResp(r)


def _no_sleep(testcase):
    orig = a._sleep
    a._sleep = lambda _s: None
    testcase.addCleanup(lambda: setattr(a, "_sleep", orig))


class TestArchiveSidecar(unittest.TestCase):
    """archive = {...} honesty gate + helpers. Canaries: prove the gate FAILS on a forged /
    bare-redirect / mismatched memento, so only a genuine dated snapshot can ever render."""

    def _dir(self, toml, bib=_BIB):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        with open(os.path.join(d, "refs.bib"), "w", encoding="utf-8") as fh:
            fh.write(bib)
        with open(os.path.join(d, "source-quotes.toml"), "w", encoding="utf-8") as fh:
            fh.write(toml)
        return d

    # --- _parse_memento / _norm_url_for_compare (pure) ---
    def test_parse_memento_date_and_original(self):
        self.assertEqual(g._parse_memento(_GOOD_MEM), ("2026-01-02", "https://a.example/x"))
        # an if_/id_ modifier after the 14 digits is tolerated; the date is unchanged
        self.assertEqual(
            g._parse_memento("https://web.archive.org/web/20260102030405if_/https://a.example/x"),
            ("2026-01-02", "https://a.example/x"))

    def test_parse_memento_rejects_non_snapshots(self):
        for bad in ("https://web.archive.org/web/https://a.example/x",     # bare redirect
                    "https://web.archive.org/web/2026/https://a.example/x",  # short ts
                    "http://web.archive.org/web/20260102030405/https://a.example/x",  # http
                    "https://web.archive.org/web/20261301000000/https://a.example/x",  # month 13
                    "https://web.archive.org/web/20260132000000/https://a.example/x",  # day 32
                    "https://evil.example/x"):
            self.assertIsNone(g._parse_memento(bad), bad)

    def test_norm_url_for_compare(self):
        n = g._norm_url_for_compare
        self.assertEqual(n("https://a.example/x/"), n("https://a.example/x"))
        # ROOT url: a bare host and a lone "/" are equivalent (RFC 3986 6.2.3); Wayback
        # canonicalizes the embedded original WITH the slash, so a bib url written without
        # one must still match its own snapshot. Regression: the old len(path)>1 guard left
        # the root "/" on, so every root url was wrongly rejected as a different-url memento.
        self.assertEqual(n("https://a.example/"), n("https://a.example"))
        # FRAGMENT: a #anchor is client-side (RFC 3986 3.5), never captured by any archiver,
        # so a memento of the fragmentless page must match the #anchored citation -- else the
        # entry is permanently un-archivable. Query is kept distinct; only the fragment drops.
        self.assertEqual(n("https://a.example/x#sec"), n("https://a.example/x"))
        self.assertEqual(n("https://a.example/p?q=1#frag"), n("https://a.example/p?q=1"))
        self.assertEqual(n("https://A.Example/x"), n("https://a.example/x"))
        self.assertEqual(n("https://a.example/%7Ex"), n("https://a.example/~x"))  # unreserved
        # a reserved octet stays escaped: a%2Fb must NOT compare equal to a/b, so a memento
        # of a structurally-different url cannot slip through the honesty gate.
        self.assertNotEqual(n("https://a.example/a%2Fb"), n("https://a.example/a/b"))

    # --- _load_sidecar archive-shape canaries (pure, no pandoc) ---
    def test_valid_archive_memento_loads(self):
        d = self._dir('[alpha]\nquotes = [{ text = "x" }]\n'
                      'archive = { memento = "%s" }\n' % _GOOD_MEM)
        self.assertIn("alpha", g._load_sidecar(d))

    def test_valid_archive_no_memento_loads(self):
        d = self._dir('[alpha]\nquotes = [{ text = "x" }]\n'
                      'archive = { no_memento = "EUR-Lex not archivable" }\n')
        self.assertIn("alpha", g._load_sidecar(d))

    def test_archive_bad_shapes_rejected(self):
        bad_archives = (
            'archive = { memento = "https://web.archive.org/web/https://a.example/x" }',  # bare redirect
            'archive = { memento = "https://web.archive.org/web/2026/https://a.example/x" }',  # short ts
            'archive = { memento = "http://web.archive.org/web/20260102030405/https://a.example/x" }',  # http
            'archive = { memento = "%s", no_memento = "x" }' % _GOOD_MEM,  # both
            'archive = {}',                                               # neither
            'archive = { foo = "x" }',                                    # unknown subfield
            'archive = { memento = 1 }',                                  # non-string
            'archive = { no_memento = "" }',                              # empty reason
            'archive = "nope"',                                           # not a table
        )
        for arc in bad_archives:
            d = self._dir('[alpha]\nquotes = [{ text = "x" }]\n' + arc + "\n")
            with self.assertRaises(g.BuildError, msg=arc):
                g._load_sidecar(d)

    # --- _checked_memento honesty gate (pure, no pandoc): embedded original vs bib url ---
    def test_gate_rejects_mismatched_memento(self):
        bad = "https://web.archive.org/web/20260102030405/https://WRONG.example/x"
        with self.assertRaises(g.BuildError) as cm:
            g._checked_memento("d", "alpha", {"memento": bad}, "https://a.example/x")
        self.assertIn("does not match", str(cm.exception))

    def test_gate_rejects_memento_on_linkless_entry(self):
        # No bib url to verify against -> cannot honestly render; fail.
        with self.assertRaises(g.BuildError):
            g._checked_memento("d", "alpha", {"memento": _GOOD_MEM}, "")

    def test_gate_accepts_matching_memento(self):
        self.assertEqual(
            g._checked_memento("d", "alpha", {"memento": _GOOD_MEM}, "https://a.example/x"),
            _GOOD_MEM)
        # a trailing-slash-only difference still matches
        self.assertEqual(
            g._checked_memento("d", "alpha", {"memento": _GOOD_MEM}, "https://a.example/x/"),
            _GOOD_MEM)
        # ROOT url: Wayback embeds the original WITH a slash; a root bib url without one must
        # still match (regression -- previously rejected, forcing every root url to no_memento).
        root_mem = "https://web.archive.org/web/20260102030405/https://a.example/"
        self.assertEqual(
            g._checked_memento("d", "alpha", {"memento": root_mem}, "https://a.example"),
            root_mem)
        # FRAGMENT: the cited url has a #section but the memento (like any snapshot) embeds the
        # fragmentless page -- it must still match, or an #anchored citation can never archive.
        self.assertEqual(
            g._checked_memento("d", "alpha", {"memento": _GOOD_MEM},
                               "https://a.example/x#install"), _GOOD_MEM)

    def test_gate_matches_when_bib_url_is_itself_a_memento(self):
        # refs.bib url already a Wayback memento -> compare against its embedded original.
        bib_mem = "https://web.archive.org/web/20200101000000/https://a.example/x"
        self.assertEqual(
            g._checked_memento("d", "alpha", {"memento": _GOOD_MEM}, bib_mem), _GOOD_MEM)

    def test_gate_no_memento_returns_none(self):
        self.assertIsNone(
            g._checked_memento("d", "alpha", {"no_memento": "paywalled"}, "https://a.example/x"))


class TestArchiveRender(unittest.TestCase):
    """_enhance_references emits Robust Links Variant A + a visible no-JS archive link, and
    leaves the href (live original) and any doi.org link untouched. Pure; no pandoc."""

    def _ref(self):
        return ('<p><a href="#ref-alpha" role="doc-biblioref">[1]</a></p>'
                '<div id="ref-alpha" class="csl-entry" role="listitem">'
                '<div class="csl-left-margin">[1]</div>'
                '<div class="csl-right-inline">Org A. Available: '
                '<a href="https://a.example/x">https://a.example/x</a>. '
                'doi: <a href="https://doi.org/10.1/x">10.1/x</a></div></div>')

    def test_memento_renders_robust_link_and_visible_link(self):
        out = g._enhance_references(self._ref(), set(), {}, {"alpha": _GOOD_MEM})
        # Variant A: href stays the LIVE original, data-* carry the snapshot.
        self.assertIn('href="https://a.example/x" data-versionurl="%s" '
                      'data-versiondate="2026-01-02"' % _GOOD_MEM, out)
        # Visible, no-JS archive link with the derived date.
        self.assertIn('class="csl-archive"', out)
        self.assertIn("archived 2026-01-02", out)
        # The doi.org link is never turned into an archive anchor.
        self.assertNotIn('href="https://doi.org/10.1/x" data-versionurl', out)

    def test_no_memento_emits_no_archive_link(self):
        out = g._enhance_references(self._ref(), set(), {}, {})
        self.assertNotIn("csl-archive", out)
        self.assertNotIn("data-versionurl", out)

    def test_augment_skips_already_archived_anchor(self):
        inner = ('see <a href="https://web.archive.org/web/20200101000000/https://a.example/x">'
                 'old</a>')
        _out, hit = g._augment_archive_anchor(
            inner, "https://a.example/x", _GOOD_MEM, "2026-01-02")
        self.assertFalse(hit)   # the only anchor is already a memento -> not augmented

    def test_augment_doi_anchor_that_is_the_cited_source(self):
        # A doi.org link IS augmented when it is the cited original (the url-equality test,
        # not a blanket doi skip, decides); an unrelated doi link stays untouched.
        inner = ('<a href="https://doi.org/10.1/x">x</a> '
                 '<a href="https://doi.org/10.9/other">o</a>')
        mem = "https://web.archive.org/web/20260102030405/https://doi.org/10.1/x"
        out, hit = g._augment_archive_anchor(inner, "https://doi.org/10.1/x", mem, "2026-01-02")
        self.assertTrue(hit)
        self.assertIn('href="https://doi.org/10.1/x" data-versionurl="%s"' % mem, out)
        self.assertNotIn('href="https://doi.org/10.9/other" data-versionurl', out)


class TestArchiveCli(unittest.TestCase):
    def test_delay_validator(self):
        import argparse
        self.assertEqual(cli._nonneg_float("4"), 4.0)
        self.assertEqual(cli._nonneg_float("0"), 0.0)
        for bad in ("-1", "nan", "inf"):
            with self.assertRaises(argparse.ArgumentTypeError):
                cli._nonneg_float(bad)


class TestArchiveTool(unittest.TestCase):
    """archive.py pure helpers: Availability parsing, memento matching, Retry-After, and the
    surgical source-quotes.toml apply. No live network."""

    def test_closest_memento_parsing(self):
        js = {"archived_snapshots": {"closest": {
            "url": "http://web.archive.org/web/20260102030405/https://a.example/x"}}}
        self.assertEqual(a._closest_memento(js), _GOOD_MEM)   # http forced to https
        self.assertIsNone(a._closest_memento({"archived_snapshots": {}}))
        self.assertIsNone(a._closest_memento(
            {"archived_snapshots": {"closest": {"url": "https://web.archive.org/web/x/y"}}}))

    def test_memento_matches(self):
        self.assertTrue(a._memento_matches(_GOOD_MEM, "https://a.example/x"))
        self.assertTrue(a._memento_matches(_GOOD_MEM, "https://a.example/x/"))  # trailing slash
        self.assertFalse(a._memento_matches(_GOOD_MEM, "https://b.example/y"))
        self.assertFalse(a._memento_matches("https://web.archive.org/web/x/y",
                                            "https://a.example/x"))

    def test_retry_after_seconds(self):
        self.assertEqual(a._retry_after_seconds("5"), 5.0)
        self.assertIsNone(a._retry_after_seconds("not-a-date"))
        self.assertIsNone(a._retry_after_seconds(None))

    def test_spn_memento_from_status(self):
        ok = {"status": "success", "timestamp": "20260102030405",
              "original_url": "https://a.example/x"}
        self.assertEqual(a._spn_memento_from_status(ok), _GOOD_MEM)
        self.assertIsNone(a._spn_memento_from_status({"status": "pending"}))
        self.assertIsNone(a._spn_memento_from_status(
            {"status": "success", "original_url": "https://a.example/x"}))  # no timestamp
        self.assertIsNone(a._spn_memento_from_status(
            {"status": "success", "timestamp": "20261301000000",            # month 13
             "original_url": "https://a.example/x"}))

    def test_save_page_now_auth_submit_poll_success(self):
        _no_sleep(self)
        op = _FakeOpener([
            json.dumps({"job_id": "J1", "url": "https://a.example/x"}),
            json.dumps({"status": "pending"}),
            json.dumps({"status": "success", "timestamp": "20260102030405",
                        "original_url": "https://a.example/x"})])
        mem = a._save_page_now_auth("https://a.example/x", "AK", "SK", opener=op,
                                    base_delay=0, log=lambda _m: None)
        self.assertEqual(mem, _GOOD_MEM)

    def test_save_page_now_auth_rejects_non_dict(self):
        _no_sleep(self)
        op = _FakeOpener([json.dumps(["not", "an", "object"])])
        self.assertIsNone(a._save_page_now_auth("https://a.example/x", "AK", "SK",
                                                opener=op, base_delay=0, log=lambda _m: None))

    def test_availability_transient_failure_is_sentinel(self):
        _no_sleep(self)
        err = urllib.error.HTTPError("https://archive.org/x", 429, "rl",
                                     email.message.Message(), None)
        self.assertIs(
            a._availability("https://a.example/x", opener=_FakeOpener([err, err, err, err]),
                            base_delay=0, log=lambda _m: None),
            a._LOOKUP_FAILED)

    def test_redirect_handler_blocks_offhost_keeps_archive(self):
        h = a._ArchiveOnlyRedirect()
        req = urllib.request.Request("https://web.archive.org/save/x")
        with self.assertRaises(urllib.error.HTTPError):
            h.redirect_request(req, _FakeResp(""), 302, "", {}, "https://evil.example/x")
        with self.assertRaises(urllib.error.HTTPError):   # off-host even if https
            h.redirect_request(req, _FakeResp(""), 302, "", {},
                               "http://web.archive.org/x")   # non-https
        out = h.redirect_request(
            req, _FakeResp(""), 302, "", {},
            "https://web.archive.org/web/20260101000000/https://a.example/x")
        self.assertIsNotNone(out)

    def test_header_key_quoted_dotted_and_comment(self):
        self.assertEqual(a._header_key("[alpha]\n"), "alpha")
        self.assertEqual(a._header_key('["a.b.c"]\n'), "a.b.c")   # dotted citekey must quote
        self.assertEqual(a._header_key("[alpha]   # a note\n"), "alpha")
        self.assertIsNone(a._header_key("label = 1\n"))
        self.assertIsNone(a._header_key("[[arr]]\n"))

    def test_atomic_write_replaces_file(self):
        import shutil as _sh
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: _sh.rmtree(d))
        p = os.path.join(d, "f.toml")
        a._atomic_write(p, "hello\n")
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "hello\n")

    def test_apply_rejects_symlinked_toml(self):
        import shutil as _sh
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: _sh.rmtree(d))
        target = os.path.join(d, "real.toml")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write('[alpha]\nquotes = [{ text = "x" }]\n')
        os.symlink(target, os.path.join(d, "source-quotes.toml"))
        cache = os.path.join(d, "cache.json")
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump({"alpha": {"memento": _GOOD_MEM}}, fh)
        with self.assertRaises(g.BuildError) as cm:
            a.apply(d, cache_path=cache, log=lambda _m: None)
        self.assertIn("symlink", str(cm.exception))

    def test_fetch_absence_transient_success_reuse(self):
        import shutil as _sh
        _no_sleep(self)
        orig_csl = g._csl_entries
        g._csl_entries = lambda _bib: {"alpha": {"URL": "https://a.example/x"}}
        self.addCleanup(lambda: setattr(g, "_csl_entries", orig_csl))
        orig_av = a._availability
        self.addCleanup(lambda: setattr(a, "_availability", orig_av))
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: _sh.rmtree(d))
        with open(os.path.join(d, "refs.bib"), "w", encoding="utf-8") as fh:
            fh.write("unused -- _csl_entries is patched")
        cache_path = os.path.join(d, "cache.json")
        kw = dict(save=False, tor=False, base_delay=0, log=lambda _m: None)

        def _rm():
            if os.path.exists(cache_path):
                os.remove(cache_path)

        a._availability = lambda _u, **_k: None                       # confirmed absence
        c = a.fetch(d, cache_path=cache_path, **kw)
        self.assertEqual(c["alpha"], {"no_memento": "no Wayback snapshot available"})

        _rm()
        a._availability = lambda _u, **_k: a._LOOKUP_FAILED           # transient -> unresolved
        c = a.fetch(d, cache_path=cache_path, **kw)
        self.assertNotIn("alpha", c)                                  # NOT recorded no_memento

        _rm()
        a._availability = lambda _u, **_k: _GOOD_MEM                  # success
        c = a.fetch(d, cache_path=cache_path, **kw)
        self.assertEqual(c["alpha"], {"memento": _GOOD_MEM})

        def _boom(*_a, **_k):                                         # reuse: must not re-query
            raise AssertionError("availability called despite a valid cached memento")
        a._availability = _boom
        c = a.fetch(d, cache_path=cache_path, **kw)
        self.assertEqual(c["alpha"], {"memento": _GOOD_MEM})

    def test_archive_toml_line(self):
        self.assertEqual(a._archive_toml_line({"memento": _GOOD_MEM}),
                         'archive = { memento = "%s" }\n' % _GOOD_MEM)
        self.assertEqual(a._archive_toml_line({"no_memento": 'a "q" b'}),
                         'archive = { no_memento = "a \\"q\\" b" }\n')

    def test_apply_text_inserts_and_is_idempotent(self):
        toml = ('[alpha]\nlabel = "a"\nquotes = [{ text = "x" }]\n\n'
                '[beta]\nquotes = [{ text = "y" }]\n')
        cache = {"alpha": {"memento": _GOOD_MEM}}
        new, applied = a._apply_text(toml, cache)
        self.assertEqual(applied, {"alpha"})
        self.assertIn('[alpha]\narchive = { memento = "%s" }\n' % _GOOD_MEM, new)
        self.assertIn('[beta]\nquotes', new)          # other tables untouched
        # Re-apply must not duplicate the line (drops the stale one first).
        new2, _ = a._apply_text(new, cache)
        self.assertEqual(new2.count("archive = {"), 1)

    def test_apply_text_only_managed_tables(self):
        toml = '[alpha]\nquotes = [{ text = "x" }]\narchive = { no_memento = "keep me" }\n'
        # beta is in the cache but absent from the file -> not applied (caller treats as drift)
        _new, applied = a._apply_text(toml, {"beta": {"memento": _GOOD_MEM}})
        self.assertEqual(applied, set())

    def test_apply_text_preserves_multiline_string(self):
        # A managed table with a multiline string whose body contains `[beta]` and an
        # `archive =` line must NOT be corrupted: the archive line is inserted at the table
        # level and the string body is untouched (the line editor skips multiline bodies).
        toml = ('[alpha]\nno_quote = """\n'
                'archive = part of the reason\n[beta]\nmore\n"""\n\n'
                '[beta]\nquotes = [{ text = "y" }]\n')
        cache = {"alpha": {"memento": _GOOD_MEM}}
        new, applied = a._apply_text(toml, cache)
        self.assertEqual(applied, {"alpha"})
        self.assertIn('[alpha]\narchive = { memento = "%s" }\nno_quote = """' % _GOOD_MEM, new)
        self.assertIn('archive = part of the reason\n[beta]\nmore\n"""', new)
        a._verify_only_archive_changed(toml, new, cache, "t.toml")   # must not raise
        parsed = tomllib.loads(new)
        self.assertIn("[beta]", parsed["alpha"]["no_quote"])   # string body intact
        self.assertEqual(parsed["alpha"]["archive"], {"memento": _GOOD_MEM})

    def test_verify_rejects_a_non_archive_change(self):
        # The fail-closed net: if the edit changed anything but the archive field, refuse.
        old = '[alpha]\nquotes = [{ text = "x" }]\n'
        corrupt = '[alpha]\nquotes = [{ text = "CORRUPT" }]\narchive = { memento = "%s" }\n' % _GOOD_MEM
        with self.assertRaises(g.BuildError):
            a._verify_only_archive_changed(old, corrupt, {"alpha": {"memento": _GOOD_MEM}}, "t.toml")


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
