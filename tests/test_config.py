import os
import tempfile
import unittest
from pathlib import Path

from paper_radar.config import load_config


class ConfigTests(unittest.TestCase):
    def test_loads_yaml_and_semantic_scholar_keys_from_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                "\n".join(
                    [
                        "topics:",
                        '  categories: ["cs.AI"]',
                        "  queries:",
                        '    - "LLM agent"',
                        "daemon:",
                        "  interval_minutes: 60",
                        '  timezone: "Asia/Ho_Chi_Minh"',
                        '  daily_recap_time: "21:00"',
                        "  first_run_lookback_hours: 48",
                        "filters:",
                        "  max_papers_per_batch: 20",
                        "  relevance_threshold: 7",
                        "  grounding_threshold: 7",
                        "  idea_threshold: 6",
                        "paths:",
                        '  database: "data/test.sqlite3"',
                        '  tmp_pdfs: "data/tmp_pdfs"',
                        '  digests: "digests"',
                        "semantic_scholar:",
                        "  enabled: true",
                        '  api_key_env: "SEMANTIC_SCHOLAR_API_KEYS"',
                        "  require_arxiv_external_id: true",
                        "  arxiv_freshness_reconciliation: true",
                        "llm:",
                        '  base_url_env: "OPENAI_BASE_URL"',
                        '  api_key_env: "OPENAI_API_KEY"',
                        '  model_env: "OPENAI_MODEL"',
                        "telegram:",
                        '  bot_token_env: "TELEGRAM_BOT_TOKEN"',
                        '  chat_id_env: "TELEGRAM_CHAT_ID"',
                    ]
                ),
                encoding="utf-8",
            )
            (root / ".env").write_text(
                "SEMANTIC_SCHOLAR_API_KEYS=one, two,,three\n"
                "OPENAI_BASE_URL=https://llm.example/v1\n"
                "OPENAI_API_KEY=secret\n"
                "OPENAI_MODEL=model-a\n"
                "TELEGRAM_BOT_TOKEN=bot\n"
                "TELEGRAM_CHAT_ID=chat\n",
                encoding="utf-8",
            )

            config = load_config(root / "config.yaml", root / ".env")

        self.assertEqual(config.topics.categories, ["cs.AI"])
        self.assertEqual(config.topics.queries, ["LLM agent"])
        self.assertEqual(config.semantic_scholar.api_keys, ["one", "two", "three"])
        self.assertEqual(config.llm.base_url, "https://llm.example/v1")
        self.assertEqual(config.telegram.chat_id, "chat")

    def test_existing_environment_overrides_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                "semantic_scholar:\n"
                '  api_key_env: "SEMANTIC_SCHOLAR_API_KEYS"\n'
                "topics:\n"
                '  categories: ["cs.AI"]\n'
                "  queries: []\n",
                encoding="utf-8",
            )
            (root / ".env").write_text("SEMANTIC_SCHOLAR_API_KEYS=file-key\n", encoding="utf-8")
            old = os.environ.get("SEMANTIC_SCHOLAR_API_KEYS")
            os.environ["SEMANTIC_SCHOLAR_API_KEYS"] = "env-key"
            try:
                config = load_config(root / "config.yaml", root / ".env")
            finally:
                if old is None:
                    os.environ.pop("SEMANTIC_SCHOLAR_API_KEYS", None)
                else:
                    os.environ["SEMANTIC_SCHOLAR_API_KEYS"] = old

        self.assertEqual(config.semantic_scholar.api_keys, ["env-key"])

    def test_daily_recap_times_from_yaml_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                'daemon:\n  daily_recap_times:\n    - "11:00"\n    - "23:00"\n',
                encoding="utf-8",
            )
            (root / ".env").write_text("", encoding="utf-8")
            config = load_config(root / "config.yaml", root / ".env")
        self.assertEqual(config.daemon.daily_recap_times, ["11:00", "23:00"])

    def test_daily_recap_times_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                'daemon:\n  daily_recap_time: "21:00"\n',
                encoding="utf-8",
            )
            (root / ".env").write_text("", encoding="utf-8")
            config = load_config(root / "config.yaml", root / ".env")
        self.assertEqual(config.daemon.daily_recap_times, ["21:00"])

    def test_daily_recap_times_default_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                "daemon:\n  daily_recap_times: []\n",
                encoding="utf-8",
            )
            (root / ".env").write_text("", encoding="utf-8")
            config = load_config(root / "config.yaml", root / ".env")
        self.assertEqual(config.daemon.daily_recap_times, ["11:00", "23:00"])

    def test_daily_recap_times_default_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text("daemon:\n  interval_minutes: 60\n", encoding="utf-8")
            (root / ".env").write_text("", encoding="utf-8")
            config = load_config(root / "config.yaml", root / ".env")
        self.assertEqual(config.daemon.daily_recap_times, ["11:00", "23:00"])

    def test_daily_recap_times_inline_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                'daemon:\n  daily_recap_times: ["09:00", "15:00", "21:00"]\n',
                encoding="utf-8",
            )
            (root / ".env").write_text("", encoding="utf-8")
            config = load_config(root / "config.yaml", root / ".env")
        self.assertEqual(config.daemon.daily_recap_times, ["09:00", "15:00", "21:00"])

    def test_dataclass_default_is_two_slots(self):
        from paper_radar.config import DaemonConfig

        cfg = DaemonConfig()
        self.assertEqual(cfg.daily_recap_times, ["11:00", "23:00"])


if __name__ == "__main__":
    unittest.main()
