#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git config core.hooksPath .githooks
printf 'Installed git hooks path: %s\n' "$(git config --get core.hooksPath)"
