import pytest
from labgrid import Target

def test_a210_kernel_uname(target: Target):
    ssh = target.get_driver("SSHDriver")
    target.activate(ssh)
    stdout, stderr, returncode = ssh.run("uname -s -m -r")
    assert returncode == 0
    uname_str = stdout[0].strip()
    print(f"\n[Phase 2C Board 2] Kernel: {uname_str}")
    assert "riscv64" in uname_str
    assert "Linux" in uname_str

def test_a210_cpuinfo_isa(target: Target):
    ssh = target.get_driver("SSHDriver")
    target.activate(ssh)
    stdout, stderr, returncode = ssh.run("cat /proc/cpuinfo")
    assert returncode == 0
    full_cpuinfo = "\n".join(stdout)
    assert "0x5b7" in full_cpuinfo
    assert "rv64imafdcv" in full_cpuinfo
    assert full_cpuinfo.count("processor\t:") == 8
    print("\n[Phase 2C Board 2] Verified 8x XuanTie cores")

def test_a210_network_mac(target: Target):
    ssh = target.get_driver("SSHDriver")
    target.activate(ssh)
    stdout, stderr, returncode = ssh.run("cat /sys/class/net/end0/address")
    assert returncode == 0
    mac = stdout[0].strip()
    print(f"\n[Phase 2C Board 2] Verified end0 MAC: {mac}")
    assert mac == "48:da:00:00:02:00"

def test_a210_memory(target: Target):
    ssh = target.get_driver("SSHDriver")
    target.activate(ssh)
    stdout, stderr, returncode = ssh.run("grep MemTotal /proc/meminfo")
    assert returncode == 0
    mem_total_kb = int(stdout[0].split()[1])
    mem_total_gb = mem_total_kb / 1024 / 1024
    print(f"\n[Phase 2C Board 2] Total RAM: {mem_total_gb:.2f} GB")
    assert mem_total_gb > 7.0
