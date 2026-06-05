import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProjectHarnessTests(unittest.TestCase):
    def _git(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-c", "user.name=Harness Test", "-c", "user.email=harness@example.test", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )

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
        harness = (ROOT / "scripts" / "harness.sh").read_text(encoding="utf-8")

        self.assertIn("paper-radar", readme)
        self.assertIn("make verify", readme)
        self.assertIn("scripts/harness.sh --pre-push", readme)
        self.assertIn("make verify", development)
        self.assertIn("scripts/install-hooks.sh", development)
        self.assertIn("python3 -m ruff check .", harness)
        self.assertIn("python3 -m ruff format --check .", harness)
        self.assertIn("python3 -m unittest discover -v", harness)
        self.assertIn("No real network calls", development)
        self.assertIn("Harness Verification Record", development)
        self.assertIn("OpenCode State And Sandbox", development)

    def test_machine_enforced_harness_files_exist_and_are_executable(self):
        for rel in ("scripts/harness.sh", ".githooks/pre-push", "scripts/install-hooks.sh"):
            path = ROOT / rel
            self.assertTrue(path.exists(), f"{rel} missing")
            self.assertTrue(os.access(path, os.X_OK), f"{rel} is not executable")

    def test_machine_enforced_harness_commands_are_wired(self):
        harness_path = ROOT / "scripts" / "harness.sh"
        makefile_path = ROOT / "Makefile"
        pre_push_path = ROOT / ".githooks" / "pre-push"
        install_hooks_path = ROOT / "scripts" / "install-hooks.sh"
        for path in (harness_path, makefile_path, pre_push_path, install_hooks_path):
            self.assertTrue(path.exists(), f"{path.relative_to(ROOT)} missing")

        harness = harness_path.read_text(encoding="utf-8")
        makefile = makefile_path.read_text(encoding="utf-8")
        pre_push = pre_push_path.read_text(encoding="utf-8")
        install_hooks = install_hooks_path.read_text(encoding="utf-8")

        self.assertIn("python3 -m ruff check .", harness)
        self.assertIn("python3 -m ruff format --check .", harness)
        self.assertIn("python3 -m unittest discover -v", harness)
        self.assertLess(harness.index("python3 -m ruff check ."), harness.index("python3 -m unittest discover -v"))
        self.assertIn("scripts/harness.sh", makefile)
        self.assertIn("--pre-push", pre_push)
        self.assertIn("core.hooksPath", install_hooks)
        self.assertIn(".githooks", install_hooks)

    def test_refactor_cadence_gate_blocks_after_five_features(self):
        harness = ROOT / "scripts" / "harness.sh"
        self.assertTrue(harness.exists(), "scripts/harness.sh missing")

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git(repo, "init", "-q")
            self._git(repo, "commit", "--allow-empty", "-m", "refactor: checkpoint")

            for i in range(4):
                self._git(repo, "commit", "--allow-empty", "-m", f"feat: feature {i + 1}")

            ok = subprocess.run(
                [str(harness), "--refactor-check-only"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("4 feature commits", ok.stdout)

            self._git(repo, "commit", "--allow-empty", "-m", "feat: feature 5")
            due = subprocess.run(
                [str(harness), "--refactor-check-only"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(due.returncode, 0)
            self.assertIn("REFACTOR DUE", due.stdout + due.stderr)

            self._git(repo, "commit", "--allow-empty", "-m", "refactor: cleanup checkpoint")
            reset = subprocess.run(
                [str(harness), "--refactor-check-only"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(reset.returncode, 0, reset.stdout + reset.stderr)
            self.assertIn("0 feature commits", reset.stdout)

    def test_docs_describe_implemented_machine_enforced_harness(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        opencode = (ROOT / "docs" / "opencode.md").read_text(encoding="utf-8")
        development = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")

        combined = "\n".join([agents, opencode, development])
        self.assertIn("scripts/harness.sh", combined)
        self.assertIn("make verify", combined)
        self.assertNotIn("This feature is not implemented yet", combined)
        self.assertNotIn("currently known to lack `.git`", combined)
        self.assertNotIn("`lint`: `opencode/deepseek-v4-flash-free`", development)
        self.assertNotIn("`implement`: `acbpro/glm-5.1`", development)

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

    def test_opencode_debate_agents_carry_debate_protocol(self):
        config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
        agents = config["agent"]

        coordinator_prompt = agents["coordinator"]["prompt"]
        self.assertIn("ask the user to choose debate panel models", coordinator_prompt)
        self.assertIn("spawn each selected @debate-* panelist independently", coordinator_prompt)
        self.assertIn("stop until the user approves", coordinator_prompt)

        panelist_names = [
            "debate-deepseek",
            "debate-mimo",
            "debate-nemotron",
            "debate-glm",
            "debate-gpt55",
        ]
        required_sections = [
            "Recommendation",
            "Main argument",
            "Risks",
            "Testability",
            "Simplicity and reuse",
            "Refactor impact",
            "Deployment impact",
            "What would change my mind",
        ]
        for name in panelist_names:
            prompt = agents[name].get("prompt", "")
            self.assertIn("independent debate panelist", prompt, name)
            self.assertIn("Do not rely on", prompt, name)
            self.assertIn("Do not edit files", prompt, name)
            self.assertIn("do not run commands", prompt, name)
            for section in required_sections:
                self.assertIn(section, prompt, name)

        judge_prompt = agents["debate-judge"].get("prompt", "")
        self.assertIn("final debate judge", judge_prompt)
        self.assertIn("identify agreements and conflicts", judge_prompt)
        self.assertIn("summarize each model's strongest point", judge_prompt)
        self.assertIn("list rejected alternatives", judge_prompt)
        self.assertIn("follow-up tests or experiments", judge_prompt)
        self.assertIn("Do not invent evidence", judge_prompt)
        self.assertIn("requires user approval", judge_prompt)

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
        self.assertIn("scripts/harness.sh", feature_plan)
        self.assertIn("scripts/harness.sh --pre-push", feature_plan)
        verify_index = feature_plan.index("scripts/harness.sh")
        pre_push_index = feature_plan.index("scripts/harness.sh --pre-push")
        self.assertLess(verify_index, pre_push_index)

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
        self.assertIn("scripts/harness.sh", test_matrix)
        self.assertIn("scripts/harness.sh --pre-push", test_matrix)

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
