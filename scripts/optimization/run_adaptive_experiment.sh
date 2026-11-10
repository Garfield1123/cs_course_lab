#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Deliberately analyze the existing sweep; never launch duplicate baseline queries.
exec python3 "$repo_root/optimization/experiment.py" analyze "$@"
