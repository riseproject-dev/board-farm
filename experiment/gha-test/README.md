# Phase 1 Labgrid Pilot: 4-Container Microservices Architecture

This experiment provides a fully self-contained local prototype of **Phase 1 (Labgrid Pilot)** as specified in [tftp-boot-gha-and-flashing-design.md](../../docs/architecture-design/tftp-boot-gha-and-flashing-design.md) and [labgrid-dhcp-tftp-research.md](../../docs/phase-1-labgrid-pilot/labgrid-dhcp-tftp-research.md).

It splits the board farm architecture into **four separate Docker containers**, mirroring production lab setup:

1. **`labgrid-exporter` Container (PDU & Hardware Control)**:
   Executes [`qemu-power.sh`](file:///usr/local/google/home/puneetha/RISE/git-repo/board-farm/experiment/gha-test/qemu-power.sh) to handle PDU power cycling (`CommandPowerPort`) and exposes serial console endpoints (Port 2001).
2. **`labgrid-coordinator` Container (Lock Registry)**:
   Central resource locking and board state registry service (Port 20408).
3. **`lab-gateway` Container (DHCP & TFTP Server)**:
   Containerized `strm/dnsmasq` serving DHCP (`192.168.100.x`) and TFTP (`/srv/tftp`) over UDP with `--bind-interfaces`.
4. **`gha-runner` Container (GitHub Actions Runner & Orchestrator)**:
   Self-hosted GitHub Actions runner container that pulls GHA workflows, stages kernel artifacts to `/tmp/tftp/`, and executes Pytest Labgrid tests.

---

## Documentation Files

- [GHA_RUNNER_SETUP.md](file:///usr/local/google/home/puneetha/RISE/git-repo/board-farm/experiment/gha-test/GHA_RUNNER_SETUP.md): Step-by-step guide for registering the `gha-runner` container with an online GitHub repository fork and running live GitHub Actions workflows.

---

## Directory Structure

```text
experiment/gha-test/
├── README.md                 # Documentation and execution guide
├── GHA_RUNNER_SETUP.md       # Detailed GitHub Actions self-hosted runner guide
├── docker-compose.yml        # 4-Container Compose config (Exporter, Coordinator, Gateway, GHA Runner)
├── Dockerfile.labgrid        # Docker container image definition for Labgrid services
├── Dockerfile.gha-runner     # Docker container image definition for GitHub Actions Runner
├── entrypoint.sh             # Entrypoint script for GHA Runner registration
├── run_experiment.sh         # Master test runner script (6 logging stages)
├── setup-gateway.sh          # Container setup & TFTP directory initialization
├── qemu-power.sh             # PDU simulator (controls QEMU or Mock DUT)
├── mock_target.py            # Mock serial DUT server for instant local runs
├── download-image.sh         # Helper to fetch real Alpine Linux kernel & initramfs
├── exporter.yaml             # Labgrid exporter configuration
├── lab_env.yaml              # Labgrid environment & target driver bindings
├── tests/
│   └── test_kernel.py        # Pytest test suite strictly using Labgrid drivers
└── .github/
    └── workflows/
        └── kernel_test.yml   # GitHub Actions workflow for Phase 1
```

---

## Quick Start (Local Run)

```bash
cd experiment/gha-test
sudo ./run_experiment.sh
```
