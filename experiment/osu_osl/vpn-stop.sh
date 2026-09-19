#!/usr/bin/env bash
# ==============================================================================
# Stops the OSU OSL VPN client and SOCKS5 proxy container
# ==============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DOCKER_CMD="docker compose"
if ! docker compose version >/dev/null 2>&1; then
    if command -v docker-compose >/dev/null 2>&1; then
        DOCKER_CMD="docker-compose"
    fi
fi

if ! docker ps >/dev/null 2>&1 && command -v sg >/dev/null 2>&1; then
    RUNNER="sg docker -c"
else
    RUNNER="eval"
fi

echo "Stopping OSU OSL VPN container..."
$RUNNER "cd \"$SCRIPT_DIR/vpn\" && $DOCKER_CMD down"
echo "VPN stopped."
