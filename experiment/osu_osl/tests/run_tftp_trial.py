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

PORT = "/dev/ttyUSB1"
BAUD = 115200
SERVER_IP = "10.6.4.11"
TARGET_SSH = "root@10.6.4.13"

def trigger_reboot(ser):
    time.sleep(2)
    # Step 2: Reboot target into U-Boot
    print("\n[Host] Sending SSH reboot to root@10.6.4.13...", flush=True)
    try:
        subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "root@10.6.4.13", "reboot"],
            timeout=5,
            capture_output=True,
        )
    except Exception as e:
        print(f"[Host Note] SSH reboot result: {e}", flush=True)

    # Serial fallback: trigger reboot over serial line if target is in initramfs shell
    try:
        ser.write(b"\nreboot -f\nreboot\n")
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
            if prompt in buf:
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
    print(f" A210-2 TFTP Netboot Trial (Safe RAM Boot)")
    print(f" Target: a210-2 via {PORT} @ {BAUD}")
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

            if not u_boot_interrupted:
                if any(x in buf.lower() for x in ["autoboot", "hit any key", "stop autoboot"]):
                    print("\n[Host] >>> DETECTED AUTOBOOT! SENDING INTERRUPT KEYSTROKES... <<<", flush=True)
                    for _ in range(10):
                        ser.write(b" \n")
                        time.sleep(0.05)
                    u_boot_interrupted = True
                    buf = ""

            if u_boot_interrupted and ("u-boot#" in buf or "=>" in buf):
                print("\n[Host] >>> U-BOOT PROMPT ACTIVE AND READY! <<<", flush=True)
                break
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

    # Step 5: Booting in RAM (Option A: Safe RAM Boot, zero disk write)
    print("\n--- [Phase 4] Booting Kernel & Initramfs into RAM (Option A) ---", flush=True)
    bootargs = "console=ttyS4,115200 earlycon clk_ignore_unused panic=30"
    send_uboot_cmd(ser, f"setenv bootargs '{bootargs}'", timeout=5)

    print("[Host] Executing booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}...", flush=True)
    ser.write(b"booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}\n")

    print("\n--- [Phase 4 Console Stream] Monitoring Kernel Boot Output ---", flush=True)
    boot_start = time.time()
    while time.time() - boot_start < 45:
        data = ser.read(ser.in_waiting or 1)
        if data:
            chunk = data.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()

    print("\n\n============================================================")
    print("[Host] RAM Netboot Stream Completed Successfully!")
    print("============================================================", flush=True)
    ser.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
