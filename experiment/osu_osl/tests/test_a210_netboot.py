import os
import subprocess
import time
import pytest
from labgrid import Target

DEFAULT_SERVER_IP = os.environ.get("TFTP_SERVER_IP", "10.6.4.11")

def test_a210_uboot_tftp_netboot(target: Target):
    print("\n[Labgrid Netboot] Triggering reboot via SSH...")
    try:
        ssh = target.get_driver("SSHDriver")
        target.activate(ssh)
        ssh.run("reboot")
    except Exception as e:
        print(f"[SSH Reboot] SSH reset sent or connection closed as expected: {e}")

    print("[Labgrid Netboot] Activating native Labgrid UBootDriver...")
    uboot = target.get_driver("UBootDriver")
    target.activate(uboot)
    
    print("[Labgrid UBootDriver] Intercepted U-Boot! Checking version...")
    res = uboot.run("version")
    print(f"[U-Boot Version] {res[0] if res else 'OK'}")
    
    print("[Labgrid UBootDriver] Running DHCP...")
    uboot.run("setenv autoload no")
    uboot.run("dhcp")
    uboot.run(f"setenv serverip {DEFAULT_SERVER_IP}")
    
    print("[Labgrid UBootDriver] Fetching artifacts via TFTP...")
    uboot.run("tftpboot ${kernel_addr} Image", timeout=45)
    uboot.run("tftpboot ${dtb_addr} a210-dev.dtb", timeout=20)
    uboot.run("tftpboot ${initrd_addr} installer.cpio.gz", timeout=45)
    
    print("[Labgrid UBootDriver] TFTP downloads complete! Booting RAM kernel...")
    uboot.run("setenv bootargs 'console=ttyS4,115200 earlycon clk_ignore_unused panic=30'")
    uboot.run("booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}")
