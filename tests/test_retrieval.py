import tempfile
import unittest
from pathlib import Path

from paper_radar._http import ssl_context
from paper_radar.retrieval import HybridRetriever, PaperMetadata, PdfDownloader, SemanticScholarClient


class RetrievalTests(unittest.TestCase):
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

    def test_hybrid_retriever_merges_by_arxiv_id_and_prefers_arxiv_dates(self):
        s2_paper = PaperMetadata(
            arxiv_id="2605.12345",
            semantic_scholar_id="s2-1",
            title="S2 Title",
            abstract="S2 abstract",
            published_at="2026-05-28",
            pdf_url="https://pdf.example/s2.pdf",
            semantic_scholar_tldr="short",
            source="semantic_scholar",
        )
        arxiv_paper = PaperMetadata(
            arxiv_id="2605.12345",
            title="arXiv Title",
            abstract="arxiv abstract",
            categories=["cs.AI"],
            published_at="2026-05-29",
            updated_at="2026-05-29",
            pdf_url="https://arxiv.org/pdf/2605.12345.pdf",
            source="arxiv",
        )

        retriever = HybridRetriever(
            semantic_scholar_search=lambda queries, limit, since=None: [s2_paper],
            arxiv_search=lambda categories, since, limit: [arxiv_paper],
        )
        merged = retriever.search_recent(["LLM agent"], ["cs.AI"], since="2026-05-28", limit=20)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "arXiv Title")
        self.assertEqual(merged[0].semantic_scholar_id, "s2-1")
        self.assertEqual(merged[0].semantic_scholar_tldr, "short")

    def test_hybrid_retriever_returns_semantic_scholar_results_when_arxiv_is_rate_limited(self):
        s2_paper = PaperMetadata(arxiv_id="2605.12345", title="S2 Paper", source="semantic_scholar")

        retriever = HybridRetriever(
            semantic_scholar_search=lambda queries, limit, since=None: [s2_paper],
            arxiv_search=lambda categories, since, limit: (_ for _ in ()).throw(RuntimeError("429")),
        )

        merged = retriever.search_recent(["LLM agent"], ["cs.AI"], since="2026-05-27", limit=20)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "S2 Paper")

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
