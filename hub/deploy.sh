#!/usr/bin/env bash
# ==============================================================================
# Deploys RISE Board Farm Hub to the Labgrid Controller Host
# ==============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_CMD="$SCRIPT_DIR/../experiment/osu_osl/ssh-osu.sh"

echo "========================================================"
echo " Deploying RISE Board Farm Hub to labgrid controller    "
echo "========================================================"

# 1. Sync code to remote controller
echo "[1/4] Syncing hub code to controller..."
tar -czf - -C "$SCRIPT_DIR" . | "$SSH_CMD" labgrid "mkdir -p ~/board-farm-hub && tar -xzf - -C ~/board-farm-hub"

# 2. Setup Virtualenv & Dependencies on controller
echo "[2/4] Setting up Python virtual environment and dependencies..."
"$SSH_CMD" labgrid "
  if [ ! -d ~/hub_venv ]; then
    python3 -m venv ~/hub_venv
  fi
  ~/hub_venv/bin/pip install --upgrade pip
  ~/hub_venv/bin/pip install -r ~/board-farm-hub/requirements.txt
"

# 3. Install Systemd Service
echo "[3/4] Installing and restarting systemd service..."
"$SSH_CMD" labgrid "
  sudo tee /etc/systemd/system/board-farm-hub.service > /dev/null << 'SVC'
[Unit]
Description=RISE Board Farm Hub (Web Dashboard & Telemetry)
After=network.target labgrid-coordinator.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/board-farm-hub
ExecStart=/home/$USER/hub_venv/bin/python3 hub.py run --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=LG_COORDINATOR=127.0.0.1:20408
Environment=HUB_DB_PATH=/home/$USER/board-farm-hub/hub.db

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
