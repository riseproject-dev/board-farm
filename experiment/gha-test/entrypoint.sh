#!/usr/bin/env bash
set -uo pipefail

export RUNNER_ALLOW_RUNASROOT=1

REPO="${GITHUB_REPOSITORY:-riseproject-dev/board-farm}"
TOKEN="${RUNNER_TOKEN:-AR6SMT7VWPUK3YPICPPVKHTKMKAVA}"

echo "========================================================"
echo " GitHub Actions Self-Hosted Runner Container "
echo "========================================================"

if [ -n "$REPO" ] && [ -n "$TOKEN" ] && [ "$TOKEN" != "sample_runner_token" ]; then
    echo "[GHA-Runner] Registering self-hosted runner with GitHub repository: https://github.com/$REPO..."
    if ./config.sh --url "https://github.com/$REPO" --token "$TOKEN" --name "board-farm-qemu-runner" --unattended --replace --labels "self-hosted,board-farm-controller"; then
        echo "[GHA-Runner] Starting runner daemon (listening for GitHub Action jobs)..."
        exec ./run.sh
    else
        echo "[GHA-Runner] Registration failed/expired. Keeping container alive for local execution."
        exec tail -f /dev/null
    fi
else
    echo "[GHA-Runner] No registration token provided (RUNNER_TOKEN)."
    echo "[GHA-Runner] Container is ready for local execution."
    exec tail -f /dev/null
fi
