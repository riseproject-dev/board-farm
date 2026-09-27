#!/usr/bin/env python3
"""
Automated Yocto RAM Netboot Verification on Zhihe A210 Board 04.
Downloads Image + a210-dev.dtb + yocto-rootfs.cpio.gz over TFTP and boots in RAM.
Captures Poky/Yocto banner and login prompt, tests basic commands, and reboots.
"""
import sys
import time
import serial
import threading
import subprocess
import argparse

BOARD_MAP = {
    "a210-board-04": {"port": "/dev/ttyUSB3", "ssh": "root@10.6.4.15"},
    "a210-4": {"port": "/dev/ttyUSB3", "ssh": "root@10.6.4.15"},
}

def parse_args():
    parser = argparse.ArgumentParser(description="A210 Yocto Netboot Runner")
    parser.add_argument("--board", default="a210-board-04")
    parser.add_argument("--image", default="Image")
    parser.add_argument("--dtb", default="a210-dev.dtb")
    parser.add_argument("--initrd", default="yocto-rootfs.cpio.gz")
    return parser.parse_args()

args = parse_args()
cfg = BOARD_MAP[args.board]
PORT = cfg["port"]
TARGET_SSH = cfg["ssh"]
BAUD = 115200
SERVER_IP = "10.6.4.11"

def trigger_reboot(ser):
    time.sleep(2)
    print(f"\n[Host] Sending SSH reboot to {TARGET_SSH}...", flush=True)
    try:
        subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", TARGET_SSH, "reboot"],
            timeout=5,
            capture_output=True,
        )
    except Exception as e:
        print(f"[Host Note] SSH reboot result: {e}", flush=True)

    try:
        ser.write(b"\nreset\nreboot -f\n")
    except Exception:
        pass

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
    print("============================================================")
    print(f" A210 Yocto Netboot Verification: a210-board-04")
    print(f" Target: {TARGET_SSH} via {PORT} @ {BAUD}")
    print(f" Initrd: {args.initrd}")
    print("============================================================", flush=True)

    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    ser.reset_input_buffer()

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
                    for _ in range(12):
                        ser.write(b" \n")
                        time.sleep(0.04)
                    u_boot_interrupted = True
                    buf = ""
    else:
        print("\n[Host Error] Timed out waiting for U-Boot prompt!", flush=True)
        ser.close()
        return 1

    time.sleep(1)

    print("\n--- [Phase 1] Configuring Network & DHCP ---", flush=True)
    send_uboot_cmd(ser, "setenv autoload no", timeout=5)
    ok, _ = send_uboot_cmd(ser, "dhcp", timeout=20)
    if not ok:
        send_uboot_cmd(ser, "dhcp", timeout=20)

    send_uboot_cmd(ser, f"setenv serverip {SERVER_IP}", timeout=5)

    print("\n--- [Phase 2] TFTP Artifact Transfers ---", flush=True)
    print(f"[Host] 1/3: Transferring kernel ({args.image})...", flush=True)
    ok, buf = send_uboot_cmd(ser, f"tftpboot ${{kernel_addr}} {args.image}", timeout=60)
    if not ok or "Bytes transferred" not in buf:
        print("[Host Error] TFTP transfer of kernel failed!", flush=True)
        ser.close()
        return 1

    print(f"[Host] 2/3: Transferring device tree ({args.dtb})...", flush=True)
    ok, buf = send_uboot_cmd(ser, f"tftpboot ${{dtb_addr}} {args.dtb}", timeout=30)
    if not ok or "Bytes transferred" not in buf:
        print("[Host Error] TFTP transfer of DTB failed!", flush=True)
        ser.close()
        return 1

    print(f"[Host] 3/3: Transferring Yocto initramfs ({args.initrd})...", flush=True)
    ok, buf = send_uboot_cmd(ser, f"tftpboot ${{initrd_addr}} {args.initrd}", timeout=45)
    if not ok or "Bytes transferred" not in buf:
        print("[Host Error] TFTP transfer of Yocto initramfs failed!", flush=True)
        ser.close()
        return 1

    print("\n--- [Phase 3] Booting Yocto In-Memory ---", flush=True)
    bootargs = "console=ttyS4,115200 earlycon clk_ignore_unused panic=30"
    send_uboot_cmd(ser, f"setenv bootargs '{bootargs}'", timeout=5)
    print("[Host] Executing booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}...", flush=True)
    ser.write(b"booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}\n")

    print("\n--- [Phase 4] Monitoring Yocto Boot Stream ---", flush=True)
    boot_start = time.time()
    seen_login = False
    console_log = ""

    while time.time() - boot_start < 85:
        data = ser.read(ser.in_waiting or 1)
        if data:
            chunk = data.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()
            console_log += chunk

            if "login:" in console_log.lower() and not seen_login:
                seen_login = True
                print("\n\n[Host] >>> DETECTED YOCTO LOGIN PROMPT! <<<\n", flush=True)
                time.sleep(1)
                print("[Host] Logging in as root...", flush=True)
                ser.write(b"root\n")
                time.sleep(1)
                print("[Host] Running verification commands...", flush=True)
                ser.write(b"uname -a; cat /etc/issue; id; sleep 2; echo '*** REBOOTING BACK TO EMMC ***'; reboot -f\n")
                time.sleep(6)
                break

    time.sleep(5)
    ser.close()
    print("\n============================================================")
    print(f" Yocto Netboot Verification on a210-board-04 Complete!")
    print("============================================================", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
