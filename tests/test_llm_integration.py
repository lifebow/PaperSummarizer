import os
import unittest

from paper_radar.llm import (
    LlmClient,
    build_qa_prompt,
    build_relevance_prompt,
    build_summary_prompt,
    passes_quality_gate,
)


def requires_llm_api(func):
    def wrapper(*args, **kwargs):
        base_url = os.environ.get("OPENAI_BASE_URL", "")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = os.environ.get("OPENAI_MODEL", "")
        if not all([base_url, api_key, model]):
            raise unittest.SkipTest("OPENAI_BASE_URL, OPENAI_API_KEY, or OPENAI_MODEL not set")
        return func(*args, **kwargs)

    return wrapper


@requires_llm_api
class LlmIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = LlmClient(
            base_url=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ["OPENAI_MODEL"],
        )

    def test_relevance_prompt_returns_valid_json(self):
        system, user = build_relevance_prompt(
            title="Attention Is All You Need",
            abstract="We propose the Transformer, a new architecture for sequence transduction.",
            topics=["deep learning", "transformers", "NLP"],
        )
        result = self.client.complete_json(system, user)

        self.assertIsInstance(result, dict)
        self.assertIn("relevance_score", result)
        self.assertIn("reason", result)
        self.assertGreaterEqual(float(result["relevance_score"]), 0)
        self.assertLessEqual(float(result["relevance_score"]), 10)

    def test_summary_prompt_returns_valid_json(self):
        system, user = build_summary_prompt(
            title="Attention Is All You Need",
            abstract="We propose the Transformer, a new architecture for sequence transduction.",
            full_text_markdown="The dominant sequence transduction models are based on complex recurrent...",
        )
        result = self.client.complete_json(system, user)

        self.assertIsInstance(result, dict)
        self.assertIn("background_needed", result)
        self.assertIn("what_the_paper_does", result)
        self.assertIn("novelty", result)
        self.assertIn("method", result)
        self.assertIn("ideas_to_try", result)
        self.assertIsInstance(result["ideas_to_try"], list)

    def test_qa_prompt_returns_valid_json(self):
        summary = {
            "background_needed": "Understanding of transformers",
            "what_the_paper_does": "Proposes new architecture",
            "novelty": "Self-attention mechanism",
            "method": "Multi-head attention",
            "ideas_to_try": ["Apply to vision"],
        }
        system, user = build_qa_prompt(
            summary=summary,
            abstract="We propose the Transformer, a new architecture for sequence transduction.",
            full_text_markdown="The dominant sequence transduction models are based on complex recurrent...",
        )
        result = self.client.complete_json(system, user)

        self.assertIsInstance(result, dict)
        self.assertIn("relevance_score", result)
        self.assertIn("grounding_score", result)
        self.assertIn("idea_score", result)
        self.assertIn("qa_reason", result)

        self.assertTrue(passes_quality_gate(result))

    def test_full_pipeline_relevance_then_summary_then_qa(self):
        title = "BERT: Pre-training of Deep Bidirectional Transformers"
        abstract = "We introduce a new language representation model called BERT."
        topics = ["NLP", "transformers", "pre-training"]

        relevance_system, relevance_user = build_relevance_prompt(title, abstract, topics)
        relevance_result = self.client.complete_json(relevance_system, relevance_user)
        self.assertIn("relevance_score", relevance_result)

        summary_system, summary_user = build_summary_prompt(title, abstract, "")
        summary_result = self.client.complete_json(summary_system, summary_user)
        self.assertIn("ideas_to_try", summary_result)

        qa_system, qa_user = build_qa_prompt(summary_result, abstract, "")
        qa_result = self.client.complete_json(qa_system, qa_user)
        self.assertIn("relevance_score", qa_result)

        self.assertIsInstance(qa_result["relevance_score"], (int, float, str))
        self.assertIsInstance(qa_result["grounding_score"], (int, float, str))
        self.assertIsInstance(qa_result["idea_score"], (int, float, str))


if __name__ == "__main__":
    unittest.main()
