import json
import tempfile
import unittest
from pathlib import Path

from paper_radar.digest import append_digest_batch, render_paper_markdown
from paper_radar.llm import LlmClient, _extract_json_object, _ssl_context, passes_quality_gate


class LlmDigestTests(unittest.TestCase):
    def test_llm_client_sends_openai_compatible_payload_and_parses_json(self):
        captured = {}

        def fake_post(url, *, headers, payload, timeout):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = payload
            return {"choices": [{"message": {"content": json.dumps({"relevance_score": 8, "reason": "good"})}}]}

        client = LlmClient(base_url="https://llm.example/v1", api_key="secret", model="model-a", http_post=fake_post)
        result = client.complete_json("system", "user")

        self.assertEqual(result["relevance_score"], 8)
        self.assertEqual(captured["url"], "https://llm.example/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "model-a")
        self.assertIn("Bearer secret", captured["headers"]["Authorization"])
        self.assertIn("User-Agent", captured["headers"])

    def test_quality_gate_requires_all_thresholds(self):
        self.assertTrue(passes_quality_gate({"relevance_score": 7, "grounding_score": 7, "idea_score": 6}))
        self.assertFalse(passes_quality_gate({"relevance_score": 6.9, "grounding_score": 9, "idea_score": 9}))

    def test_extracts_json_from_fenced_model_response(self):
        text = '```json\n{"relevance_score": 8, "reason": "good"}\n```'
        self.assertEqual(_extract_json_object(text)["relevance_score"], 8)

    def test_ssl_context_is_available_for_provider_requests(self):
        self.assertIsNotNone(_ssl_context())

    def test_render_paper_markdown_includes_background_math_and_ideas(self):
        markdown = render_paper_markdown(
            {
                "title": "Agent Safety Paper",
                "arxiv_id": "2605.12345",
                "pdf_url": "https://arxiv.org/pdf/2605.12345.pdf",
                "summary": {
                    "background_needed": "Understand Markov decision processes.",
                    "what_the_paper_does": "Studies agent safety.",
                    "novelty": "New jailbreak benchmark.",
                    "method": "Evaluates tool-use agents.",
                    "math_technical_core": "Defines risk as expected loss.",
                    "results_claims": "Finds failures.",
                    "limitations_uncertainty": "Small model set.",
                    "ideas_to_try": ["Add multi-agent jailbreaks", "Test long-horizon tools"],
                    "qa_scores": {"relevance": 8, "grounding": 8, "idea": 7},
                    "qa_reason": "Strong match.",
                },
            }
        )

        self.assertIn("Background needed", markdown)
        self.assertIn("Math / technical core", markdown)
        self.assertIn("Add multi-agent jailbreaks", markdown)

    def test_appends_daily_digest_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            digest_dir = Path(tmp)
            path = append_digest_batch(
                digest_dir,
                "2026-05-29",
                "15:00",
                [{"title": "Paper", "arxiv_id": "1", "summary": {"ideas_to_try": []}}],
            )

            content = path.read_text(encoding="utf-8")

        self.assertIn("# Paper Radar Digest - 2026-05-29", content)
        self.assertIn("## 15:00 Batch", content)
        self.assertIn("### Paper", content)


if __name__ == "__main__":
    unittest.main()
