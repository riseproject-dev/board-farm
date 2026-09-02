#!/usr/bin/env bash
# Gateway & Network Setup Script for Local Phase 1 Experiment (Docker + dnsmasq)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TFTP_DIR="/tmp/tftp/qemu-board"
CONTAINER_NAME="lab-gateway"
INTERFACE="${GATEWAY_IFACE:-lo}"

echo "Creating TFTP directory structure at $TFTP_DIR..."
mkdir -p "$TFTP_DIR"
chmod -R 777 /tmp/tftp

stop_gateway() {
    if command -v docker >/dev/null 2>&1; then
        if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
            echo "Stopping and removing existing Docker gateway container (${CONTAINER_NAME})..."
            docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
        fi
    fi
}

if [ "${1:-start}" = "stop" ]; then
    stop_gateway
    exit 0
fi

stop_gateway

echo "Starting Docker dnsmasq container (DHCP + TFTP server)..."
if docker run -d --name "$CONTAINER_NAME" \
    --net=host \
    --cap-add=NET_ADMIN \
    -v /tmp/tftp:/srv/tftp \
    strm/dnsmasq \
    --interface="$INTERFACE" \
    --bind-interfaces \
    --dhcp-range=192.168.100.50,192.168.100.100,12h \
    --enable-tftp \
    --tftp-root=/srv/tftp >/dev/null 2>&1; then

    echo "Waiting for Docker dnsmasq gateway readiness..."
    READY=0
    for i in $(seq 1 10); do
        if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null)" = "true" ]; then
            READY=1
            break
        fi
        sleep 0.5
    done

    if [ "$READY" -eq 1 ]; then
        echo "✓ Docker dnsmasq gateway container is running and serving /tmp/tftp."
    else
        echo "⚠️ Docker dnsmasq container started but state check timed out."
    fi
else
    echo "⚠️ Docker dnsmasq failed to start (e.g. missing sudo/permissions)."
    echo "Falling back to local Python TFTP server..."
    python3 "$SCRIPT_DIR/tftp_server.py" --port 6969 --root /tmp/tftp &
    echo $! > /tmp/tftp-server.pid
fi
