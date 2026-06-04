#!/usr/bin/env bash
set -euo pipefail

REFACTOR_THRESHOLD=5

usage() {
  cat <<'USAGE'
Usage: scripts/harness.sh [--pre-push|--refactor-check-only]

Runs the project verification harness.

Modes:
  default                Run lint, format-check, unittest, and report refactor status.
  --pre-push            Run verification and block if refactor cadence is due.
  --refactor-check-only Check only the git refactor cadence gate.
USAGE
}

section() {
  printf '\n==> %s\n' "$1"
}

run_cmd() {
  section "$1"
  shift
  "$@"
}

repo_root() {
  git rev-parse --show-toplevel
}

latest_refactor_commit() {
  git log --grep='^refactor:' --format='%H' -1 || true
}

feature_count_since_latest_refactor() {
  local latest_refactor
  latest_refactor="$(latest_refactor_commit)"

  if [[ -n "$latest_refactor" ]]; then
    git log "${latest_refactor}..HEAD" --grep='^feat:' --format='%H' | wc -l | tr -d '[:space:]'
  else
    git log --grep='^feat:' --format='%H' | wc -l | tr -d '[:space:]'
  fi
}

check_refactor_cadence() {
  local block_when_due="$1"
  local count
  count="$(feature_count_since_latest_refactor)"

  if (( count >= REFACTOR_THRESHOLD )); then
    cat <<MESSAGE
REFACTOR DUE: ${count} feature commits since last refactor.
Create and pass a refactor checkpoint commit before pushing more feature work.
MESSAGE
    if [[ "$block_when_due" == "true" ]]; then
      return 1
    fi
    return 0
  fi

  printf 'Refactor cadence OK: %s feature commits since last refactor (threshold: %s).\n' \
    "$count" "$REFACTOR_THRESHOLD"
}

run_verification() {
  run_cmd "ruff check" python3 -m ruff check .
  run_cmd "ruff format check" python3 -m ruff format --check .
  run_cmd "unittest regression" python3 -m unittest discover -v
}

mode="default"
if [[ $# -gt 0 ]]; then
  mode="$1"
  shift
fi

if [[ $# -gt 0 ]]; then
  usage >&2
  exit 2
fi

case "$mode" in
  default)
    cd "$(repo_root)"
    run_verification
    section "refactor cadence"
    check_refactor_cadence false
    ;;
  --pre-push)
    cd "$(repo_root)"
    run_verification
    section "refactor cadence"
    check_refactor_cadence true
    ;;
  --refactor-check-only)
    cd "$(repo_root)"
    check_refactor_cadence true
    ;;
  --help|-h)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
