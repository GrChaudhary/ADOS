#!/usr/bin/env bash
# Installs the antigravity-awesome-skills collection into this project's
# .claude/skills, scoped to this repo only (not ~/.claude/skills).
# https://github.com/sickn33/antigravity-awesome-skills
#
# .claude/skills/ is gitignored (50MB of vendored third-party content) —
# run this after cloning, or after ADOS/.gitignore's ignore rule.
set -euo pipefail
cd "$(dirname "$0")/.."
npx --yes antigravity-awesome-skills --path .claude/skills
