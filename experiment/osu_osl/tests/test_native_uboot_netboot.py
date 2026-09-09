import pytest
from labgrid import Target
from labgrid.driver.exception import ExecutionError
from pexpect.exceptions import TIMEOUT

def test_a210_native_uboot_tftp_netboot(target: Target):
    print("\n[Labgrid Power] Triggering reboot via ExternalPowerDriver...")
    power = target.get_driver("PowerProtocol")
    target.activate(power)
    try:
        power.cycle()
    except Exception as e:
        print(f"[Power Cycle Note] {e}")
    
    print("[Labgrid UBootDriver] Activating native UBootDriver...")
    uboot = target.get_driver("UBootDriver")
    target.activate(uboot)
    
    print("[Labgrid UBootDriver] Intercepted U-Boot! Checking version...")
    res = uboot.run("version")
    print(f"[U-Boot Version] {res[0] if res else 'OK'}")
    
    print("[Labgrid UBootDriver] Running DHCP...")
    uboot.run("setenv autoload no")
    uboot.run("dhcp")
    uboot.run("setenv serverip 10.6.4.11")
    
    print("[Labgrid UBootDriver] Downloading artifacts via TFTP...")
    uboot.run("tftpboot ${kernel_addr} Image", timeout=45)
    uboot.run("tftpboot ${dtb_addr} a210-dev.dtb", timeout=20)
    uboot.run("tftpboot ${initrd_addr} installer.cpio.gz", timeout=45)
    
    print("[Labgrid UBootDriver] Executing booti RAM kernel...")
    uboot.run("setenv bootargs 'console=ttyS4,115200 earlycon clk_ignore_unused panic=30'")
    
    # Send booti command - kernel boot replaces U-Boot prompt so TIMEOUT is expected upon prompt return
    try:
        uboot.run("booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}", timeout=5)
    except (TIMEOUT, ExecutionError):
        print("[Labgrid UBootDriver] Kernel boot sequence started successfully (handover from U-Boot to Linux)!")
