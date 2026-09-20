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

## Remote Deployment to Labgrid Controller
```bash
./deploy.sh
```

---

## API Endpoints
- `GET /`: Responsive web dashboard
- `GET /api/v1/health`: Controller and tracked boards health status
- `GET /api/v1/boards`: JSON list of all boards with hardware tags, telemetry, and K8s status
- `GET /api/v1/events`: Recent cluster activity event log
- `GET /api/v1/stream`: Server-Sent Events (SSE) live updates stream
- `POST /api/v1/refresh`: Trigger an immediate on-demand polling cycle
- `GET /metrics`: Prometheus formatted metrics export
