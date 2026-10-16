#!/usr/bin/env bash
# ==============================================================================
# Deploys RISE Board Farm Hub to /opt/board-farm-hub on the Labgrid Controller
# ==============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_CMD="$SCRIPT_DIR/../experiment/osu_osl/ssh-osu.sh"
INSTALL_DIR="${INSTALL_DIR:-/opt/board-farm-hub}"

echo "========================================================"
echo " Deploying RISE Board Farm Hub to $INSTALL_DIR          "
echo "========================================================"

# 1. Prepare /opt/board-farm-hub and sync code to remote controller
echo "[1/4] Preparing $INSTALL_DIR and syncing hub code to controller..."
"$SSH_CMD" labgrid "
  sudo mkdir -p '$INSTALL_DIR'
  sudo chown -R \"\$USER:rise\" '$INSTALL_DIR'
"
tar -czf - -C "$SCRIPT_DIR" . | "$SSH_CMD" labgrid "tar -xzf - -C '$INSTALL_DIR'"

# 2. Setup Virtualenv & Dependencies in /opt/board-farm-hub/venv
echo "[2/4] Setting up Python virtual environment and dependencies..."
"$SSH_CMD" labgrid "
  if [ ! -d '$INSTALL_DIR/venv' ]; then
    python3 -m venv '$INSTALL_DIR/venv'
  fi
  '$INSTALL_DIR/venv/bin/pip' install --upgrade pip
  '$INSTALL_DIR/venv/bin/pip' install -r '$INSTALL_DIR/requirements.txt'
  sudo chown -R \"\$USER:rise\" '$INSTALL_DIR'
"

# 3. Install Systemd Service
echo "[3/4] Installing and restarting systemd service..."
"$SSH_CMD" labgrid "
  sudo tee /etc/systemd/system/board-farm-hub.service > /dev/null << SVC
[Unit]
Description=RISE Board Farm Hub (Web Dashboard & Telemetry)
After=network.target labgrid-coordinator.service

[Service]
Type=simple
User=\$USER
Group=rise
UMask=0002
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 hub.py run --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=LG_COORDINATOR=127.0.0.1:20408
Environment=HUB_DB_PATH=$INSTALL_DIR/hub.db

[Install]
WantedBy=multi-user.target
SVC

  sudo systemctl daemon-reload
  sudo systemctl enable board-farm-hub.service
  sudo systemctl restart board-farm-hub.service
"

# 4. Verify Service Health
echo "[4/4] Verifying service health..."
sleep 3
"$SSH_CMD" labgrid "curl -s http://127.0.0.1:8080/api/v1/health | jq . || curl -s http://127.0.0.1:8080/api/v1/health"

echo "✓ Deployment complete!"
echo "To forward port 8080 to cloudtop:"
echo "  $SCRIPT_DIR/../experiment/osu_osl/ssh-osu.sh labgrid -N -L 8080:127.0.0.1:8080"
