# Machine-Enforced Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the machine-enforced harness described in `docs/superpowers/specs/2026-06-04-machine-enforced-harness-design.md`.

**Architecture:** Add a small shell-based verification layer. `scripts/harness.sh` is the source of truth for lint, format-check, unittest, and refactor cadence. `.githooks/pre-push` delegates to the script, while `scripts/install-hooks.sh` installs the versioned hook path.

**Tech Stack:** Bash, Git hooks, GNU/BSD-compatible shell commands, Python `unittest`, Ruff.

---

### Task 1: Failing Harness Tests

**Files:**
- Modify: `tests/test_project_harness.py`

- [ ] **Step 1: Add failing tests for executable harness files**

Add tests that assert these files exist and are executable:

```python
def test_machine_enforced_harness_files_exist_and_are_executable(self):
    for rel in ("scripts/harness.sh", ".githooks/pre-push", "scripts/install-hooks.sh"):
        path = ROOT / rel
        self.assertTrue(path.exists(), f"{rel} missing")
        self.assertTrue(os.access(path, os.X_OK), f"{rel} is not executable")
```

- [ ] **Step 2: Add failing tests for command wiring**

Assert:

```python
def test_machine_enforced_harness_commands_are_wired(self):
    harness = (ROOT / "scripts" / "harness.sh").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    pre_push = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    install_hooks = (ROOT / "scripts" / "install-hooks.sh").read_text(encoding="utf-8")

    self.assertIn("python3 -m ruff check .", harness)
    self.assertIn("python3 -m ruff format --check .", harness)
    self.assertIn("python3 -m unittest discover -v", harness)
    self.assertLess(harness.index("python3 -m ruff check ."), harness.index("python3 -m unittest discover -v"))
    self.assertIn("scripts/harness.sh", makefile)
    self.assertIn("--pre-push", pre_push)
    self.assertIn("core.hooksPath", install_hooks)
    self.assertIn(".githooks", install_hooks)
```

- [ ] **Step 3: Add failing tests for refactor cadence**

Use a temporary Git repository and run:

```python
subprocess.run([str(ROOT / "scripts" / "harness.sh"), "--refactor-check-only"], cwd=temp_repo)
```

Expected behavior:

- 4 `feat:` commits after latest `refactor:` exits `0`.
- 5 `feat:` commits after latest `refactor:` exits non-zero and prints `REFACTOR DUE`.
- a newer `refactor:` commit resets the count and exits `0`.

- [ ] **Step 4: Verify RED**

Run:

```bash
python3 -m unittest tests.test_project_harness -v
```

Expected: fails because `scripts/harness.sh`, `.githooks/pre-push`, `scripts/install-hooks.sh`, and `Makefile` do not exist yet.

### Task 2: Harness Scripts And Hook

**Files:**
- Create: `scripts/harness.sh`
- Create: `scripts/install-hooks.sh`
- Create: `.githooks/pre-push`
- Create: `Makefile`

- [ ] **Step 1: Implement `scripts/harness.sh`**

The script must:

- use `#!/usr/bin/env bash` and `set -euo pipefail`;
- run lint, format-check, and unittest in order;
- support `--pre-push` to run verification and then block on refactor due;
- support `--refactor-check-only` for focused tests;
- define feature commits as subjects starting with `feat:`;
- define refactor commits as subjects starting with `refactor:`;
- block when `feat_count_since_latest_refactor >= 5`.

- [ ] **Step 2: Implement `.githooks/pre-push`**

The hook must find the repository root with:

```bash
repo_root="$(git rev-parse --show-toplevel)"
```

Then execute:

```bash
"${repo_root}/scripts/harness.sh" --pre-push
```

- [ ] **Step 3: Implement `scripts/install-hooks.sh`**

The installer must run:

```bash
git config core.hooksPath .githooks
```

and print the active hook path.

- [ ] **Step 4: Implement `Makefile`**

Add:

```make
.PHONY: verify pre-push install-hooks

verify:
	./scripts/harness.sh

pre-push:
	./scripts/harness.sh --pre-push

install-hooks:
	./scripts/install-hooks.sh
```

- [ ] **Step 5: Mark shell files executable**

Run:

```bash
chmod +x scripts/harness.sh scripts/install-hooks.sh .githooks/pre-push
```

- [ ] **Step 6: Verify GREEN for harness tests**

Run:

```bash
python3 -m unittest tests.test_project_harness -v
```

Expected: all harness tests pass.

### Task 3: Docs And Workflow State

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/development.md`
- Modify: `docs/opencode.md`
- Modify: `docs/workflows/README.md`
- Modify: `docs/workflows/templates/feature-plan.md`
- Modify: `docs/workflows/templates/task-graph.md`
- Modify: `tests/test_project_harness.py`

- [ ] **Step 1: Update docs from pending to implemented**

Docs must point to:

```bash
make verify
scripts/harness.sh
scripts/harness.sh --pre-push
scripts/install-hooks.sh
```

and must no longer say the machine-enforced harness is unimplemented.

- [ ] **Step 2: Remove duplicated OpenCode model mappings from docs**

Docs should state that `opencode.json` is the source of truth instead of copying
the `lint` and `implement` model values.

- [ ] **Step 3: Add drift tests**

Add tests that assert:

- docs do not contain `This feature is not implemented yet`;
- docs do not claim the workspace lacks `.git`;
- `docs/development.md` points to `opencode.json` instead of duplicating stale
  `lint` and `implement` model mappings.

- [ ] **Step 4: Verify docs tests**

Run:

```bash
python3 -m unittest tests.test_project_harness -v
```

Expected: pass.

### Task 4: Full Verification And Commit

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Run canonical harness**

Run:

```bash
scripts/harness.sh
```

Expected: Ruff check passes, Ruff format-check passes, unittest passes.

- [ ] **Step 2: Run pre-push simulation**

Run:

```bash
scripts/harness.sh --pre-push
```

Expected: same verification passes and refactor cadence reports 3 `feat:` commits since the latest `refactor:` commit, below the threshold.

- [ ] **Step 3: Install hooks in this workspace**

Run:

```bash
scripts/install-hooks.sh
git config --get core.hooksPath
```

Expected: `.githooks`.

- [ ] **Step 4: Update `AGENTS.md` verification status**

Record:

- exact commands run,
- pass/fail result,
- unittest count and skipped tests,
- hook path installed,
- refactor cadence count.

- [ ] **Step 5: Run final targeted docs test**

Run:

```bash
python3 -m unittest tests.test_project_harness -v
```

Expected: pass.

- [ ] **Step 6: Commit implementation**

Run:

```bash
git add Makefile scripts/harness.sh scripts/install-hooks.sh .githooks/pre-push tests/test_project_harness.py README.md docs/development.md docs/opencode.md docs/workflows/README.md docs/workflows/templates/feature-plan.md docs/workflows/templates/task-graph.md AGENTS.md docs/superpowers/plans/2026-06-04-machine-enforced-harness-implementation.md
git commit -m "feat: add machine-enforced harness"
```
