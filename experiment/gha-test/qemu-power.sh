#!/usr/bin/env bash
# Script to simulate PDU power control for QEMU / Mock target
set -euo pipefail

ACTION="${1:-cycle}"
TARGET_TYPE="${TARGET_TYPE:-mock}" # 'mock', 'x86_64', or 'riscv64'
SERIAL_PORT="${SERIAL_PORT:-2001}"
PID_FILE="/tmp/qemu-board-${SERIAL_PORT}.pid"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stop_target() {
    echo "Stopping any running target on port $SERIAL_PORT..."
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill -9 "$PID" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi
    pkill -9 -f "mock_target.py" 2>/dev/null || true
    pkill -9 -f "qemu-system-riscv64" 2>/dev/null || true
    fuser -k -9 "${SERIAL_PORT}/tcp" 2>/dev/null || true
    sleep 1
}

start_target() {
    stop_target
    echo "Starting target [$TARGET_TYPE] on serial port $SERIAL_PORT..."
    
    if [ "$TARGET_TYPE" = "mock" ]; then
        python3 "$SCRIPT_DIR/mock_target.py" --port "$SERIAL_PORT" &
        PID=$!
        echo $PID > "$PID_FILE"
        disown $PID 2>/dev/null || true
    elif [ "$TARGET_TYPE" = "riscv64" ] || [ "$TARGET_TYPE" = "qemu" ]; then
        qemu-system-riscv64 \
            -M virt \
            -m 512M \
            -nographic \
            -monitor none \
            -bios /usr/lib/riscv64-linux-gnu/opensbi/generic/fw_jump.bin \
            -kernel /usr/lib/u-boot/qemu-riscv64/u-boot.bin \
            -serial tcp:127.0.0.1:"$SERIAL_PORT",server,nowait \
            </dev/null >/tmp/qemu.log 2>&1 &
        PID=$!
        echo $PID > "$PID_FILE"
        disown $PID 2>/dev/null || true
    elif [ "$TARGET_TYPE" = "x86_64" ]; then
        qemu-system-x86_64 \
            -m 512M \
            -nographic \
            -monitor none \
            -netdev user,id=net0,tftp=/tmp/tftp \
            -device e1000,netdev=net0 \
            -serial tcp:127.0.0.1:"$SERIAL_PORT",server,nowait \
            </dev/null >/tmp/qemu.log 2>&1 &
        PID=$!
        echo $PID > "$PID_FILE"
        disown $PID 2>/dev/null || true
    else
        echo "Unknown TARGET_TYPE: $TARGET_TYPE"
        exit 1
    fi
    echo "Target started successfully."
}

case "$ACTION" in
    on)
        start_target
        ;;
    off)
        stop_target
        ;;
    cycle|reset)
        stop_target
        start_target
        ;;
    *)
        echo "Usage: $0 {on|off|cycle}"
        exit 1
        ;;
esac
