import unittest

from paper_radar.topics import OTHER_TOPIC, tag_paper, topic_slug


class TopicSlugTests(unittest.TestCase):
    def test_lowercases_and_hyphenates(self):
        self.assertEqual(topic_slug("Prompt Injection"), "prompt-injection")

    def test_collapses_non_alphanumeric(self):
        self.assertEqual(topic_slug("AI safety / alignment"), "ai-safety-alignment")

    def test_strips_leading_trailing_separators(self):
        self.assertEqual(topic_slug("  LLM jailbreak!  "), "llm-jailbreak")


class TagPaperTests(unittest.TestCase):
    def _paper(self, *, title="", abstract="", summary=None):
        return {"title": title, "abstract": abstract, "summary": summary or {}}

    def test_matches_query_phrase_in_title(self):
        paper = self._paper(title="A study of prompt injection attacks")
        self.assertEqual(tag_paper(paper, ["prompt injection", "red teaming"]), ["prompt injection"])

    def test_match_is_case_insensitive(self):
        paper = self._paper(title="Advances in AI Safety")
        self.assertEqual(tag_paper(paper, ["ai safety"]), ["ai safety"])

    def test_matches_query_in_abstract(self):
        paper = self._paper(abstract="We propose a new jailbreak attack on aligned models.")
        self.assertEqual(tag_paper(paper, ["jailbreak attack"]), ["jailbreak attack"])

    def test_matches_query_in_summary_text(self):
        paper = self._paper(summary={"what_the_paper_does": "Improves safety guardrails for chatbots."})
        self.assertEqual(tag_paper(paper, ["safety guardrails"]), ["safety guardrails"])

    def test_returns_all_matching_queries_in_query_order(self):
        paper = self._paper(
            title="Red teaming prompt injection",
            abstract="defends against jailbreak attack",
        )
        result = tag_paper(paper, ["jailbreak attack", "prompt injection", "red teaming"])
        self.assertEqual(result, ["jailbreak attack", "prompt injection", "red teaming"])

    def test_no_match_returns_other_bucket(self):
        paper = self._paper(title="Quantum error correction", abstract="topological codes")
        self.assertEqual(tag_paper(paper, ["ai safety", "jailbreak"]), [OTHER_TOPIC])

    def test_summary_list_values_are_searched(self):
        paper = self._paper(summary={"ideas_to_try": ["explore constitutional AI variants"]})
        self.assertEqual(tag_paper(paper, ["constitutional AI"]), ["constitutional AI"])


if __name__ == "__main__":
    unittest.main()
