#!/usr/bin/env bash
# ==============================================================================
# Runs Phase 2C Non-Destructive Hardware Telemetry Tests via Labgrid SSHDriver
# ==============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BOARD="${1:-a210-board-01}"
REMOTE_TEST_DIR="${REMOTE_TEST_DIR:-phase2_test}"

echo "Running Phase 2C Labgrid test suite on $BOARD..."

"$SCRIPT_DIR/../ssh-osu.sh" labgrid "
  cd \"\$HOME/$REMOTE_TEST_DIR\" 2>/dev/null || cd \"$REMOTE_TEST_DIR\"
  labgrid-client -p '$BOARD' acquire
  /usr/lib64/labgrid/bin/pytest -v -s --lg-env=lab_env.yaml tests/test_a210_telemetry.py
  labgrid-client -p '$BOARD' release
"
