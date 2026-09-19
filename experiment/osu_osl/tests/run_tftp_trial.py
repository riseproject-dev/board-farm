#!/usr/bin/env python3
"""
Automated Phase 2/3/4 U-Boot & TFTP RAM Netboot Execution Script for a210-2.
Monitors serial console on /dev/ttyUSB1, interrupts autoboot, downloads
kernel + DTB + initramfs over TFTP from 10.6.4.11 into RAM, and boots.
"""
import sys
import time
import serial
import threading
import subprocess

import argparse

BOARD_MAP = {
    "a210-board-01": {"port": "/dev/ttyUSB0", "ssh": "root@10.6.4.12"},
    "a210-board-02": {"port": "/dev/ttyUSB1", "ssh": "root@10.6.4.13"},
    "a210-board-03": {"port": "/dev/ttyUSB2", "ssh": "root@10.6.4.14"},
    "a210-board-04": {"port": "/dev/ttyUSB3", "ssh": "root@10.6.4.15"},
    "a210-board-05": {"port": "/dev/ttyUSB4", "ssh": "root@10.6.4.16"},
}

# Add shorthands
for i in range(1, 6):
    BOARD_MAP[f"a210-{i}"] = BOARD_MAP[f"a210-board-{i:02d}"]

def parse_args():
    parser = argparse.ArgumentParser(description="A210 TFTP RAM Netboot Execution Script")
    parser.add_argument(
        "--board",
        choices=list(BOARD_MAP.keys()),
        default="a210-board-02",
        help="Target A210 board to netboot",
    )
    parser.add_argument(
        "--image",
        default="Image",
        help="Kernel image filename on TFTP server (default: Image)",
    )
    parser.add_argument(
        "--dtb",
        default="a210-dev.dtb",
        help="Device tree filename on TFTP server (default: a210-dev.dtb)",
    )
    parser.add_argument(
        "--rootfs",
        choices=["ram", "emmc"],
        default="ram",
        help="Root filesystem type: 'ram' (installer.cpio.gz) or 'emmc' (/dev/mmcblk0p4) (default: ram)",
    )
    return parser.parse_args()

args = parse_args()
cfg = BOARD_MAP[args.board]
if args.board.startswith("a210-board-"):
    BOARD_NAME = args.board
else:
    idx = int(args.board.split("-")[1])
    BOARD_NAME = f"a210-board-{idx:02d}"

PORT = cfg["port"]
TARGET_SSH = cfg["ssh"]
BAUD = 115200
SERVER_IP = "10.6.4.11"

def trigger_reboot(ser):
    time.sleep(2)
    # Step 2: Reboot target into U-Boot
    print(f"\n[Host] Sending SSH reboot to {TARGET_SSH}...", flush=True)
    try:
        subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", TARGET_SSH, "reboot"],
            timeout=5,
            capture_output=True,
        )
    except Exception as e:
        print(f"[Host Note] SSH reboot result: {e}", flush=True)

    # Serial fallback: trigger reset over serial line if target is in initramfs shell or u-boot
    try:
        ser.write(b"\nreset\nreboot -f\n")
    except Exception:
        pass

def wait_for_prompt(ser, prompt="=>", timeout=30):
    buf = ""
    start = time.time()
    while time.time() - start < timeout:
        data = ser.read(ser.in_waiting or 1)
        if data:
            chunk = data.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()
            buf += chunk
            if prompt in buf or "u-boot#" in buf:
                return True
    return False

def send_uboot_cmd(ser, cmd, timeout=30):
    print(f"\n[Host Command] => {cmd}", flush=True)
    ser.write((cmd + "\n").encode('latin1'))
    time.sleep(0.1)
    buf = ""
    start = time.time()
    while time.time() - start < timeout:
        data = ser.read(ser.in_waiting or 1)
        if data:
            chunk = data.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()
            buf += chunk
            if "=>" in buf or "u-boot#" in buf:
                return True, buf
    return False, buf

def main():
    print(f"============================================================")
    print(f" {BOARD_NAME} TFTP Netboot Trial (Safe RAM Boot)")
    print(f" Target: {BOARD_NAME} ({TARGET_SSH}) via {PORT} @ {BAUD}")
    print(f" Server: {SERVER_IP}")
    print(f"============================================================", flush=True)

    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    ser.reset_input_buffer()

    # Step 1: Reboot in background thread
    t = threading.Thread(target=trigger_reboot, args=(ser,))
    t.daemon = True
    t.start()

    print("[Host] Monitoring serial console for shutdown and U-Boot autoboot prompt...", flush=True)
    buf = ""
    u_boot_interrupted = False
    start_time = time.time()

    while time.time() - start_time < 90:
        data = ser.read(ser.in_waiting or 1)
        if data:
            chunk = data.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()
            buf += chunk

            if "u-boot#" in buf or "=>" in buf:
                print("\n[Host] >>> U-BOOT PROMPT ACTIVE AND READY! <<<", flush=True)
                break

            if not u_boot_interrupted:
                if any(x in buf.lower() for x in ["autoboot", "hit any key", "stop autoboot"]):
                    print("\n[Host] >>> DETECTED AUTOBOOT! SENDING INTERRUPT KEYSTROKES... <<<", flush=True)
                    for _ in range(10):
                        ser.write(b" \n")
                        time.sleep(0.05)
                    u_boot_interrupted = True
                    buf = ""
    else:
        print("\n[Host Error] Timed out waiting for U-Boot prompt!", flush=True)
        ser.close()
        return 1

    time.sleep(1)

    # Step 2: Query U-Boot environment
    print("\n--- [Phase 2] Querying U-Boot Variables ---", flush=True)
    send_uboot_cmd(ser, "printenv kernel_addr dtb_addr initrd_addr serverip ethaddr eth1addr", timeout=5)

    # Step 3: Network & DHCP
    print("\n--- [Phase 3A] Configuring Network & DHCP ---", flush=True)
    send_uboot_cmd(ser, "setenv autoload no", timeout=5)
    ok, _ = send_uboot_cmd(ser, "dhcp", timeout=20)
    if not ok:
        print("[Host Warning] DHCP did not return prompt cleanly, retrying...", flush=True)
        send_uboot_cmd(ser, "dhcp", timeout=20)

    send_uboot_cmd(ser, f"setenv serverip {SERVER_IP}", timeout=5)

    # Step 4: TFTP Downloads
    total_steps = 2 if args.rootfs == "emmc" else 3
    print("\n--- [Phase 3B] TFTP Artifact Transfers ---", flush=True)
    print(f"[Host] 1/{total_steps}: Transferring kernel ({args.image})...", flush=True)
    ok, buf = send_uboot_cmd(ser, f"tftpboot ${{kernel_addr}} {args.image}", timeout=60)
    if not ok or "Bytes transferred" not in buf:
        print(f"[Host Error] TFTP transfer of {args.image} failed!", flush=True)
        ser.close()
        return 1

    print(f"[Host] 2/{total_steps}: Transferring device tree ({args.dtb})...", flush=True)
    ok, buf = send_uboot_cmd(ser, f"tftpboot ${{dtb_addr}} {args.dtb}", timeout=30)
    if not ok or "Bytes transferred" not in buf:
        print(f"[Host Error] TFTP transfer of {args.dtb} failed!", flush=True)
        ser.close()
        return 1

    if args.rootfs == "ram":
        print(f"[Host] 3/{total_steps}: Transferring initramfs (installer.cpio.gz)...", flush=True)
        ok, buf = send_uboot_cmd(ser, "tftpboot ${initrd_addr} installer.cpio.gz", timeout=45)
        if not ok or "Bytes transferred" not in buf:
            print("[Host Error] TFTP transfer of installer.cpio.gz failed!", flush=True)
            ser.close()
            return 1

    # Step 5: Booting Kernel
    if args.rootfs == "emmc":
        print("\n--- [Phase 4] Booting Kernel into eMMC Rootfs (/dev/mmcblk0p4) ---", flush=True)
        bootargs = "console=ttyS4,115200 root=/dev/mmcblk0p4 rw rootwait earlycon clk_ignore_unused panic=30 loglevel=4"
        send_uboot_cmd(ser, f"setenv bootargs '{bootargs}'", timeout=5)
        print(f"[Host] Executing booti ${{kernel_addr}} - ${{dtb_addr}}...", flush=True)
        ser.write(b"booti ${kernel_addr} - ${dtb_addr}\n")
    else:
        print("\n--- [Phase 4] Booting Kernel & Initramfs into RAM (Option A) ---", flush=True)
        bootargs = "console=ttyS4,115200 earlycon clk_ignore_unused panic=30"
        send_uboot_cmd(ser, f"setenv bootargs '{bootargs}'", timeout=5)
        print("[Host] Executing booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}...", flush=True)
        ser.write(b"booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}\n")

    print("\n--- [Phase 4 Console Stream] Monitoring Kernel Boot Output ---", flush=True)
    boot_start = time.time()
    monitor_duration = 75 if args.rootfs == "emmc" else 45
    while time.time() - boot_start < monitor_duration:
        data = ser.read(ser.in_waiting or 1)
        if data:
            chunk = data.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()

    print("\n\n============================================================")
    print(f"[Host] {BOARD_NAME} TFTP Netboot Stream Completed Successfully!")
    print("============================================================", flush=True)
    ser.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
