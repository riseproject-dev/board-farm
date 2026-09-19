#!/usr/bin/env python3
"""
A210 Remote Fastboot Entry & Session Controller (OSU OSL Board Farm)

Automates placing an A210 board into Android Fastboot mode (over UDP/Ethernet
or USB gadget) by soft-rebooting into U-Boot and catching the autoboot countdown.

Usage:
  # Enter fastboot UDP mode on a210-board-05 (stays in fastboot until Ctrl+C):
  python3 enter_fastboot.py --board a210-board-05

  # Run quick verification probe (getvar all) and return cleanly to Linux:
  python3 enter_fastboot.py --board a210-board-05 --probe

  # Enter USB gadget fastboot (fastboot usb 0):
  python3 enter_fastboot.py --board a210-board-05 --mode usb

  # Restore a board in U-Boot/fastboot back to normal Linux boot:
  python3 enter_fastboot.py --board a210-board-05 --reboot
"""

import os
import sys
import time
import signal
import serial
import threading
import argparse
import subprocess
import shutil

BOARD_MAP = {
    "a210-board-01": {"ip": "10.6.4.12", "port": "/dev/ttyUSB0"},
    "a210-board-02": {"ip": "10.6.4.13", "port": "/dev/ttyUSB1"},
    "a210-board-03": {"ip": "10.6.4.14", "port": "/dev/ttyUSB2"},
    "a210-board-04": {"ip": "10.6.4.15", "port": "/dev/ttyUSB3"},
    "a210-board-05": {"ip": "10.6.4.16", "port": "/dev/ttyUSB4"},
}
for i in range(1, 6):
    BOARD_MAP[f"a210-{i}"] = BOARD_MAP[f"a210-board-{i:02d}"]

def find_fastboot_binary():
    """Locate fastboot binary via FASTBOOT_PATH, PATH, or local user bin."""
    env_path = os.environ.get("FASTBOOT_PATH")
    if env_path and (shutil.which(env_path) or os.path.isfile(env_path)):
        return env_path
    path = shutil.which("fastboot")
    if path:
        return path
    user_bin = os.path.expanduser("~/bin/fastboot")
    for candidate in [user_bin, "/usr/local/bin/fastboot", "/usr/bin/fastboot"]:
        if shutil.which(candidate) or os.path.isfile(candidate):
            return candidate
    return None

def trigger_reboot(ser, target_ssh):
    """Attempt SSH reboot, fallback to serial reset."""
    time.sleep(2)
    print(f"[Host] Sending SSH reboot to {target_ssh}...", flush=True)
    try:
        subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3", target_ssh, "reboot"],
            timeout=5,
            capture_output=True,
        )
    except Exception as e:
        print(f"[Host Note] SSH reboot result: {e}", flush=True)

    # Serial fallback: issue reset in case target is sitting in U-Boot or emergency shell
    try:
        ser.write(b"\nreset\nreboot -f\n")
    except Exception:
        pass

def send_cmd(ser, cmd, timeout=15):
    """Send command to U-Boot and wait for prompt."""
    print(f"[U-Boot Command] => {cmd}", flush=True)
    ser.write((cmd + "\n").encode("latin1"))
    buf = ""
    start = time.time()
    while time.time() - start < timeout:
        data = ser.read(ser.in_waiting or 1)
        if data:
            chunk = data.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()
            buf += chunk
            if "u-boot#" in buf or "=>" in buf:
                return True, buf
    return False, buf

def enter_uboot(ser, target_ssh, timeout=75):
    """Catch autoboot countdown on serial console."""
    ser.reset_input_buffer()
    t = threading.Thread(target=trigger_reboot, args=(ser, target_ssh))
    t.daemon = True
    t.start()

    print("[Host] Monitoring serial console for U-Boot autoboot countdown...", flush=True)
    buf = ""
    start = time.time()
    interrupted = False

    while time.time() - start < timeout:
        data = ser.read(ser.in_waiting or 1)
        if data:
            chunk = data.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()
            buf += chunk

            if "u-boot#" in buf or "=>" in buf:
                print("\n[Host] >>> U-BOOT PROMPT ACTIVE! <<<", flush=True)
                return True

            if not interrupted and any(x in buf.lower() for x in ["autoboot", "hit any key", "stop autoboot"]):
                print("\n[Host] >>> INTERCEPTING AUTOBOOT! <<<", flush=True)
                for _ in range(12):
                    ser.write(b" \n")
                    time.sleep(0.04)
                interrupted = True
                buf = ""
    return False

def reboot_to_linux(ser):
    """Send boot command to return cleanly to Linux."""
    print("\n[Host] Booting board back into Linux OS...", flush=True)
    ser.write(b"\x03\n")
    time.sleep(0.5)
    ser.write(b"boot\n")
    time.sleep(1)

def main():
    parser = argparse.ArgumentParser(description="Remote A210 Fastboot Entry & Session Manager")
    parser.add_argument(
        "--board",
        choices=list(BOARD_MAP.keys()),
        default="a210-board-05",
        help="Target board (default: a210-board-05)",
    )
    parser.add_argument(
        "--mode",
        choices=["udp", "usb"],
        default="udp",
        help="Fastboot interface: 'udp' (network, default) or 'usb' (Type-A flashing cable)",
    )
    parser.add_argument(
        "--port",
        help="Override serial port path (default: auto-selected by board)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Serial baud rate (default: 115200)",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Run non-destructive query (fastboot getvar all) and return to Linux",
    )
    parser.add_argument(
        "--reboot",
        action="store_true",
        help="Restore a board sitting in U-Boot or Fastboot back to Linux",
    )

    args = parser.parse_args()
    cfg = BOARD_MAP[args.board]
    board_name = args.board
    board_ip = cfg["ip"]
    serial_port = args.port or cfg["port"]
    target_ssh = f"root@{board_ip}"

    print("============================================================")
    print(f" A210 Fastboot Session Controller")
    print(f" Target: {board_name} ({board_ip})")
    print(f" Serial: {serial_port} @ {args.baud}")
    print(f" Mode:   {args.mode.upper()} Fastboot")
    print("============================================================", flush=True)

    try:
        ser = serial.Serial(serial_port, args.baud, timeout=0.1)
    except Exception as e:
        print(f"[Host Error] Failed to open serial port {serial_port}: {e}", file=sys.stderr)
        return 1

    # Simple reboot mode
    if args.reboot:
        reboot_to_linux(ser)
        ser.close()
        print("[Host] Boot command issued. Exiting.")
        return 0

    # Step 1: Intercept U-Boot
    if not enter_uboot(ser, target_ssh):
        print("[Host Error] Timed out waiting for U-Boot prompt!", file=sys.stderr)
        ser.close()
        return 1

    time.sleep(0.5)

    # Step 2: Configure Fastboot
    if args.mode == "udp":
        print("\n--- [Phase 1] Configuring Network for Fastboot UDP ---", flush=True)
        send_cmd(ser, "setenv autoload no", timeout=3)
        ok, _ = send_cmd(ser, "dhcp", timeout=15)
        if not ok:
            send_cmd(ser, "dhcp", timeout=15)

        print("\n--- [Phase 2] Starting Fastboot UDP Listener ---", flush=True)
        print(f"[Host] Fastboot UDP listening on {board_ip}:5554...", flush=True)
        ser.write(b"fastboot udp\n")

        # Wait for listening notification on console
        time.sleep(2)
        fastboot_bin = find_fastboot_binary()
        fb_target = f"udp:{board_ip}:5554"

        print("\n============================================================")
        print(f" FASTBOOT UDP ACTIVE ON {board_name}!")
        print(f" Target Address: {fb_target}")
        print(" Flash command examples:")
        print(f"   fastboot -s {fb_target} getvar all")
        print(f"   fastboot -s {fb_target} flash boot_a <boot_image>")
        print(f"   fastboot -s {fb_target} flash system_a <system_image>")
        print("============================================================\n", flush=True)

        if args.probe:
            if fastboot_bin:
                print(f"[Host] Running probe with {fastboot_bin}...", flush=True)
                cmd = [fastboot_bin, "-s", fb_target, "getvar", "all"]
                subprocess.run(cmd)
            else:
                print("[Host Warning] fastboot binary not found in PATH to execute probe.", flush=True)

            # Exit fastboot cleanly and reboot
            reboot_to_linux(ser)
            ser.close()
            print("\n[Host] Probe completed and board restored to Linux.")
            return 0

    else:
        print("\n--- [Phase 1] Starting USB Fastboot Gadget ---", flush=True)
        print("[Host] Flashing port will enumerate as 0x37f2:0xd00d via USB A-to-A cable...", flush=True)
        ser.write(b"fastboot usb 0\n")
        print("\n============================================================")
        print(f" USB FASTBOOT ACTIVE ON {board_name}!")
        print(" Flash command example:")
        print("   fastboot devices")
        print("   fastboot flash boot_a <boot_image>")
        print("============================================================\n", flush=True)

        if args.probe:
            fastboot_bin = find_fastboot_binary()
            if fastboot_bin:
                subprocess.run([fastboot_bin, "devices"])
            reboot_to_linux(ser)
            ser.close()
            return 0

    # Interactive session loop: keep listening until Ctrl+C
    print("[Host] Press Ctrl+C at any time to exit Fastboot and reboot back to Linux.\n", flush=True)

    def sigint_handler(sig, frame):
        print("\n[Host] Interrupt received! Exiting Fastboot mode...", flush=True)
        reboot_to_linux(ser)
        ser.close()
        print("[Host] Board restored to Linux. Session ended.")
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)

    while True:
        try:
            data = ser.read(ser.in_waiting or 1)
            if data:
                sys.stdout.write(data.decode("latin1", errors="replace"))
                sys.stdout.flush()
        except (KeyboardInterrupt, SystemExit):
            sigint_handler(None, None)

if __name__ == "__main__":
    sys.exit(main())
