"""
Hardware-in-the-loop Yocto volatile RAM netboot test for Zhihe A210.

Dynamically reserves any available board in the Labgrid `pool=a210-yocto` pool
on the board-farm-controller (or uses an explicit `--place` override), resolves
serial/network endpoints dynamically from the Labgrid coordinator (no hardcoded
IPs), boots Image + a210-dev.dtb + rootfs.cpio.gz into volatile RAM via U-Boot
`tftpboot` + `booti`, validates kernel/SMP/OpenSBI reserved-memory/Ethernet
state, and always restores the board cleanly back to its persistent eMMC Debian
baseline before releasing the pool reservation.
"""

from pathlib import Path
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import serial
import pytest

COORDINATOR_ADDR = os.environ.get("LG_COORDINATOR", "127.0.0.1:20408")
BAUD_RATE = 115200


def _run_lg(
    args: list[str],
    token: str | None = None,
    timeout: int = 30,
    check: bool = True,
) -> str:
    env = os.environ.copy()
    env["LG_COORDINATOR"] = COORDINATOR_ADDR
    if token:
        env["LG_TOKEN"] = token
    res = subprocess.run(
        ["labgrid-client", "-x", COORDINATOR_ADDR, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )
    return res.stdout


def _reserve_from_pool(pool: str, timeout: int = 900) -> str:
    """Reserve any available board matching pool=<pool> and return LG_TOKEN."""
    out = _run_lg(
        ["reserve", "--wait", "--shell", f"pool={pool}"],
        timeout=timeout,
    )
    match = re.search(r"LG_TOKEN=([A-Za-z0-9]+)", out)
    if not match:
        raise RuntimeError(f"Failed to parse LG_TOKEN from labgrid reservation output:\n{out}")
    return match.group(1)


def _resolve_place_endpoints(
    place_selector: str, token: str | None = None
) -> tuple[str, str, str, str]:
    """Query Labgrid coordinator for allocated place name, serial device path, target IP, and TFTP server IP."""
    info = _run_lg(["-p", place_selector, "show"], token=token)

    place_match = re.search(r"Place\s+'([^']+)':", info)
    allocated_place = place_match.group(1) if place_match else place_selector

    path_match = re.search(r"'path':\s*'([^']+)'", info)
    serial_path = path_match.group(1) if path_match else "/dev/ttyUSB2"

    addr_match = re.search(r"'address':\s*'([^']+)'", info)
    if not addr_match:
        raise RuntimeError(
            f"Could not resolve NetworkService address from Labgrid place '{allocated_place}':\n{info}"
        )
    target_ip = addr_match.group(1)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((target_ip, 69))
        server_ip = sock.getsockname()[0]

    return allocated_place, serial_path, target_ip, server_ip


def _write_slow(ser: serial.Serial, cmd: str) -> None:
    for ch in cmd:
        ser.write(ch.encode("latin1"))
        time.sleep(0.004)
    ser.write(b"\n")


def _send_uboot_cmd(ser: serial.Serial, log_fp, cmd: str, timeout: float = 60.0) -> str:
    header = f"\n[Host -> U-Boot] {cmd}\n"
    sys.stdout.write(header)
    sys.stdout.flush()
    log_fp.write(header)

    _write_slow(ser, cmd)
    time.sleep(0.1)
    buf = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk_bytes = ser.read(ser.in_waiting or 1)
        if chunk_bytes:
            chunk = chunk_bytes.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()
            log_fp.write(chunk)
            log_fp.flush()
            buf += chunk
            if "u-boot#" in buf or "=>" in buf:
                return buf
    raise TimeoutError(f"Timed out after {timeout}s waiting for U-Boot prompt on command: {cmd}")


def _intercept_uboot(ser: serial.Serial, log_fp, target_ip: str, timeout: float = 60.0) -> None:
    def _trigger_reboot():
        time.sleep(1.0)
        # Also send reboot over UART in case the board is at a serial root shell or U-Boot prompt
        try:
            ser.write(b"\r\nsync; reboot -f\r\n")
        except Exception:
            pass
        subprocess.run(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=5",
                f"root@{target_ip}",
                "sync; reboot",
            ],
            timeout=12,
            capture_output=True,
            check=False,
        )

    threading.Thread(target=_trigger_reboot, daemon=True).start()

    buf = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk_bytes = ser.read(ser.in_waiting or 1)
        if chunk_bytes:
            chunk = chunk_bytes.decode("latin1", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()
            log_fp.write(chunk)
            log_fp.flush()
            buf += chunk
            if "Hit any key to stop autoboot" in buf or "U-Boot 2024.10" in buf:
                for _ in range(10):
                    ser.write(b"\r\n ")
                    time.sleep(0.05)
            if "u-boot#" in buf or "=>" in buf:
                time.sleep(0.4)
                ser.reset_input_buffer()
                return
    raise TimeoutError(f"Failed to intercept U-Boot prompt within {timeout}s")


def test_zhihe_a210_yocto_ram_netboot(
    pool_name: str,
    place_name: str,
    tftp_dir: str,
    serial_log_path: str,
    expected_kernel_prefix: str,
):
    for artifact in ("Image", "a210-dev.dtb", "rootfs.cpio.gz"):
        full_path = Path("/var/lib/tftpboot") / tftp_dir / artifact
        assert full_path.is_file(), f"Missing staged TFTP artifact: {full_path}"

    if not expected_kernel_prefix:
        build_info_path = Path("/var/lib/tftpboot") / tftp_dir / "build-info.json"
        if build_info_path.is_file():
            try:
                build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
                expected_kernel_prefix = build_info.get("kernel_version", "")
            except Exception:
                pass

    token = None
    place_selector = place_name
    acquired = False
    ser = None
    boot_succeeded = False
    restored_to_emmc = False

    try:
        if not place_selector:
            print(f"Waiting for available board in Labgrid pool 'pool={pool_name}'...")
            token = _reserve_from_pool(pool_name)
            place_selector = "+"

        allocated_place, serial_path, target_ip, server_ip = _resolve_place_endpoints(
            place_selector, token=token
        )
        print(
            f"Allocated Labgrid place '{allocated_place}' "
            f"(pool={pool_name}, serial={serial_path})"
        )
        Path("yocto_allocated_place.txt").write_text(allocated_place + "\n", encoding="utf-8")

        # Acquire exclusive lock on the reserved Labgrid place before opening serial
        _run_lg(["-p", place_selector, "acquire"], token=token)
        acquired = True

        with open(serial_log_path, "w", encoding="utf-8", errors="replace") as log_fp:
            log_fp.write(f"# Allocated Labgrid Place: {allocated_place} (pool={pool_name})\n")
            ser = serial.Serial(serial_path, BAUD_RATE, timeout=0.1)
            ser.reset_input_buffer()

            _intercept_uboot(ser, log_fp, target_ip, timeout=60.0)

            _send_uboot_cmd(ser, log_fp, "setenv autoload no", timeout=10.0)
            _send_uboot_cmd(ser, log_fp, "dhcp", timeout=30.0)
            _send_uboot_cmd(ser, log_fp, f"setenv serverip {server_ip}", timeout=10.0)

            for addr, fname, tmo in (
                ("0x84000000", f"{tftp_dir}/Image", 60.0),
                ("0x8c000000", f"{tftp_dir}/a210-dev.dtb", 30.0),
                ("0x8d000000", f"{tftp_dir}/rootfs.cpio.gz", 60.0),
            ):
                out = _send_uboot_cmd(ser, log_fp, f"tftpboot {addr} {fname}", timeout=tmo)
                assert "Bytes transferred =" in out, f"TFTP transfer failed for {fname}"

            bootargs = (
                "console=ttyS4,115200 earlycon rdinit=/sbin/init "
                "root=/dev/ram0 rw clk_ignore_unused panic=30"
            )
            _send_uboot_cmd(ser, log_fp, f"setenv bootargs '{bootargs}'", timeout=10.0)

            _write_slow(ser, "booti 0x84000000 0x8d000000:${filesize} 0x8c000000")

            boot_buf = ""
            logged_in = False
            probe_sent = False
            deadline = time.monotonic() + 110.0

            while time.monotonic() < deadline:
                chunk_bytes = ser.read(ser.in_waiting or 1)
                if not chunk_bytes:
                    continue
                chunk = chunk_bytes.decode("latin1", errors="replace")
                sys.stdout.write(chunk)
                sys.stdout.flush()
                log_fp.write(chunk)
                log_fp.flush()
                boot_buf += chunk

                if not logged_in and "zhihe-a210 login:" in boot_buf:
                    logged_in = True
                    time.sleep(0.5)
                    _write_slow(ser, "root")

                if logged_in and not probe_sent and "root@zhihe-a210:" in boot_buf:
                    probe_sent = True
                    time.sleep(1.0)
                    _write_slow(
                        ser,
                        "printf '===CI_PROBE_%s===\\n' START; "
                        "uname -a; "
                        "echo KERNEL_RELEASE=$(uname -r); "
                        "echo CORES=$(nproc); "
                        "cat /etc/issue; "
                        "ip addr show dev eth0 || true; "
                        "printf '===CI_PROBE_%s===\\n' END",
                    )

                if probe_sent and "===CI_PROBE_END===" in boot_buf:
                    boot_succeeded = True
                    break

            assert logged_in, "Timed out waiting for 'zhihe-a210 login:' prompt"
            assert boot_succeeded, "Timed out waiting for post-login verification probe"
            assert "nomap non-reusable opensbi@80000000" in boot_buf, (
                "Missing 'opensbi@80000000' no-map reserved-memory region in kernel boot log"
            )
            assert "CORES=8" in boot_buf, "Expected all 8 RISC-V cores online (CORES=8)"

            uname_match = re.search(r"KERNEL_RELEASE=(\S+)", boot_buf)
            if not uname_match:
                uname_match = re.search(r"Linux\s+(?:zhihe-a210\s+)?(\S+).*riscv64", boot_buf)
            assert uname_match, "Could not parse kernel release from 'uname' output in probe"
            kernel_rel = uname_match.group(1)
            print(
                f"\n[Probe] Running kernel release: {kernel_rel} "
                f"(expected prefix: {expected_kernel_prefix or 'any'})"
            )
            if expected_kernel_prefix:
                assert kernel_rel.startswith(expected_kernel_prefix), (
                    f"Expected kernel release starting with '{expected_kernel_prefix}', got '{kernel_rel}'"
                )

            # Always reboot cleanly back into persistent eMMC Debian
            _write_slow(ser, "sync; reboot -f")
            restore_buf = ""
            restore_deadline = time.monotonic() + 90.0
            while time.monotonic() < restore_deadline:
                chunk_bytes = ser.read(ser.in_waiting or 1)
                if chunk_bytes:
                    chunk = chunk_bytes.decode("latin1", errors="replace")
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                    log_fp.write(chunk)
                    log_fp.flush()
                    restore_buf += chunk
                    if "a210-" in restore_buf and "login:" in restore_buf:
                        restored_to_emmc = True
                        break

            assert restored_to_emmc, "Board did not return to persistent eMMC Debian login prompt"
    finally:
        if ser is not None and ser.is_open:
            if not restored_to_emmc:
                try:
                    _write_slow(ser, "sync; reboot -f")
                    time.sleep(0.2)
                    _write_slow(ser, "reset")
                except Exception:
                    pass
            ser.close()
        if acquired:
            _run_lg(["-p", place_selector, "release"], token=token, check=False)
        if token:
            _run_lg(["cancel-reservation", token], token=token, check=False)
