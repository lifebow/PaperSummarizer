import tempfile
import unittest
from pathlib import Path

from paper_radar.config import FilterSet, load_config
from paper_radar.topics import paper_filter_sets


def _load(yaml_text: str):
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.yaml"
        cfg_path.write_text(yaml_text, encoding="utf-8")
        return load_config(cfg_path, Path(tmp) / "missing.env")


class ConfigFilterSetTests(unittest.TestCase):
    def test_loads_named_filter_sets(self):
        cfg = _load(
            """
topics:
  categories: ["cs.AI", "cs.CV"]
  filters:
    AI Safety:
      - "AI safety"
      - "LLM jailbreak"
    Computer Vision:
      - "object detection"
      - "AI safety"
"""
        )
        self.assertEqual(
            cfg.topics.filters,
            [
                FilterSet("AI Safety", ["AI safety", "LLM jailbreak"]),
                FilterSet("Computer Vision", ["object detection", "AI safety"]),
            ],
        )

    def test_queries_is_deduped_union_preserving_order(self):
        cfg = _load(
            """
topics:
  filters:
    AI Safety:
      - "AI safety"
      - "LLM jailbreak"
    Computer Vision:
      - "object detection"
      - "AI safety"
"""
        )
        self.assertEqual(cfg.topics.queries, ["AI safety", "LLM jailbreak", "object detection"])

    def test_backward_compat_flat_queries_wraps_into_one_set(self):
        cfg = _load(
            """
topics:
  queries:
    - "AI safety"
    - "jailbreak"
"""
        )
        self.assertEqual(cfg.topics.filters, [FilterSet("AI Safety", ["AI safety", "jailbreak"])])
        self.assertEqual(cfg.topics.queries, ["AI safety", "jailbreak"])

    def test_no_topics_yields_empty(self):
        cfg = _load("daemon:\n  interval_minutes: 60\n")
        self.assertEqual(cfg.topics.filters, [])
        self.assertEqual(cfg.topics.queries, [])


class PaperFilterSetsTests(unittest.TestCase):
    def setUp(self):
        self.sets = [
            FilterSet("AI Safety", ["ai safety", "jailbreak"]),
            FilterSet("Computer Vision", ["object detection", "segmentation"]),
        ]

    def _paper(self, **kw):
        return {"title": kw.get("title", ""), "abstract": kw.get("abstract", ""), "summary": kw.get("summary", {})}

    def test_matches_single_set(self):
        paper = self._paper(title="A new jailbreak technique")
        self.assertEqual(paper_filter_sets(paper, self.sets), ["AI Safety"])

    def test_matches_multiple_sets(self):
        paper = self._paper(title="Jailbreak via object detection backdoor")
        self.assertEqual(paper_filter_sets(paper, self.sets), ["AI Safety", "Computer Vision"])

    def test_no_match_returns_empty(self):
        paper = self._paper(title="Quantum error correction")
        self.assertEqual(paper_filter_sets(paper, self.sets), [])


if __name__ == "__main__":
    unittest.main()
