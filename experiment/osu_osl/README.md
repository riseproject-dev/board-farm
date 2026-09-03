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
 │    └── Mounted Credentials: /home/puneetha/.ssh/id_ed25519 (read-only) │
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

On `labgrid.bak.milne.osuosl.org` (`10.6.4.11`), the runner files reside in `/home/puneetha/gha-runner`:

```text
/home/puneetha/gha-runner/
├── Dockerfile          # Builds Ubuntu 24.04 + Python venv + Labgrid + Actions Runner
└── entrypoint.sh       # Handles runner registration, SSH configs, and execution
```

### 2.1. Dockerfile (`/home/puneetha/gha-runner/Dockerfile`)

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

### 2.2. Entrypoint Script (`/home/puneetha/gha-runner/entrypoint.sh`)

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

mkdir -p /home/puneetha/.ssh
if [ -f /root/.ssh/id_ed25519 ]; then
    cp -f /root/.ssh/id_ed25519 /home/puneetha/.ssh/id_ed25519 2>/dev/null || true
    chmod 600 /home/puneetha/.ssh/id_ed25519 2>/dev/null || true
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
sudo docker build -t gha-runner:latest /home/puneetha/gha-runner
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
  -v /home/puneetha/.ssh:/root/.ssh:ro \
  -v /home/puneetha/phase2_test:/workspace/phase2_test \
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

The workflow is stored in the repository at [`.github/workflows/a210_telemetry.yml`](file:///usr/local/google/home/puneetha/RISE/git-repo/board-farm/.github/workflows/a210_telemetry.yml):

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
            elif [ -f "/home/puneetha/phase2_test/lab_env_${BOARD}.yaml" ]; then
              echo "[Fallback] Using host environment: /home/puneetha/phase2_test/lab_env_${BOARD}.yaml"
              ENV_FILE="/home/puneetha/phase2_test/lab_env_${BOARD}.yaml"
              TEST_FILE="/home/puneetha/phase2_test/tests/test_${BOARD}_telemetry.py"
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

The TFTP Netboot workflow is stored at [`.github/workflows/a210_netboot.yml`](file:///usr/local/google/home/puneetha/RISE/git-repo/board-farm/.github/workflows/a210_netboot.yml). It executes the automated in-memory RAM netboot pipeline (`run_tftp_trial.py`) over U-Boot:

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

---

## 5. How to Trigger Workflows via GitHub UI

1. Open the workflows in GitHub Actions:
   - **Telemetry Test**: 👉 [https://github.com/riseproject-dev/board-farm/actions/workflows/a210_telemetry.yml](https://github.com/riseproject-dev/board-farm/actions/workflows/a210_telemetry.yml)
   - **TFTP Netboot**: 👉 [https://github.com/riseproject-dev/board-farm/actions/workflows/a210_netboot.yml](https://github.com/riseproject-dev/board-farm/actions/workflows/a210_netboot.yml)
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
    -v /home/puneetha/.ssh:/root/.ssh:ro \
    -v /home/puneetha/phase2_test:/workspace/phase2_test \
    gha-runner:latest
"
```
