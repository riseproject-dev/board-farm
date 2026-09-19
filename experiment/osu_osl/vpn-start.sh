#!/usr/bin/env bash
# ==============================================================================
# Starts the isolated Docker OpenVPN client and SOCKS5 proxy
#
# Environment Variables:
#   OSU_VPN_CONFIG   Path to your OpenVPN profile (*.ovpn)
#                    (default: auto-detects client.ovpn or any single *.ovpn in script dir)
# ==============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. Resolve and Validate OpenVPN Configuration
if [ -z "${OSU_VPN_CONFIG:-}" ]; then
    if [ -f "$SCRIPT_DIR/client.ovpn" ]; then
        OSU_VPN_CONFIG="$SCRIPT_DIR/client.ovpn"
    else
        # Look for any .ovpn file in the directory
        shopt -s nullglob
        ovpn_files=("$SCRIPT_DIR"/*.ovpn)
        shopt -u nullglob
        if [ ${#ovpn_files[@]} -eq 1 ]; then
            OSU_VPN_CONFIG="${ovpn_files[0]}"
        elif [ ${#ovpn_files[@]} -gt 1 ]; then
            echo "❌ Error: Multiple .ovpn files found in $SCRIPT_DIR." >&2
            echo "   Please specify which one to use via OSU_VPN_CONFIG:" >&2
            for f in "${ovpn_files[@]}"; do
                echo "     - export OSU_VPN_CONFIG=\"$f\"" >&2
            done
            exit 1
        else
            echo "❌ Error: OpenVPN configuration file not found!" >&2
            echo "   Please set the OSU_VPN_CONFIG environment variable:" >&2
            echo "     export OSU_VPN_CONFIG=/path/to/your/profile.ovpn" >&2
            echo "   Or copy your OpenVPN profile as 'client.ovpn' into:" >&2
            echo "     $SCRIPT_DIR/client.ovpn" >&2
            exit 1
        fi
    fi
fi

if [ ! -f "$OSU_VPN_CONFIG" ]; then
    echo "❌ Error: Configured OSU_VPN_CONFIG='$OSU_VPN_CONFIG' does not exist or is not readable!" >&2
    exit 1
fi

# Convert to absolute path
OSU_VPN_CONFIG="$(cd "$(dirname "$OSU_VPN_CONFIG")" && pwd)/$(basename "$OSU_VPN_CONFIG")"
export OSU_VPN_CONFIG

echo "========================================================"
echo " Starting OSU OSL VPN Client & SOCKS5 Proxy             "
echo "========================================================"
echo "Using OpenVPN profile: $OSU_VPN_CONFIG"

DOCKER_CMD="docker compose"
if ! docker compose version >/dev/null 2>&1; then
    if command -v docker-compose >/dev/null 2>&1; then
        DOCKER_CMD="docker-compose"
    else
        echo "❌ Error: Neither 'docker compose' nor 'docker-compose' found!" >&2
        exit 1
    fi
fi

# Run with docker group if current user cannot access docker daemon directly
if ! docker ps >/dev/null 2>&1 && command -v sg >/dev/null 2>&1; then
    RUNNER="sg docker -c"
else
    RUNNER="eval"
fi

$RUNNER "cd \"$SCRIPT_DIR/vpn\" && OSU_VPN_CONFIG=\"$OSU_VPN_CONFIG\" $DOCKER_CMD up -d"

echo "Waiting for VPN tunnel to establish..."
sleep 3
"$SCRIPT_DIR/vpn-status.sh"
