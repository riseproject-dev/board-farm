# GitHub Actions Self-Hosted Runner & Workflow Setup Guide

This guide documents the architecture, installation, configuration, operational management, and GitHub Actions workflow deployment for running automated Labgrid hardware tests at Oregon State University Open Source Lab (OSU OSL).

---

## 1. System Architecture

```text
               GitHub Actions Cloud (github.com)
                           │
                           │  HTTPS Outbound Long-Polling (Port 443)
                           ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ OSU OSL Controller Host: labgrid.bak.milne.osuosl.org (10.6.4.11)      │
 │                                                                        │
 │  Docker Container: `gha-runner`                                        │
 │    ├── GitHub Actions Runner Daemon (actions-runner v2.337+)           │
 │    ├── Runner Labels: [self-hosted, board-farm-controller, a210]       │
 │    ├── Networking: --net host (native rack IP access)                  │
 │    ├── Tooling: Python 3.12, Labgrid 26.0, Pytest 9.1                  │
 │    └── Mounted Credentials: $HOME/.ssh/id_ed25519 (read-only) │
 │                                                                        │
 │  Native Systemd Services:                                              │
 │    ├── labgrid-coordinator.service (Port 20408)                        │
 │    └── labgrid-exporter.service (NetworkService / root SSH)            │
 └─────────────────┬──────────────────────────────────────────────────────┘
                   │
                   │ Local Hardware Subnet (10.6.4.0/24)
                   │
                   ├──> a210-1 (10.6.4.12) - Place: a210-board-01
                   └──> a210-2 (10.6.4.13) - Place: a210-board-02
```

### Why Host Directly on the Controller with `--net host`?
1. **Zero Latency & No Tunnels**: The runner communicates with `labgrid-coordinator` via `ws://127.0.0.1:20408/ws` directly on loopback, bypassing firewall rules that block external VPN access to port 20408.
2. **Direct Hardware Subnet Access**: The runner initiates SSH connections to `10.6.4.12` and `10.6.4.13` at wire speed over the local rack switch without routing through VPN or cloudtop proxies.
3. **Outbound Internet Resiliency**: The runner polls GitHub over HTTPS directly from the OSU OSL network. It remains connected and responsive even if local cloudtop VPN sessions disconnect.

---

## 2. Directory & File Layout on Controller Host

On `labgrid.bak.milne.osuosl.org` (`10.6.4.11`), the runner files reside in `~/gha-runner` (or `/home/<username>/gha-runner`):

```text
~/gha-runner/
├── Dockerfile          # Builds Ubuntu 24.04 + Python venv + Labgrid + Actions Runner
└── entrypoint.sh       # Handles runner registration, SSH configs, and execution
```

### 2.1. Dockerfile (`~/gha-runner/Dockerfile`)

```dockerfile
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    python3 \
    python3-pip \
    python3-venv \
    sudo \
    iputils-ping \
    ca-certificates \
    jq \
    libicu-dev \
    libkrb5-3 \
    zlib1g \
    openssh-client \
    psmisc \
    && rm -rf /var/lib/apt/lists/*

# Isolated Python virtual environment for Labgrid & Pytest
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir labgrid pytest
RUN ln -sf /opt/venv/bin/* /usr/local/bin/

WORKDIR /runner

# Official GitHub Actions runner package
RUN RUNNER_VERSION=2.321.0 && \
    curl -o actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz -L https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz && \
    tar xzf ./actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz && \
    rm actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz

COPY entrypoint.sh /runner/entrypoint.sh
RUN chmod +x /runner/entrypoint.sh

ENTRYPOINT ["/runner/entrypoint.sh"]
```

### 2.2. Entrypoint Script (`~/gha-runner/entrypoint.sh`)

```bash
#!/usr/bin/env bash
set -uo pipefail

export RUNNER_ALLOW_RUNASROOT=1

REPO="${GITHUB_REPOSITORY:-riseproject-dev/board-farm}"
TOKEN="${RUNNER_TOKEN}"
NAME="${RUNNER_NAME:-board-farm-qemu-runner}"
LABELS="${RUNNER_LABELS:-self-hosted,board-farm-controller,a210}"

echo "========================================================"
echo " GitHub Actions Self-Hosted Runner (OSU-OSL Controller) "
echo "========================================================"

# Pre-configure SSH client for passwordless connection to boards
mkdir -p /root/.ssh
cat << 'SSHCFG' > /etc/ssh/ssh_config.d/labgrid.conf 2>/dev/null || true
Host 10.6.4.*
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    IdentityFile /root/.ssh/id_ed25519
SSHCFG

# Ensure user SSH credentials directory exists if running as user
if [ -n "${RUNNER_USER:-}" ]; then
    mkdir -p "/home/${RUNNER_USER}/.ssh"
    if [ -f /root/.ssh/id_ed25519 ]; then
        cp -f /root/.ssh/id_ed25519 "/home/${RUNNER_USER}/.ssh/id_ed25519" 2>/dev/null || true
        chmod 600 "/home/${RUNNER_USER}/.ssh/id_ed25519" 2>/dev/null || true
    fi
fi

if [ -n "$REPO" ] && [ -n "$TOKEN" ]; then
    echo "[GHA-Runner] Registering runner with https://github.com/$REPO..."
    ./config.sh --url "https://github.com/$REPO" \
                --token "$TOKEN" \
                --name "$NAME" \
                --labels "$LABELS" \
                --unattended \
                --replace

    echo "[GHA-Runner] Starting runner daemon..."
    exec ./run.sh
else
    echo "[GHA-Runner] Error: GITHUB_REPOSITORY or RUNNER_TOKEN not set."
    exec tail -f /dev/null
fi
```

---

## 3. Deployment Commands

### Step 1: Obtain a Registration Token
Navigate to GitHub:
**`https://github.com/riseproject-dev/board-farm/settings/actions/runners/new`**
Select **Linux ➔ x64**, and copy the token string from the `./config.sh` snippet.

### Step 2: Build the Container Image
On `labgrid.bak.milne.osuosl.org`:
```bash
sudo docker build -t gha-runner:latest ~/gha-runner
```

### Step 3: Launch the Runner Daemon
```bash
sudo docker run -d \
  --name gha-runner \
  --restart unless-stopped \
  --net host \
  -e GITHUB_REPOSITORY="riseproject-dev/board-farm" \
  -e RUNNER_TOKEN="<FRESH_REGISTRATION_TOKEN>" \
  -e RUNNER_NAME="board-farm-qemu-runner" \
  -e RUNNER_LABELS="self-hosted,board-farm-controller,a210" \
  -e LG_CROSSBAR="ws://127.0.0.1:20408/ws" \
  -v $HOME/.ssh:/root/.ssh:ro \
  -v ${PHASE2_TEST_DIR:-$HOME/phase2_test}:/workspace/phase2_test \
  gha-runner:latest
```

### Step 4: Verify Container Execution
```bash
sudo docker logs gha-runner --tail 20
```
Expected output:
```text
√ Connected to GitHub
Current runner version: '2.337.0'
2026-09-02 05:29:23Z: Listening for Jobs
```

---

## 4. GitHub Actions Workflow Configuration

The workflow is stored in the repository at [`.github/workflows/a210_telemetry.yml`](../../.github/workflows/a210_telemetry.yml):

```yaml
name: A210 Hardware Telemetry Test (OSU OSL)

on:
  workflow_dispatch:
    inputs:
      board:
        description: 'Target A210 board to test'
        required: true
        default: 'a210-board-02'
        type: choice
        options:
          - a210-board-02
          - a210-board-01

jobs:
  telemetry:
    name: Run Non-Destructive Hardware Telemetry
    runs-on: [self-hosted, board-farm-controller]
    concurrency:
      group: board-farm-${{ inputs.board }}
      cancel-in-progress: false
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Verify Labgrid Connectivity & Environment
        run: |
          echo "=========================================================="
          echo " Target Board: ${{ inputs.board }}"
          echo " Controller Host: $(hostname)"
          echo " Runner User: $(whoami)"
          echo "=========================================================="
          
          export LG_CROSSBAR="ws://127.0.0.1:20408/ws"
          labgrid-client places
          labgrid-client resources

      - name: Execute Non-Destructive Labgrid Telemetry Tests
        run: |
          BOARD="${{ inputs.board }}"
          export LG_CROSSBAR="ws://127.0.0.1:20408/ws"
          
          echo "Acquiring coordinator lock for $BOARD..."
          labgrid-client -p "$BOARD" acquire || true
          
          ENV_FILE="experiment/osu_osl/lab_env_${BOARD}.yaml"
          TEST_FILE="experiment/osu_osl/tests/test_${BOARD}_telemetry.py"
          
          # Fallback to mounted phase2_test workspace if run in container mount
          if [ ! -f "$ENV_FILE" ]; then
            if [ -f "/workspace/phase2_test/lab_env_${BOARD}.yaml" ]; then
              echo "[Fallback] Using mounted environment: /workspace/phase2_test/lab_env_${BOARD}.yaml"
              ENV_FILE="/workspace/phase2_test/lab_env_${BOARD}.yaml"
              TEST_FILE="/workspace/phase2_test/tests/test_${BOARD}_telemetry.py"
            elif [ -f "${PHASE2_TEST_DIR:-$HOME/phase2_test}/lab_env_${BOARD}.yaml" ]; then
              echo "[Fallback] Using host environment: ${PHASE2_TEST_DIR:-$HOME/phase2_test}/lab_env_${BOARD}.yaml"
              ENV_FILE="${PHASE2_TEST_DIR:-$HOME/phase2_test}/lab_env_${BOARD}.yaml"
              TEST_FILE="${PHASE2_TEST_DIR:-$HOME/phase2_test}/tests/test_${BOARD}_telemetry.py"
            fi
          fi
          
          echo "Executing Pytest suite: $TEST_FILE with $ENV_FILE"
          pytest -v -s \
            --lg-env="$ENV_FILE" \
            --junitxml=results.xml \
            "$TEST_FILE"
          
          echo "Releasing coordinator lock for $BOARD..."
          labgrid-client -p "$BOARD" release || true

      - name: Upload Test Results Artifact
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: ${{ inputs.board }}-telemetry-results
          path: results.xml
```

### 4.2. TFTP Netboot Workflow (`a210_netboot.yml`)

The TFTP Netboot workflow is stored at [`.github/workflows/a210_netboot.yml`](../../.github/workflows/a210_netboot.yml). It executes the automated in-memory RAM netboot pipeline (`run_tftp_trial.py`) over U-Boot:

```yaml
name: A210 TFTP RAM Netboot (OSU OSL)

on:
  workflow_dispatch:
    inputs:
      board:
        description: 'Target A210 board to netboot'
        required: true
        default: 'a210-board-02'
        type: choice
        options:
          - a210-board-02
          - a210-board-01

jobs:
  netboot:
    name: Run In-Memory TFTP Netboot Trial
    runs-on: [self-hosted, board-farm-controller]
    concurrency:
      group: board-farm-${{ inputs.board }}
      cancel-in-progress: false
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Execute TFTP Netboot Sequence in RAM
        run: |
          BOARD="${{ inputs.board }}"
          echo "=========================================================="
          echo " Executing In-Memory TFTP Netboot on: $BOARD"
          echo "=========================================================="

          TEST_SCRIPT="experiment/osu_osl/tests/run_tftp_trial.py"
          if [ ! -f "$TEST_SCRIPT" ]; then
            if [ -f "/workspace/phase2_test/run_tftp_trial.py" ]; then
              TEST_SCRIPT="/workspace/phase2_test/run_tftp_trial.py"
            fi
          fi

          python3 "$TEST_SCRIPT"
```

### 4.3. Native Labgrid UBoot TFTP Workflow (`a210_labgrid_uboot.yml`)

The Native Labgrid UBoot Netboot workflow is stored at [`.github/workflows/a210_labgrid_uboot.yml`](../../.github/workflows/a210_labgrid_uboot.yml). It uses Labgrid's native `UBootDriver` and `ExternalPowerDriver` (`ssh root@<IP> reboot`) to execute Pytest hardware netbooting:

```yaml
name: A210 Labgrid Native UBoot Netboot (OSU OSL)

on:
  workflow_dispatch:
    inputs:
      board:
        description: 'Target A210 board to test'
        required: true
        default: 'a210-board-02'
        type: choice
        options:
          - a210-board-02
          - a210-board-01

jobs:
  labgrid-uboot-netboot:
    name: Run Native Labgrid UBootDriver TFTP Netboot
    runs-on: [self-hosted, board-farm-controller]
    concurrency:
      group: board-farm-${{ inputs.board }}
      cancel-in-progress: false
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Execute Pytest Suite with Native Labgrid UBootDriver
        run: |
          BOARD="${{ inputs.board }}"
          export LG_CROSSBAR="ws://127.0.0.1:20408/ws"

          ENV_FILE="experiment/osu_osl/lab_env_native_uboot_${BOARD}.yaml"
          TEST_FILE="experiment/osu_osl/tests/test_native_uboot_netboot.py"

          pytest -v -s --lg-env="$ENV_FILE" --junitxml=labgrid_uboot_results.xml "$TEST_FILE"
```

---

## 5. How to Trigger Workflows via GitHub UI

1. Open the workflows in GitHub Actions:
   - **Telemetry Test**: 👉 [https://github.com/riseproject-dev/board-farm/actions/workflows/a210_telemetry.yml](https://github.com/riseproject-dev/board-farm/actions/workflows/a210_telemetry.yml)
   - **TFTP Netboot (Script)**: 👉 [https://github.com/riseproject-dev/board-farm/actions/workflows/a210_netboot.yml](https://github.com/riseproject-dev/board-farm/actions/workflows/a210_netboot.yml)
   - **Native Labgrid UBoot Netboot (Pytest)**: 👉 [https://github.com/riseproject-dev/board-farm/actions/workflows/a210_labgrid_uboot.yml](https://github.com/riseproject-dev/board-farm/actions/workflows/a210_labgrid_uboot.yml)
2. Click **Run workflow** (upper right).
3. Select `Branch: main`.
4. Choose target board (`a210-board-02` or `a210-board-01`).
5. Click **Run workflow**.

---

## 6. Real Execution Log (Live Verification)

Runner container log during first live run on `a210-board-02`:
```text
2026-09-02 05:29:23Z: Listening for Jobs
2026-09-02 05:36:59Z: Running job: Run Non-Destructive Hardware Telemetry
2026-09-02 05:37:12Z: Job Run Non-Destructive Hardware Telemetry completed with result: Succeeded
```

Total job duration: **13 seconds** (all 4 hardware assertions passed, JUnit XML artifact published).

---

## 7. Operational & Maintenance Commands

### Check Runner Status
From workstation via proxy wrapper:
```bash
./ssh-osu.sh labgrid "sudo docker ps; sudo docker logs gha-runner --tail 10"
```

### Restart Runner Container
If needed after host updates:
```bash
./ssh-osu.sh labgrid "sudo docker restart gha-runner"
```

### Replace Runner with New Registration Token
If GitHub invalidates registration:
```bash
./ssh-osu.sh labgrid "
  sudo docker stop gha-runner && sudo docker rm gha-runner
  sudo docker run -d \
    --name gha-runner \
    --restart unless-stopped \
    --net host \
    -e GITHUB_REPOSITORY='riseproject-dev/board-farm' \
    -e RUNNER_TOKEN='<NEW_TOKEN>' \
    -e RUNNER_NAME='board-farm-qemu-runner' \
    -e RUNNER_LABELS='self-hosted,board-farm-controller,a210' \
    -e LG_CROSSBAR='ws://127.0.0.1:20408/ws' \
    -v $HOME/.ssh:/root/.ssh:ro \
    -v ${PHASE2_TEST_DIR:-$HOME/phase2_test}:/workspace/phase2_test \
    gha-runner:latest
"
```

---

## 8. Remote Fastboot & Flashing Automation (`enter_fastboot.py`)

The A210 platform uses **Android Fastboot** (over UDP/Ethernet or USB gadget) rather than USB DFU for low-level image deployment and flashing.

The helper script `experiment/osu_osl/scripts/enter_fastboot.py` automates placing any of the 5 cluster boards into Fastboot mode via serial console interception and restoring them safely back to Linux.

### 8.1 Key Capabilities & Design
- **No Physical Remote Relays Needed**: As long as U-Boot or Linux is responsive, boards can be soft-rebooted into Fastboot UDP without physical button presses or relay hardware.
- **Fastboot UDP over Subnet**: Runs directly over the 10.6.4.0/24 rack switch on UDP port 5554.
- **Fail-Safe Restoration**: On `Ctrl+C` (SIGINT) or with the `--reboot` flag, the script cleanly issues `boot` to return the board to persistent Debian Linux.

### 8.2 Usage Examples

```bash
# 1. Non-destructive probe: Enters fastboot UDP, runs 'getvar all', and reboots to Linux
python3 experiment/osu_osl/scripts/enter_fastboot.py --board a210-board-05 --probe

# 2. Interactive Fastboot UDP session (stays listening until Ctrl+C):
python3 experiment/osu_osl/scripts/enter_fastboot.py --board a210-board-05

# In another terminal while active:
fastboot -s udp:10.6.4.16:5554 getvar all
fastboot -s udp:10.6.4.16:5554 flash boot_a boot.img
fastboot -s udp:10.6.4.16:5554 reboot

# 3. Emergency restore: Force a board sitting in U-Boot or Fastboot back to Linux
python3 experiment/osu_osl/scripts/enter_fastboot.py --board a210-board-05 --reboot
```


---

## 9. Developer & Operator Tooling

The scripts in `experiment/osu_osl/` allow operators to connect to the lab, manage OpenVPN tunnels, access boards over serial/SSH, and run hardware test suites.

### 9.1. SSH Wrapper (`ssh-osu.sh`)
Connects to the Labgrid controller host or target boards through the SOCKS5 proxy:

```bash
# Interactive shell on labgrid controller:
./ssh-osu.sh labgrid

# Execute command on board 05 (10.6.4.16):
./ssh-osu.sh a210-5 "uptime"

# Targets supported:
#   labgrid               -> 10.6.4.11 (User: $OSU_SSH_USER)
#   a210-1 ... a210-5     -> 10.6.4.12 ... 10.6.4.16 (User: root)
#   <ip> or user@<ip>     -> Direct IP connection
```

#### Environment Variables:
- `OSU_SSH_USER`: Username on the controller host (default: `$USER`).
- `OSU_SSH_KEY`: Path to private SSH key (default: auto-detects `~/.ssh/id_ed25519`, `~/.ssh/id_rsa`, or `~/.ssh/github_ed25519`).
- `OSU_SOCKS5_PROXY`: SOCKS5 proxy endpoint (default: `127.0.0.1:1080`, set to `none` if on a direct VPN connection).

### 9.2. Isolated OpenVPN & SOCKS5 Client (`vpn-start.sh`, `vpn-status.sh`, `vpn-stop.sh`)
Runs OpenVPN in an isolated container with an embedded Dante SOCKS5 proxy on `127.0.0.1:1080`:

```bash
# Start VPN container (uses OSU_VPN_CONFIG or auto-detects client.ovpn):
./vpn-start.sh

# Check tunnel status and target connectivity (gateway, controller, boards 01-05):
./vpn-status.sh

# Stop VPN container:
./vpn-stop.sh
```

#### Environment Variables:
- `OSU_VPN_CONFIG`: Absolute path to your `.ovpn` configuration file (default: `client.ovpn` or any single `.ovpn` file in the directory).

### 9.3. Test & Execution Scripts
- **`tests/run_phase2c.sh`**: Runs Phase 2C non-destructive hardware telemetry via Labgrid `SSHDriver`. Supports setting `REMOTE_TEST_DIR`.
- **`tests/tftp_execute.py`**: Executes an automated in-memory RAM netboot over U-Boot serial console (`--port`, `--server-ip`, or `A210_SERIAL_PORT`, `TFTP_SERVER_IP`).
- **`tests/test_a210_netboot.py`**: Native Pytest Labgrid netboot test using `UBootDriver`.
- **`scripts/enter_fastboot.py`**: Intercepts U-Boot countdown to enter Android Fastboot UDP / USB mode. Binary search path configurable via `FASTBOOT_PATH`.
