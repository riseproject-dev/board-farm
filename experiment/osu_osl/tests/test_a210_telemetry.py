import pytest
from labgrid import Target

def test_a210_kernel_uname(target: Target):
    """Verify kernel release and architecture on live A210 hardware."""
    ssh = target.get_driver("SSHDriver")
    target.activate(ssh)

    stdout, stderr, returncode = ssh.run("uname -s -m -r")
    assert returncode == 0, f"uname failed: {stderr}"
    uname_str = stdout[0].strip()
    print(f"\n[Phase 2C] Kernel Uname: {uname_str}")
    assert "riscv64" in uname_str, "Target is not riscv64"
    assert "Linux" in uname_str, "Target is not Linux"

def test_a210_cpuinfo_isa(target: Target):
    """Verify Alibaba XuanTie C920/C908 Octa-core CPU and RISC-V extensions."""
    ssh = target.get_driver("SSHDriver")
    target.activate(ssh)

    stdout, stderr, returncode = ssh.run("cat /proc/cpuinfo")
    assert returncode == 0
    full_cpuinfo = "\n".join(stdout)

    # Verify vendor ID 0x5b7 (T-Head / Alibaba)
    assert "mvendorid" in full_cpuinfo and "0x5b7" in full_cpuinfo, "Missing T-Head mvendorid (0x5b7)"
    assert "rv64imafdcv" in full_cpuinfo, "Missing rv64imafdcv extensions"
    assert full_cpuinfo.count("processor\t:") == 8, f"Expected 8 cores, found {full_cpuinfo.count('processor\t:')}"
    print("\n[Phase 2C] Verified 8x XuanTie cores with rv64imafdcv extensions")

def test_a210_network_mac(target: Target):
    """Verify physical end0 Ethernet MAC address prefix for OSU-OSL A210 cluster."""
    ssh = target.get_driver("SSHDriver")
    target.activate(ssh)

    stdout, stderr, returncode = ssh.run("cat /sys/class/net/end0/address")
    assert returncode == 0
    mac = stdout[0].strip()
    print(f"\n[Phase 2C] Verified end0 MAC address: {mac}")
    assert mac.startswith("48:da:00:00:"), f"Unexpected MAC: {mac}"

def test_a210_memory(target: Target):
    """Verify physical RAM capacity (>7GB)."""
    ssh = target.get_driver("SSHDriver")
    target.activate(ssh)

    stdout, stderr, returncode = ssh.run("grep MemTotal /proc/meminfo")
    assert returncode == 0
    mem_total_kb = int(stdout[0].split()[1])
    mem_total_gb = mem_total_kb / 1024 / 1024
    print(f"\n[Phase 2C] Total RAM: {mem_total_gb:.2f} GB")
    assert mem_total_gb > 7.0, f"Memory capacity too low: {mem_total_gb} GB"
