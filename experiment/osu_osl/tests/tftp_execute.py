#!/usr/bin/env python3
"""
Executes TFTP RAM Netboot on an A210 board via U-Boot serial console.
"""
import os
import sys
import time
import argparse
import serial

DEFAULT_PORT = os.environ.get("A210_SERIAL_PORT", "/dev/ttyUSB1")
DEFAULT_SERVER_IP = os.environ.get("TFTP_SERVER_IP", "10.6.4.11")
DEFAULT_BAUD = int(os.environ.get("A210_BAUD_RATE", "115200"))

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
            if "u-boot#" in buf or "=>" in buf:
                return True, buf
    return False, buf

def main():
    parser = argparse.ArgumentParser(description="A210 U-Boot TFTP RAM Netboot Executor")
    parser.add_argument("--port", default=DEFAULT_PORT, help="Serial TTY port (default: %(default)s)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate (default: %(default)s)")
    parser.add_argument("--server-ip", default=DEFAULT_SERVER_IP, help="TFTP server IP (default: %(default)s)")
    args = parser.parse_args()

    print("============================================================")
    print(f" Executing TFTP Netboot on {args.port} (Server: {args.server_ip})")
    print("============================================================", flush=True)

    ser = serial.Serial(args.port, args.baud, timeout=0.1)
    ser.reset_input_buffer()

    # Wake up prompt
    print("[Host] Checking U-Boot prompt responsiveness...", flush=True)
    ser.write(b"\n")
    time.sleep(0.5)
    resp = ser.read(ser.in_waiting or 1).decode("latin1", errors="replace")
    sys.stdout.write(resp)
    sys.stdout.flush()

    # Step 1: Query U-Boot Variables
    print("\n--- [Phase 2] Querying U-Boot Variables ---", flush=True)
    send_uboot_cmd(ser, "printenv kernel_addr dtb_addr initrd_addr serverip ethaddr eth1addr", timeout=5)

    # Step 2: Configure Network & DHCP
    print("\n--- [Phase 3A] Configuring Network & DHCP ---", flush=True)
    send_uboot_cmd(ser, "setenv autoload no", timeout=5)
    ok, buf = send_uboot_cmd(ser, "dhcp", timeout=25)
    if "DHCP client bound to address" not in buf:
        print("[Host Note] Retrying DHCP...", flush=True)
        send_uboot_cmd(ser, "dhcp", timeout=25)

    send_uboot_cmd(ser, f"setenv serverip {args.server_ip}", timeout=5)

    # Step 3: TFTP Artifact Transfers
    print("\n--- [Phase 3B] TFTP Artifact Transfers ---", flush=True)
    print("[Host] 1/3: Transferring kernel (Image)...", flush=True)
    ok, buf = send_uboot_cmd(ser, "tftpboot ${kernel_addr} Image", timeout=45)
    if not ok or "Bytes transferred" not in buf:
        print("[Host Error] TFTP transfer of Image failed!", flush=True)
        ser.close()
        return 1

    print("[Host] 2/3: Transferring device tree (a210-dev.dtb)...", flush=True)
    ok, buf = send_uboot_cmd(ser, "tftpboot ${dtb_addr} a210-dev.dtb", timeout=20)
    if not ok or "Bytes transferred" not in buf:
        print("[Host Error] TFTP transfer of a210-dev.dtb failed!", flush=True)
        ser.close()
        return 1

    print("[Host] 3/3: Transferring initramfs (installer.cpio.gz)...", flush=True)
    ok, buf = send_uboot_cmd(ser, "tftpboot ${initrd_addr} installer.cpio.gz", timeout=45)
    if not ok or "Bytes transferred" not in buf:
        print("[Host Error] TFTP transfer of installer.cpio.gz failed!", flush=True)
        ser.close()
        return 1

    # Step 4: Boot in RAM (Safe RAM Netboot)
    print("\n--- [Phase 4] Booting Kernel & Initramfs in RAM ---", flush=True)
    bootargs = "console=ttyS4,115200 earlycon clk_ignore_unused panic=30"
    send_uboot_cmd(ser, f"setenv bootargs '{bootargs}'", timeout=5)

    print("[Host] Executing: booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}...", flush=True)
    ser.write(b"booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}\n")

    print("\n--- [Phase 4 Console Stream] Monitoring Live Kernel Boot ---", flush=True)
    boot_start = time.time()
    while time.time() - boot_start < 45:
        data = ser.read(ser.in_waiting or 1)
        if data:
            chunk = data.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()

    print("\n\n============================================================")
    print("[Host] RAM Netboot Stream Completed!")
    print("============================================================", flush=True)
    ser.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
