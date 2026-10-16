# RISE Board Farm Hub

Lightweight, real-time dashboard and telemetry aggregator for the OSU OSL RISC-V A210 board farm, bridging **Labgrid** hardware reservations and **Kubernetes** worker node telemetry.

---

## Features
- **Real-Time Labgrid Coordination**: Tracks coordinator places (`a210-board-01` .. `05`) on port `20408` (Idle, Acquired, Reserved, Offline).
- **Live Hardware Telemetry**: Non-destructive background polling of CPU load (1m/5m/15m), RAM utilization, eMMC storage, and uptime across all 5 physical boards.
- **Kubernetes Node Visibility**: Highlights cluster workers (e.g. `a210-board-05`) with live node condition, Flannel VXLAN overlay subnet (`10.244.29.0/32`), and Device Plugin status.
- **Reactive Frontend**: Single-page Vue 3 + Tailwind CSS dark dashboard receiving real-time Server-Sent Events (SSE).
- **Observability**: Exposes standard `/metrics` Prometheus format for Grafana ingestion.
- **Zero Heavy Dependencies**: Built with Python (FastAPI) and embedded SQLite in WAL mode (`hub.db`).

---

## Directory Layout
```text
hub/
├── README.md               # Documentation
├── requirements.txt        # Python package dependencies
├── deploy.sh               # One-click remote deployment to controller host
├── hub.py                  # CLI runner and entrypoint
├── app/
│   ├── config.py           # Cluster configuration & board metadata
│   ├── db.py               # SQLite WAL database models & CRUD
│   ├── coordinator.py      # Labgrid coordinator sync worker
│   ├── telemetry.py        # Hardware & Kubernetes telemetry poller
│   └── main.py             # FastAPI REST, SSE stream, and metrics endpoints
└── static/
    └── index.html          # Vue 3 / Tailwind CSS responsive web dashboard
```

---

## Quick Start & Local Execution
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run single polling pass
python3 hub.py poll

# 3. Start web server on port 8080
python3 hub.py run --port 8080
```

---

## Remote Deployment to Labgrid Controller (`/opt/board-farm-hub`)

The Hub runs in `/opt/board-farm-hub` on `labgrid.bak.milne.osuosl.org` (`10.6.4.11`), managed by `board-farm-hub.service` and shared across the `rise` group.

### Option A: Automated Deployment (No `git clone` required on controller)
From a workstation with `ssh-osu.sh` configured, run:
```bash
./deploy.sh
```
This archives `hub/` via `tar` over SSH directly into `/opt/board-farm-hub`, creates `/opt/board-farm-hub/venv`, installs `requirements.txt`, and configures/restarts `/etc/systemd/system/board-farm-hub.service`.

### Option B: Manual `scp` or `git clone` on the Controller
If deploying directly on the controller (`10.6.4.11`):
```bash
# 1. Copy or clone files into /opt/board-farm-hub
sudo mkdir -p /opt/board-farm-hub
sudo chown -R "$USER:rise" /opt/board-farm-hub
cp -r hub/* /opt/board-farm-hub/

# 2. Create virtualenv and install dependencies
python3 -m venv /opt/board-farm-hub/venv
/opt/board-farm-hub/venv/bin/pip install --upgrade pip
/opt/board-farm-hub/venv/bin/pip install -r /opt/board-farm-hub/requirements.txt

# 3. Enable and start systemd service
sudo systemctl daemon-reload
sudo systemctl enable --now board-farm-hub.service
```

---

## API Endpoints
- `GET /`: Responsive web dashboard
- `GET /api/v1/health`: Controller and tracked boards health status
- `GET /api/v1/boards`: JSON list of all boards with hardware tags, telemetry, and K8s status
- `GET /api/v1/events`: Recent cluster activity event log
- `GET /api/v1/stream`: Server-Sent Events (SSE) live updates stream
- `POST /api/v1/refresh`: Trigger an immediate on-demand polling cycle
- `GET /metrics`: Prometheus formatted metrics export (including Linux Foundation LFX telemetry schemas)

---

## Linux Foundation (LFX) Telemetry Schema

The `/metrics` endpoint exports metrics conforming to the Linux Foundation LFX hardware testbed specification for the All Things Open (ATO) showcase:

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `lfx_riscv_board_available` | Gauge | `board_id`, `soc`, `location`, `k8s_joined` | Availability status of RISC-V physical boards (1=Ready, 0=Unavailable) |
| `lfx_riscv_active_jobs` | Gauge | `board_id`, `suite`, `runner_type` | Currently active CI test executions dispatched to baremetal boards |
| `board_farm_node_ready` | Gauge | `node`, `soc`, `location` | Node readiness status across testbed |
| `board_farm_temperature_celsius` | Gauge | `board` | Operating temperature in Celsius |
| `board_farm_job_duration_seconds` | Counter | `board` | Cumulative test job run duration |

