import tempfile
import unittest
from pathlib import Path

from paper_radar._http import ssl_context
from paper_radar.retrieval import (
    ArxivClient,
    HybridRetriever,
    PaperMetadata,
    PdfDownloader,
    SemanticScholarClient,
    choose_allowed_show,
    parse_latest_section_header,
)


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, html: str | dict[str, str]):
        self.html = html
        self.urls = []

    def get(self, url: str, *, timeout: int):
        self.urls.append((url, timeout))
        if isinstance(self.html, dict):
            return FakeResponse(self.html[url])
        return FakeResponse(self.html)


class RetrievalTests(unittest.TestCase):
    def test_choose_allowed_show_uses_arxiv_valid_values(self):
        cases = [
            (25, 25),
            (26, 50),
            (50, 50),
            (51, 100),
            (100, 100),
            (101, 250),
            (250, 250),
            (251, 500),
            (500, 500),
            (501, 1000),
            (1000, 1000),
            (1001, 2000),
            (2000, 2000),
            (2001, 2000),
        ]

        for total, expected_show in cases:
            with self.subTest(total=total):
                self.assertEqual(choose_allowed_show(total), expected_show)

    def test_latest_section_header_parser_reads_date_and_expected_total(self):
        html = """
        <h3>Fri, 5 Jun 2026 (showing first 50 of 798 entries)</h3>
        <dl></dl>
        """

        header = parse_latest_section_header(html)

        self.assertIsNotNone(header)
        self.assertEqual(header.section_date, "Fri, 5 Jun 2026")
        self.assertEqual(header.section_date_iso, "2026-06-05")
        self.assertEqual(header.expected_total, 798)
        self.assertFalse(header.continued)

    def test_latest_section_header_parser_handles_continued_and_range_headers(self):
        cases = [
            (
                """
                <h3>
                  Fri, 5 Jun 2026
                  (continued, showing 50 of 798 entries)
                </h3>
                """,
                "Fri, 5 Jun 2026",
                "2026-06-05",
                798,
                True,
            ),
            (
                '<h3 class="list-title">Fri, 5 Jun 2026 (showing 1-50 of 798 entries)</h3>',
                "Fri, 5 Jun 2026",
                "2026-06-05",
                798,
                False,
            ),
            (
                "<h3>Fri, 5 Jun 2026 (showing first 50 of 798 entries )</h3>",
                "Fri, 5 Jun 2026",
                "2026-06-05",
                798,
                False,
            ),
            (
                "<h3>Fri, 05 Jun 2026&nbsp;(showing first 50 of 798 entries)</h3>",
                "Fri, 5 Jun 2026",
                "2026-06-05",
                798,
                False,
            ),
            (
                "<h3>Mon, 1 Jun 2026 (continued, showing last 46 of 758 entries)</h3>",
                "Mon, 1 Jun 2026",
                "2026-06-01",
                758,
                True,
            ),
        ]

        for html, expected_label, expected_iso, expected_total, continued in cases:
            with self.subTest(html=html):
                header = parse_latest_section_header(html)

                self.assertIsNotNone(header)
                self.assertEqual(header.section_date, expected_label)
                self.assertEqual(header.section_date_iso, expected_iso)
                self.assertEqual(header.expected_total, expected_total)
                self.assertEqual(header.continued, continued)

    def test_arxiv_list_parser_filters_only_target_date_section(self):
        html = """
        <h3>Fri, 5 Jun 2026 (showing first 3 of 3 entries)</h3>
        <dl>
          <dt><a href="/abs/2606.00001">arXiv:2606.00001</a></dt>
          <dd><div class="list-title"><span class="descriptor">Title:</span>Latest One</div></dd>
          <dt><a href="/abs/2606.00002">arXiv:2606.00002</a></dt>
          <dd><div class="list-title"><span class="descriptor">Title:</span>Latest Two</div></dd>
        </dl>
        <h3>Thu, 4 Jun 2026 (showing first 2 of 2 entries)</h3>
        <dl>
          <dt><a href="/abs/2606.00003">arXiv:2606.00003</a></dt>
          <dd><div class="list-title"><span class="descriptor">Title:</span>Older One</div></dd>
        </dl>
        """

        papers = ArxivClient(client=FakeSession(html))._parse_entries_from_html(
            html,
            target_section="Fri, 5 Jun 2026",
        )

        self.assertEqual([paper.arxiv_id for paper in papers], ["2606.00001", "2606.00002"])
        self.assertEqual([paper.title for paper in papers], ["Latest One", "Latest Two"])

    def test_semantic_scholar_rotates_keys_and_filters_non_arxiv(self):
        calls = []

        def fake_get(url, *, params, headers, timeout):
            calls.append(headers["x-api-key"])
            return {
                "data": [
                    {
                        "paperId": "s2-1",
                        "title": "Agent Safety",
                        "abstract": "LLM agent safety",
                        "publicationDate": "2026-05-29",
                        "externalIds": {"ArXiv": "2605.12345"},
                        "openAccessPdf": {"url": "https://pdf.example/paper.pdf"},
                        "tldr": {"text": "TLDR"},
                        "url": "https://semanticscholar.org/paper/s2-1",
                    },
                    {
                        "paperId": "s2-2",
                        "title": "No arxiv",
                        "externalIds": {},
                    },
                ]
            }

        client = SemanticScholarClient(api_keys=["k1", "k2"], http_get=fake_get)
        first = client.search("LLM agent", limit=10, since="2026-05-27T00:00:00+00:00")
        second = client.search("AI safety", limit=10)

        self.assertEqual(calls, ["k1", "k2"])
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].arxiv_id, "2605.12345")
        self.assertEqual(second[0].pdf_url, "https://pdf.example/paper.pdf")

    def test_semantic_scholar_sends_user_agent_and_ssl_context_exists(self):
        captured = {}

        def fake_get(url, *, params, headers, timeout):
            captured["headers"] = headers
            return {"data": []}

        SemanticScholarClient(api_keys=["k1"], http_get=fake_get).search("LLM agent")

        self.assertIn("User-Agent", captured["headers"])
        self.assertIsNotNone(ssl_context())

    def test_semantic_scholar_requests_recent_results_sorted_by_publication_date(self):
        captured = {}

        def fake_get(url, *, params, headers, timeout):
            captured["params"] = params
            return {"data": []}

        SemanticScholarClient(api_keys=["k1"], http_get=fake_get).search(
            "AI safety",
            limit=5,
            since="2026-05-27T12:34:00+00:00",
        )

        self.assertEqual(captured["params"]["sort"], "publicationDate:desc")
        self.assertEqual(captured["params"]["publicationDateOrYear"], "2026-05-27:")

    def test_arxiv_client_uses_recent_cs_list_then_abs_pages(self):
        list_html = """
        <dl>
          <dt><span class="list-identifier"><a href="/abs/2606.00001v2">arXiv:2606.00001v2</a></span></dt>
          <dd>
            <div class="list-title mathjax"><span class="descriptor">Title:</span>
              Headless &amp; Simple Crawl
            </div>
            <div class="list-subjects"><span class="descriptor">Subjects:</span>
              Artificial Intelligence (cs.AI); Computation and Language (cs.CL)
            </div>
          </dd>
          <dt><span class="list-identifier"><a href="/abs/2606.00002">arXiv:2606.00002</a></span></dt>
          <dd><div class="list-title mathjax"><span class="descriptor">Title:</span>Another Paper</div></dd>
        </dl>
        """
        abs_html_1 = """
        <meta name="citation_title" content="Full arXiv Abs Title">
        <meta name="citation_date" content="2026/06/04">
        <meta name="citation_author" content="Ada Lovelace">
        <meta name="citation_author" content="Alan Turing">
        <blockquote class="abstract mathjax">
          <span class="descriptor">Abstract:</span>
          Full abstract from arXiv abs page.
        </blockquote>
        <td class="tablecell subjects">
          <span class="primary-subject">Artificial Intelligence</span> subjects: cs.AI; cs.CL
        </td>
        """
        abs_html_2 = """
        <meta name="citation_title" content="Second Abs Title">
        <meta name="citation_date" content="2026/06/03">
        <blockquote class="abstract mathjax"><span class="descriptor">Abstract:</span>Second abstract.</blockquote>
        """
        session = FakeSession(
            {
                "https://arxiv.org/list/cs/recent?skip=0&show=1000": list_html,
                "https://arxiv.org/abs/2606.00001": abs_html_1,
                "https://arxiv.org/abs/2606.00002": abs_html_2,
            }
        )

        results = ArxivClient(client=session).search_recent(["cs.AI", "cs.CL"], since="2026-06-01", limit=1000)

        self.assertEqual(
            session.urls,
            [
                ("https://arxiv.org/list/cs/recent?skip=0&show=1000", 30),
                ("https://arxiv.org/abs/2606.00001", 30),
                ("https://arxiv.org/abs/2606.00002", 30),
            ],
        )
        self.assertEqual([p.arxiv_id for p in results], ["2606.00001", "2606.00002"])
        self.assertEqual(results[0].title, "Full arXiv Abs Title")
        self.assertEqual(results[0].authors, ["Ada Lovelace", "Alan Turing"])
        self.assertEqual(results[0].abstract, "Full abstract from arXiv abs page.")
        self.assertEqual(results[0].published_at, "2026-06-04")
        self.assertEqual(results[0].pdf_url, "https://arxiv.org/pdf/2606.00001.pdf")
        self.assertEqual(results[0].source, "arxiv")

    def test_arxiv_client_keeps_list_metadata_when_abs_page_fails(self):
        class FailingAbsSession(FakeSession):
            def get(self, url: str, *, timeout: int):
                self.urls.append((url, timeout))
                if "/abs/" in url:
                    raise RuntimeError("abs failed")
                return FakeResponse(self.html)

        session = FailingAbsSession(
            '<dt><a href ="/abs/2606.00001">arXiv:2606.00001</a></dt>'
            '<dd><div class="list-title"><span class="descriptor">Title:</span>List Title</div></dd>'
        )

        results = ArxivClient(client=session).search_recent(["cs.AI"], since="2026-06-01", limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].arxiv_id, "2606.00001")
        self.assertEqual(results[0].title, "List Title")
        self.assertEqual(results[0].abstract, "")

    def test_arxiv_recent_keeps_recent_list_papers_regardless_of_since_date(self):
        list_html = '<dt><a href ="/abs/2606.00001">arXiv:2606.00001</a></dt><dd></dd>'
        abs_html = """
        <meta name="citation_title" content="Yesterday Recent Paper">
        <meta name="citation_date" content="2026/06/03">
        <blockquote class="abstract mathjax"><span class="descriptor">Abstract:</span>Still recent.</blockquote>
        """
        session = FakeSession(
            {
                "https://arxiv.org/list/cs/recent?skip=0&show=10": list_html,
                "https://arxiv.org/abs/2606.00001": abs_html,
            }
        )

        results = ArxivClient(client=session).search_recent(["cs.AI"], since="2026-06-04", limit=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].arxiv_id, "2606.00001")
        self.assertEqual(results[0].published_at, "2026-06-03")

    def test_arxiv_client_skips_existing_db_papers_before_abs_fetch(self):
        list_html = """
        <dt><a href ="/abs/2606.00001">arXiv:2606.00001</a></dt>
        <dd><div class="list-title"><span class="descriptor">Title:</span>Existing</div></dd>
        <dt><a href ="/abs/2606.00002">arXiv:2606.00002</a></dt>
        <dd><div class="list-title"><span class="descriptor">Title:</span>New</div></dd>
        """
        abs_html = """
        <meta name="citation_title" content="New Abs Title">
        <meta name="citation_date" content="2026/06/04">
        <blockquote class="abstract mathjax"><span class="descriptor">Abstract:</span>New abstract.</blockquote>
        """
        session = FakeSession(
            {
                "https://arxiv.org/list/cs/recent?skip=0&show=10": list_html,
                "https://arxiv.org/abs/2606.00002": abs_html,
            }
        )

        results = ArxivClient(client=session).search_recent_new_only(
            ["cs.AI"],
            since="2026-06-01",
            limit=10,
            paper_exists=lambda arxiv_id: arxiv_id == "2606.00001",
        )

        self.assertEqual([p.arxiv_id for p in results], ["2606.00002"])
        self.assertEqual(
            session.urls,
            [
                ("https://arxiv.org/list/cs/recent?skip=0&show=10", 30),
                ("https://arxiv.org/abs/2606.00002", 30),
            ],
        )

    def test_arxiv_client_derives_non_cs_archive_from_category_prefix(self):
        session = FakeSession('<dt><a href="/abs/2606.00003">arXiv:2606.00003</a></dt><dd></dd>')

        ArxivClient(client=session).search_recent(["math.CO"], since="2026-06-01", limit=10)

        self.assertEqual(session.urls[0][0], "https://arxiv.org/list/math/recent?skip=0&show=10")

    def test_hybrid_retriever_returns_arxiv_direct_results_without_s2_lookup(self):
        arxiv_paper = PaperMetadata(
            arxiv_id="2605.12345",
            title="arXiv Title",
            categories=["cs.AI"],
            abstract="arXiv abstract",
            pdf_url="https://arxiv.org/pdf/2605.12345.pdf",
            source="arxiv",
        )

        def fake_get(url, *, params, headers, timeout):
            raise AssertionError("Semantic Scholar should not be called for recent arXiv-direct retrieval")

        fake_s2 = SemanticScholarClient(api_keys=["k1"], http_get=fake_get)

        retriever = HybridRetriever(
            s2_client=fake_s2,
            arxiv_search=lambda categories, since, limit: [arxiv_paper],
        )
        results = retriever.search_recent(["LLM agent"], ["cs.AI"], since="2026-05-28", limit=20)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "arXiv Title")
        self.assertEqual(results[0].abstract, "arXiv abstract")
        self.assertEqual(results[0].pdf_url, "https://arxiv.org/pdf/2605.12345.pdf")
        self.assertEqual(results[0].source, "arxiv")

    def test_hybrid_retriever_uses_arxiv_new_only_path_when_db_filter_available(self):
        class FakeArxivClient:
            def __init__(self):
                self.calls = []

            def search_recent(self, categories, *, since, limit):
                raise AssertionError("plain search should not run when paper_exists is available")

            def search_recent_new_only(self, categories, *, since, limit, paper_exists):
                self.calls.append((categories, since, limit, paper_exists("2606.00001")))
                return [PaperMetadata(arxiv_id="2606.00002", title="New", source="arxiv")]

        fake_arxiv = FakeArxivClient()
        retriever = HybridRetriever(
            s2_client=SemanticScholarClient(api_keys=[], http_get=lambda *a, **kw: {}),
            arxiv_search=fake_arxiv.search_recent,
            paper_exists=lambda arxiv_id: arxiv_id == "2606.00001",
        )

        results = retriever.search_recent([], ["cs.AI"], since="2026-06-01", limit=10)

        self.assertEqual([p.arxiv_id for p in results], ["2606.00002"])
        self.assertEqual(fake_arxiv.calls, [(["cs.AI"], "2026-06-01", 10, True)])

    def test_hybrid_retriever_returns_empty_when_arxiv_is_rate_limited(self):
        """When arXiv fails, no papers returned."""
        fake_s2 = SemanticScholarClient(api_keys=["k1"], http_get=lambda *a, **kw: {})

        retriever = HybridRetriever(
            s2_client=fake_s2,
            arxiv_search=lambda categories, since, limit: (_ for _ in ()).throw(RuntimeError("429")),
        )

        merged = retriever.search_recent(["LLM agent"], ["cs.AI"], since="2026-05-27", limit=20)

        self.assertEqual(len(merged), 0)

    def test_pdf_downloader_uses_existing_pdf_url_then_arxiv_fallback(self):
        downloaded = []

        def fake_download(url, dest):
            downloaded.append(url)
            Path(dest).write_bytes(b"%PDF")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = PdfDownloader(http_download=fake_download)
            paper = PaperMetadata(arxiv_id="2605.12345", pdf_url="")
            path = downloader.download(paper, Path(tmp))

        self.assertEqual(downloaded, ["https://arxiv.org/pdf/2605.12345.pdf"])
        self.assertTrue(path.name.endswith(".pdf"))

    def test_pdf_downloader_tries_paperscraper_before_arxiv_url_fallback(self):
        calls = []

        def fake_paperscraper(arxiv_id, dest):
            calls.append(("paperscraper", arxiv_id))
            return False

        def fake_download(url, dest):
            calls.append(("url", url))
            Path(dest).write_bytes(b"%PDF")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = PdfDownloader(http_download=fake_download, paperscraper_download=fake_paperscraper)
            downloader.download(PaperMetadata(arxiv_id="2605.12345", pdf_url=""), Path(tmp))

        self.assertEqual(
            calls,
            [
                ("paperscraper", "2605.12345"),
                ("url", "https://arxiv.org/pdf/2605.12345.pdf"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
