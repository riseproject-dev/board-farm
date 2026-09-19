#!/usr/bin/env bash
# ==============================================================================
# Checks the health and connectivity of the OSU OSL VPN container
# ==============================================================================
set -euo pipefail

CONTAINER_NAME="osu-vpn"

if ! docker ps >/dev/null 2>&1 && command -v sg >/dev/null 2>&1; then
    RUNNER="sg docker -c"
else
    RUNNER="eval"
fi

if ! $RUNNER "docker ps --filter name=$CONTAINER_NAME --filter status=running -q" | grep -q .; then
    echo "❌ OSU OSL VPN container is NOT running."
    echo "   Start it with: ./vpn-start.sh"
    exit 1
fi

echo "✓ OSU OSL VPN container is running."
VPN_IP=$($RUNNER "docker exec $CONTAINER_NAME ip -4 addr show dev tun0" | awk '/inet / {print $2}' | cut -d/ -f1)
echo "  - Tunnel IP       : $VPN_IP"
echo "  - SOCKS5 Proxy    : 127.0.0.1:1080"

echo -n "  - VPN Gateway (10.0.0.1)  : "
if $RUNNER "docker exec $CONTAINER_NAME ping -c 1 -W 2 10.0.0.1" >/dev/null 2>&1; then
    echo "OK (Reachable)"
else
    echo "FAILED"
fi

echo -n "  - Labgrid Host (10.6.4.11): "
if $RUNNER "docker exec $CONTAINER_NAME nc -zv -w 2 10.6.4.11 22" >/dev/null 2>&1; then
    echo "OK (SSH port 22 open)"
else
    echo "FAILED"
fi

for i in 1 2 3 4 5; do
    IP="10.6.4.$((11 + i))"
    echo -n "  - Target A210-$i ($IP): "
    if $RUNNER "docker exec $CONTAINER_NAME nc -zv -w 2 $IP 22" >/dev/null 2>&1; then
        echo "OK (SSH port 22 open)"
    else
        echo "UNREACHABLE"
    fi
done
