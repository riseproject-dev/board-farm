#!/usr/bin/env bash
# ==============================================================================
# OSU OSL Hardware Access SSH Wrapper
#
# Provides seamless, proxy-aware SSH access to the OSU OSL labgrid controller
# and Zhihe A210 target boards over the SOCKS5 VPN proxy.
#
# Environment Variables:
#   OSU_SSH_USER     SSH username for the labgrid controller host
#                    (default: $USER)
#   OSU_SSH_KEY      Path to the private SSH key
#                    (default: auto-detect ~/.ssh/id_ed25519, ~/.ssh/id_rsa,
#                              or ~/.ssh/github_ed25519)
#   OSU_SOCKS5_PROXY SOCKS5 proxy host:port
#                    (default: 127.0.0.1:1080, set to "none" or "" for direct)
#
# Usage:
#   ./ssh-osu.sh labgrid               # Interactive shell on controller host
#   ./ssh-osu.sh a210-1 [command...]   # SSH to a210 board 01 (10.6.4.12)
#   ./ssh-osu.sh a210-5 [command...]   # SSH to a210 board 05 (10.6.4.16)
#   ./ssh-osu.sh 10.6.4.16 [cmd...]    # Direct IP target
# ==============================================================================
set -euo pipefail

# 1. Determine SSH User
OSU_SSH_USER="${OSU_SSH_USER:-${USER:-}}"
if [ -z "$OSU_SSH_USER" ]; then
    echo "❌ Error: OSU_SSH_USER is not set and USER environment variable is empty." >&2
    echo "   Please set OSU_SSH_USER to your OSU OSL username (e.g., export OSU_SSH_USER=myuser)." >&2
    exit 1
fi

# 2. Determine SSH Key
OSU_SSH_KEY="${OSU_SSH_KEY:-}"
if [ -z "$OSU_SSH_KEY" ]; then
    for candidate in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_rsa" "$HOME/.ssh/github_ed25519"; do
        if [ -f "$candidate" ]; then
            OSU_SSH_KEY="$candidate"
            break
        fi
    done
fi

if [ -z "$OSU_SSH_KEY" ] || [ ! -f "$OSU_SSH_KEY" ]; then
    echo "❌ Error: SSH private key not found!" >&2
    echo "   Checked default locations: ~/.ssh/id_ed25519, ~/.ssh/id_rsa, ~/.ssh/github_ed25519" >&2
    echo "   Please specify your private key: export OSU_SSH_KEY=/path/to/private_key" >&2
    exit 1
fi

# 3. Determine Proxy Configuration
OSU_SOCKS5_PROXY="${OSU_SOCKS5_PROXY:-127.0.0.1:1080}"
SSH_PROXY_ARGS=()

if [ -n "$OSU_SOCKS5_PROXY" ] && [ "$OSU_SOCKS5_PROXY" != "none" ] && [ "$OSU_SOCKS5_PROXY" != "direct" ]; then
    PROXY_HOST="${OSU_SOCKS5_PROXY%:*}"
    PROXY_PORT="${OSU_SOCKS5_PROXY##*:}"
    
    # Check if proxy is reachable
    if command -v nc >/dev/null 2>&1; then
        if ! nc -z -w 1 "$PROXY_HOST" "$PROXY_PORT" >/dev/null 2>&1; then
            echo "⚠️  Warning: SOCKS5 proxy at $OSU_SOCKS5_PROXY is not reachable." >&2
            echo "   Did you start the VPN container? Run ./vpn-start.sh" >&2
            echo "   If you have a direct VPN connection, set: export OSU_SOCKS5_PROXY=none" >&2
        fi
    fi
    SSH_PROXY_ARGS=(-o "ProxyCommand=nc -X 5 -x ${OSU_SOCKS5_PROXY} %h %p")
fi

# 4. Resolve Target Host and Remote User
TARGET="${1:-labgrid}"
shift || true

REMOTE_USER=""
REMOTE_HOST=""

case "$TARGET" in
    labgrid)
        REMOTE_USER="$OSU_SSH_USER"
        REMOTE_HOST="10.6.4.11"
        ;;
    a210-1|a210-board-01)
        REMOTE_USER="root"
        REMOTE_HOST="10.6.4.12"
        ;;
    a210-2|a210-board-02)
        REMOTE_USER="root"
        REMOTE_HOST="10.6.4.13"
        ;;
    a210-3|a210-board-03)
        REMOTE_USER="root"
        REMOTE_HOST="10.6.4.14"
        ;;
    a210-4|a210-board-04)
        REMOTE_USER="root"
        REMOTE_HOST="10.6.4.15"
        ;;
    a210-5|a210-board-05)
        REMOTE_USER="root"
        REMOTE_HOST="10.6.4.16"
        ;;
    *@*)
        REMOTE_USER="${TARGET%@*}"
        REMOTE_HOST="${TARGET##*@}"
        ;;
    10.6.4.*)
        REMOTE_USER="root"
        REMOTE_HOST="$TARGET"
        ;;
    *)
        echo "Usage: $0 {labgrid|a210-1|a210-2|a210-3|a210-4|a210-5|<ip>} [remote command...]" >&2
        exit 1
        ;;
esac

exec ssh -o StrictHostKeyChecking=accept-new \
         -o UserKnownHostsFile=/dev/null \
         -o LogLevel=ERROR \
         -i "$OSU_SSH_KEY" \
         "${SSH_PROXY_ARGS[@]}" \
         "${REMOTE_USER}@${REMOTE_HOST}" "$@"
