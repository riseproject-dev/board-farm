SUMMARY = "Linux Kernel for the ZhiHe A210 8-Core RISC-V SoC"
DESCRIPTION = "Mainline-based Linux kernel for ZhiHe A210 maintained by OSU-OSL"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://COPYING;md5=6bc538ed5bd9a7fc9398086aeddd7e4b"

inherit kernel

SRC_URI = "git://git.osuosl.org/osuosl/zhihe-a210-kernel.git;protocol=https;branch=osl/a210-mainline \
           file://defconfig"

# osl/a210-mainline head
SRCREV = "dba78c9a1309ef6b42ceb301cc68bb187b2f1385"

LINUX_VERSION ?= "7.2.3"
LINUX_VERSION_EXTENSION ?= "-osl"

PV = "${LINUX_VERSION}+git${SRCPV}"

COMPATIBLE_MACHINE = "zhihe-a210"

KCONFIG_MODE = "--alldefconfig"

KERNEL_DEVICETREE = "zhihe/a210-dev.dtb"
