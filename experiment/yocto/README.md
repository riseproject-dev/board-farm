# ZhiHe A210 Yocto BSP Experiment (`meta-zhihe`)

This directory contains the standalone Yocto Board Support Package (BSP) layer (`meta-zhihe`) and automated TFTP netboot trial scripts for the **ZhiHe A210 RISC-V SoC** (8-core XuanTie C920/C908 @ 1.896 GHz).

---

## 1. Directory Structure

```text
experiment/yocto/
├── meta-zhihe/
│   ├── conf/
│   │   ├── layer.conf
│   │   └── machine/
│   │       └── zhihe-a210.conf
│   └── recipes-core/
│       └── images/
│           └── core-image-minimal.bbappend
├── run_yocto_trial.py
└── README.md
```

---

## 2. BSP Layer Highlights (`meta-zhihe`)

* **Layer Compatibility**: Yocto Project / Poky **Scarthgap** (5.0.x LTS).
* **Target Architecture**: 64-bit RISC-V with ratified Vector 1.0 (`-march=rv64gcv -mabi=lp64d`).
* **Console Routing**: Serial UART on `/dev/ttyS4` @ 115200 baud (matching the A210 hardware debug header pinout).
* **Decoupled Kernel Provider**: Sets `PREFERRED_PROVIDER_virtual/kernel = "linux-dummy"` to allow building modular userspace root filesystems that boot alongside verified kernel images (`Image` + `a210-dev.dtb`).
* **Netboot Hook**: Includes `recipes-core/images/core-image-minimal.bbappend` to symlink `/init -> /sbin/init` for in-memory initramfs boots.
* **Footprint**: Generates a self-contained, lightweight ~5.0 MB compressed root filesystem (`core-image-minimal-zhihe-a210.rootfs.cpio.gz`).

---

## 3. How to Build with Poky & BitBake

### Prerequisites
Clone Poky (Scarthgap branch) and `meta-riscv`:

```bash
mkdir -p yocto-workspace && cd yocto-workspace
git clone -b scarthgap git://git.yoctoproject.org/poky
git clone -b scarthgap https://github.com/riscv/meta-riscv.git
cp -r /path/to/board-farm/experiment/yocto/meta-zhihe .
```

### Initialize Build Environment
```bash
source poky/oe-init-build-env build

bitbake-layers add-layer ../meta-riscv
bitbake-layers add-layer ../meta-zhihe
```

### Configure Machine (`conf/local.conf`)
Ensure `conf/local.conf` targets the ZhiHe A210 machine:
```bitbake
MACHINE ??= "zhihe-a210"
```

### Run the Build
```bash
bitbake core-image-minimal
```

The output artifact is generated at:
```text
build/tmp/deploy/images/zhihe-a210/core-image-minimal-zhihe-a210.rootfs.cpio.gz
```

---

## 4. In-Memory RAM Netboot on Physical Hardware

Testing is performed **strictly in RAM** via TFTP netboot (`booti`), ensuring zero destructive writes to the board's on-board eMMC storage (`/dev/mmcblk0p4`, Debian):

### Manual U-Boot Sequence
From the board's serial console (`/dev/ttyS4` @ 115200):
```text
dhcp
setenv serverip <TFTP_SERVER_IP>
tftpboot ${kernel_addr} Image
tftpboot ${dtb_addr} a210-dev.dtb
tftpboot ${initrd_addr} yocto-rootfs.cpio.gz
setenv bootargs 'console=ttyS4,115200 earlycon clk_ignore_unused panic=30'
booti ${kernel_addr} ${initrd_addr}:${filesize} ${dtb_addr}
```

### Automated Trial Runner
An automated runner script is included to intercept U-Boot over the serial gateway, transfer artifacts over TFTP, boot into RAM, verify the login shell, and cleanly reboot:

```bash
python3 run_yocto_trial.py --board a210-board-04 --initrd yocto-rootfs.cpio.gz
```
