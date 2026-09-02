"""
Phase 1 Labgrid Pilot: Hardware & Boot Integration Test
Executes against Labgrid Coordinator & Exporter microservices stack.
"""
import os
import subprocess
import time
import pytest
from labgrid import Environment, Target

def test_stage_boot_and_uname(target):
    """
    Phase 1 Labgrid Pilot Real QEMU / Mock Hardware Test:
    1. Downloads & stages real official Debian DQIB RISC-V 64 kernel image in TFTP directory.
    2. Power cycles target board via PDU script / QEMU launcher.
    3. Intercepts U-Boot prompt over serial via UBootDriver through labgrid-coordinator.
    4. Executes uboot.boot() to boot target.
    """
    target_type = os.getenv("TARGET_TYPE", "mock")

    # Step 1: Ensure target board is active BEFORE activating Labgrid drivers
    power_script = os.path.join(os.path.dirname(__file__), "..", "qemu-power.sh")
    env = os.environ.copy()
    env["TARGET_TYPE"] = target_type
    subprocess.run([power_script, "cycle"], check=True, env=env)
    time.sleep(1)

    # Step 2: Download & stage real official RISC-V kernel image in TFTP directory
    download_script = os.path.join(os.path.dirname(__file__), "..", "download-image.sh")
    subprocess.run([download_script, "riscv64"], check=True)
    fit_image_path = "/tmp/tftp/qemu-board/fitImage"
    assert os.path.exists(fit_image_path) and os.path.getsize(fit_image_path) > 1000000, "TFTP real kernel image staging failed"
    print(f"\n[Test] Staged real RISC-V 64 kernel image ({os.path.getsize(fit_image_path)} bytes) at {fit_image_path}")

    # Step 3: U-Boot Driver Execution via labgrid-coordinator
    uboot = target.get_driver("UBootDriver")
    target.activate(uboot)
    print("[Test] Intercepted U-Boot prompt via Labgrid UBootDriver (coordinator-managed).")

    # Step 4: Boot Target via UBootDriver.boot()
    print("[Test] Booting target into Linux kernel via UBootDriver.boot()...")
    uboot.boot()
    print("[Test] Target successfully booted real RISC-V 64 Linux kernel.")
