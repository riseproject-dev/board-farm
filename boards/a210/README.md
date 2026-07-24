# Alibaba Zhihe A210 Board Specification & Bring-Up Notes

*Note: For the official compliance state covering hardware provisioning, vendor binary management, and firmware upstreaming, please see the [A210 Compliance Checklist](compliance-checklist.md).*

## 1. Hardware Overview
* **Processor Architecture:** [Octa-core RISC-V 64GCV (4×C920 @ 1.9GHz + 4×C908 @ 1.9GHz)](https://developer.zhcomputing.com/en/docs/A210/A210_Datasheet/), targeting RVA23 capability testing.
* **Additional Compute:** 12 TOPS INT8 NPU and 50.34 GFLOPS GPU.
* **Memory Pipeline:** Up to 16GB LPDDR4/LPDDR4X.

---

## 2. Public Source Code Mirrors (RISE Board Farm)

For the Alibaba Zhihe A210, low-level firmware components and Linux kernel builds are open-sourced and mirrored at RISE Board Farm, but have yet to be upstreamed to their respective mainline repositories:

* **OpenSBI:** [https://git.osuosl.org/osuosl/zhihe-a210-opensbi](https://git.osuosl.org/osuosl/zhihe-a210-opensbi)
* **U-Boot:** [https://git.osuosl.org/osuosl/zhihe-a210-u-boot](https://git.osuosl.org/osuosl/zhihe-a210-u-boot)
* **Buildroot:** [https://git.osuosl.org/osuosl/zhihe-a210-buildroot](https://git.osuosl.org/osuosl/zhihe-a210-buildroot)
* **Linux Kernel:** [https://git.osuosl.org/osuosl/a210-linux](https://git.osuosl.org/osuosl/a210-linux)

---

## 3. Useful Links
* [Board farm onboarding status, notes and docs](https://git.osuosl.org/osuosl/a210-linux/-/tree/main/docs?ref_type=heads)
