import unittest

from paper_radar.cli import require_llm_config
from paper_radar.config import AppConfig, LlmConfig


class CliTests(unittest.TestCase):
    def test_requires_llm_config_for_real_runs(self):
        with self.assertRaises(SystemExit):
            require_llm_config(AppConfig(llm=LlmConfig(base_url="https://llm.example/v1", api_key="", model="model")))

    def test_accepts_complete_llm_config(self):
        require_llm_config(AppConfig(llm=LlmConfig(base_url="https://llm.example/v1", api_key="key", model="model")))


if __name__ == "__main__":
    unittest.main()
