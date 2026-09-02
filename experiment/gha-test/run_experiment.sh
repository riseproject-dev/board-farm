#!/usr/bin/env bash
# Master Experiment Launcher: Phase 1 Labgrid Pilot 4-Container Stack
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_TYPE="${TARGET_TYPE:-mock}"
TFTP_DIR="/tmp/tftp/qemu-board"
GH_TEST_MODE=0

# Parse command line flags
for arg in "$@"; do
    case "$arg" in
        --gh-test)
            GH_TEST_MODE=1
            ;;
        *)
            ;;
    esac
done

echo ""
echo "=========================================================================="
echo "      RISE BOARD FARM - PHASE 1 LABGRID PILOT LOCAL EXPERIMENT            "
echo "=========================================================================="
echo "  Architecture: 4-Container Docker Microservices (Gateway, Coord, Exp, GHA)"
echo "  Target Mode : $TARGET_TYPE"
echo "  Runner Mode : $( [ "$GH_TEST_MODE" -eq 1 ] && echo "GitHub Actions Remote (--gh-test)" || echo "Direct Pytest Local" )"
echo "  Timestamp   : $(date -u)"
echo "=========================================================================="
echo ""

# Cleanup trap (Restored full teardown on script exit)
cleanup() {
    echo ""
    echo "=========================================================================="
    echo " [STAGE 6/6] EXPERIMENT TEARDOWN & CLEANUP                                "
    echo "=========================================================================="
    echo "[Cleanup] Powering off Target DUT..."
    "$SCRIPT_DIR/qemu-power.sh" off >/dev/null 2>&1 || true

    if command -v docker >/dev/null 2>&1; then
        echo "[Cleanup] Stopping and removing 4-container Docker stack..."
        (cd "$SCRIPT_DIR" && docker compose down --remove-orphans)
    fi
    echo "[Cleanup] Teardown and cleanup completed successfully."
    echo "=========================================================================="
}
trap cleanup EXIT

# --------------------------------------------------------------------------
# STAGE 1: INITIALIZATION & STAGING SETUP
# --------------------------------------------------------------------------
echo "=========================================================================="
echo " [STAGE 1/6] INITIALIZING ENVIRONMENT & TFTP STAGING PATH                 "
echo "=========================================================================="
echo "[Stage 1] Creating TFTP staging directory at $TFTP_DIR..."
mkdir -p "$TFTP_DIR"
chmod -R 777 /tmp/tftp
echo "[Stage 1] TFTP staging directory prepared successfully."
echo ""

# --------------------------------------------------------------------------
# STAGE 2: DOCKER MICROSERVICES STACK DEPLOYMENT & PLACE PROVISIONING
# --------------------------------------------------------------------------
echo "=========================================================================="
echo " [STAGE 2/6] DEPLOYING 4-CONTAINER DOCKER STACK & PROVISIONING BOARD PLACE "
echo "=========================================================================="
if command -v docker >/dev/null 2>&1; then
    echo "[Stage 2] Building & launching containers via Docker Compose..."
    echo "[Stage 2] Containers: lab-gateway, labgrid-coordinator, labgrid-exporter, gha-runner"
    (cd "$SCRIPT_DIR" && docker compose up -d)
    
    echo "[Stage 2] Auto-provisioning lab board 'qemu-board-01' on labgrid-coordinator..."
    sleep 2
    docker compose exec -T gha-runner bash -c "
        export LG_CROSSBAR=ws://127.0.0.1:20408/ws
        labgrid-client -p qemu-board-01 create || true
        labgrid-client -p qemu-board-01 add-match '*/*/*/*' || true
        labgrid-client -p qemu-board-01 set-tags board=qemu-riscv64 || true
    "
    
    echo "[Stage 2] Current container status:"
    (cd "$SCRIPT_DIR" && docker compose ps)
else
    echo "⚠️ [Stage 2] Docker command not found. Running in local process mode."
fi
echo ""

# --------------------------------------------------------------------------
# STAGE 3: GATEWAY & TFTP READINESS VERIFICATION
# --------------------------------------------------------------------------
echo "=========================================================================="
echo " [STAGE 3/6] VERIFYING TFTP & DHCP GATEWAY READINESS                       "
echo "=========================================================================="
echo "[Stage 3] Checking gateway readiness..."
READY=0
for i in $(seq 1 10); do
    if command -v docker >/dev/null 2>&1 && [ "$(docker inspect -f '{{.State.Running}}' lab-gateway 2>/dev/null)" = "true" ]; then
        READY=1
        break
    fi
    sleep 1
done

if [ "$READY" -eq 1 ]; then
    echo "✓ [Stage 3] lab-gateway container (dnsmasq) is UP and serving /tmp/tftp."
else
    echo "⚠️ [Stage 3] Gateway container check pending (proceeding with local network)."
fi
echo ""

# --------------------------------------------------------------------------
# STAGE 4: TARGET DUT POWER-ON & PDU SIMULATION
# --------------------------------------------------------------------------
echo "=========================================================================="
echo " [STAGE 4/6] PDU POWER CONTROL & TARGET DUT LAUNCH                        "
echo "=========================================================================="
echo "[Stage 4] Triggering PDU power-cycle for target [$TARGET_TYPE]..."
TARGET_TYPE="$TARGET_TYPE" "$SCRIPT_DIR/qemu-power.sh" cycle
echo "[Stage 4] Target DUT is running and listening for serial on TCP port 2001."
sleep 1
echo ""

# --------------------------------------------------------------------------
# STAGE 5: LABGRID DYNAMIC LOCK RESERVATION & TEST SUITE EXECUTION
# --------------------------------------------------------------------------
echo "=========================================================================="
echo " [STAGE 5/6] DYNAMIC BOARD RESERVATION & TEST SUITE EXECUTION             "
echo "=========================================================================="

# Wait for gha-runner container readiness
for i in $(seq 1 10); do
    if command -v docker >/dev/null 2>&1 && [ "$(docker inspect -f '{{.State.Running}}' gha-runner 2>/dev/null)" = "true" ]; then
        break
    fi
    sleep 1
done

if [ "$GH_TEST_MODE" -eq 1 ]; then
    echo "[Stage 5] GitHub Actions Runner Mode (--gh-test) enabled."
    echo "[Stage 5] Listening on container 'gha-runner' logs for queued GitHub Actions jobs..."
    echo "[Stage 5] Queue a task via GitHub Actions (UI/API) to proceed."
    echo ""

    JOB_STATUS=""
    while IFS= read -r line; do
        echo "[gha-runner] $line"
        if [[ "$line" =~ Job\ .*completed\ with\ result:\ (.*) ]]; then
            JOB_STATUS="${BASH_REMATCH[1]}"
            break
        fi
    done < <(docker logs -f --tail 0 gha-runner 2>&1)

    if [ "$JOB_STATUS" = "Succeeded" ]; then
        echo ""
        echo "✓ [Stage 5] GitHub Actions job completed successfully ($JOB_STATUS)!"
    else
        echo ""
        echo "❌ [Stage 5] GitHub Actions job ended with status: ${JOB_STATUS:-Failed}."
        exit 1
    fi
else
    if command -v docker >/dev/null 2>&1 && [ "$(docker inspect -f '{{.State.Running}}' gha-runner 2>/dev/null)" = "true" ]; then
        echo "[Stage 5] Executing Pytest test suite inside 'gha-runner' Docker container via dynamic reservation..."
        docker exec -t gha-runner bash -c "
            export LG_CROSSBAR=ws://127.0.0.1:20408/ws
            eval \$(labgrid-client reserve --shell --wait board=qemu-riscv64)
            echo \"[Stage 5] Dynamically reserved board place '\$LG_PLACE' (Token: \$LG_TOKEN)\"
            labgrid-client -p \"\$LG_PLACE\" acquire || true
            cd /workspace && /opt/venv/bin/pytest -s --lg-env=lab_env.yaml --junitxml=results.xml tests/test_kernel.py
            labgrid-client -p \"\$LG_PLACE\" release || true
            labgrid-client cancel-reservation \"\$LG_TOKEN\" || true
        "
    else
        echo "[Stage 5] Executing Pytest test suite inside container..."
        docker exec -t gha-runner bash -c "
            export LG_CROSSBAR=ws://127.0.0.1:20408/ws
            eval \$(labgrid-client reserve --shell --wait board=qemu-riscv64)
            labgrid-client -p \"\$LG_PLACE\" acquire || true
            /opt/venv/bin/pytest -s --lg-env=/workspace/lab_env.yaml --junitxml=/workspace/results.xml /workspace/tests/test_kernel.py
            labgrid-client -p \"\$LG_PLACE\" release || true
            labgrid-client cancel-reservation \"\$LG_TOKEN\" || true
        "
    fi
fi

echo ""
echo "=========================================================================="
echo "          EXPERIMENT COMPLETED SUCCESSFULLY!                              "
echo "=========================================================================="
echo "  - Test XML Report : $SCRIPT_DIR/results.xml"
echo "  - Target Boot Mode: $TARGET_TYPE"
echo "=========================================================================="
