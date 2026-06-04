import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProjectHarnessTests(unittest.TestCase):
    def test_pyproject_declares_ruff_harness(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("[project.optional-dependencies]", text)
        self.assertIn("ruff>=0.8", text)
        self.assertIn("[tool.ruff]", text)
        self.assertIn('target-version = "py310"', text)
        self.assertIn("[tool.ruff.lint]", text)

    def test_project_docs_describe_common_commands(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        development = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")

        self.assertIn("paper-radar", readme)
        self.assertIn("python3 -m unittest discover -v", readme)
        self.assertIn("python3 -m ruff check .", development)
        self.assertIn("python3 -m ruff format --check .", development)
        self.assertIn("No real network calls", development)
        self.assertIn("Harness Verification Record", development)
        self.assertIn("OpenCode State And Sandbox", development)

    def test_opencode_entrypoint_loads_workflow_docs(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))

        self.assertIn("OpenCode Start Here", agents)
        self.assertIn("OpenCode reads this `AGENTS.md` file first", agents)
        self.assertIn("docs/opencode.md", agents)
        self.assertEqual(config["$schema"], "https://opencode.ai/config.json")
        self.assertIn("docs/opencode.md", config["instructions"])
        self.assertIn("docs/workflows/README.md", config["instructions"])
        self.assertIn("docs/workflows/templates/*.md", config["instructions"])

    def test_opencode_docs_define_autonomous_subagent_workflow(self):
        opencode = (ROOT / "docs" / "opencode.md").read_text(encoding="utf-8")

        self.assertIn("Autonomous Subagent Execution Gate", opencode)
        self.assertIn("coordinator must not run mechanical checks directly", opencode)
        self.assertIn("User Model Selection Gate", opencode)
        self.assertIn("USER_CHOSEN_MODEL", opencode)
        self.assertIn("USER_CHOSEN_JUDGE_MODEL", opencode)
        self.assertIn("opencode", opencode)
        self.assertIn("runner: subagent", opencode)
        self.assertIn("runner: opencode", opencode)
        self.assertIn("Subagent Proof Levels", opencode)
        self.assertIn("config resolve", opencode)
        self.assertIn("runner execution", opencode)
        self.assertIn("model-backed OpenCode execution", opencode)
        self.assertIn("~/.local/share/opencode", opencode)

    def test_env_example_documents_secret_groups_and_skip_behavior(self):
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("# Semantic Scholar integration", env_example)
        self.assertIn("# OpenAI-compatible LLM integration", env_example)
        self.assertIn("# Telegram recap integration", env_example)
        self.assertIn("# Missing integration secrets should skip integration tests", env_example)

    def test_workflow_templates_encode_quality_gates(self):
        feature_plan = (ROOT / "docs" / "workflows" / "templates" / "feature-plan.md").read_text(encoding="utf-8")
        debate_brief = (ROOT / "docs" / "workflows" / "templates" / "debate-brief.md").read_text(encoding="utf-8")
        test_matrix = (ROOT / "docs" / "workflows" / "templates" / "test-matrix.md").read_text(encoding="utf-8")

        self.assertIn("Lint Before Test Gate", feature_plan)
        self.assertIn("Regression Gate", feature_plan)
        self.assertIn("Commit Before Refactor Gate", feature_plan)
        self.assertIn("Refactor Cadence Gate", feature_plan)
        self.assertIn("Feature Test Matrix", feature_plan)
        self.assertIn("Docker Deploy Smoke Gate", feature_plan)
        self.assertIn("Autonomous Subagent Execution Gate", feature_plan)
        lint_index = feature_plan.index("python3 -m ruff check .")
        test_index = feature_plan.index("python3 -m unittest discover -v")
        self.assertLess(lint_index, test_index)

        self.assertIn("User Model Selection Gate", debate_brief)
        self.assertIn("USER_CHOSEN_MODEL", debate_brief)
        self.assertIn("USER_CHOSEN_JUDGE_MODEL", debate_brief)
        self.assertIn("Independent Arguments", debate_brief)
        self.assertIn("Final Judge", debate_brief)
        self.assertIn("User Approval Gate", debate_brief)

        self.assertIn("Happy path", test_matrix)
        self.assertIn("Niche/domain cases", test_matrix)
        self.assertIn("Invalid input", test_matrix)
        self.assertIn("Failure/retry behavior", test_matrix)
        self.assertIn("Backward compatibility", test_matrix)
        self.assertIn("Refactor safety", test_matrix)

    def test_integration_test_files_exist(self):
        test_dir = ROOT / "tests"
        integration_files = list(test_dir.glob("test_*_integration.py"))
        self.assertGreater(len(integration_files), 0, "No integration test files found")

        for f in integration_files:
            content = f.read_text(encoding="utf-8")
            has_api_check = "requires_s2_api" in content or "requires_llm_api" in content
            self.assertTrue(has_api_check, f"{f.name} missing API key check decorator")
            has_skip = "SkipTest" in content or "unittest.skip" in content
            self.assertTrue(has_skip, f"{f.name} missing skip mechanism")


if __name__ == "__main__":
    unittest.main()
