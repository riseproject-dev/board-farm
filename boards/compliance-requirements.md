# RISE Target Hardware Onboarding & Upstreaming Compliance Policy

## 1. Overview

The RISE Project adheres to a collaborative, upstream-first open-source philosophy. Physical hardware integrated into the **RISE Board Farm** moves through a progressive, phased compliance framework anchored around **Lab Integration & Access Stages**. 

This policy provides access to engineering samples while establishing clear operational and upstreaming gates for hardware to progress into shared CI pools and production bare-metal pools. Compliance with these gates and binary blob sunset clauses is strictly enforced; stage progression is independently evaluated and approved by the **RISE Developer Tooling WG** and the **Board Farm Maintainers**.

---

## 2. Phased Onboarding Framework (Lab Integration Stages)

Target boards progress through three distinct Lab Integration Stages. For each stage, the policy outlines a vendor requirement checklist and the corresponding Board Farm support and services provided:

---

### Stage 1: Isolated Bring-up Bench

* **Target Scope:** Initial lab bring-up, prototype staging, and early hardware enablement.
* **Vendor Requirements Checklist:**
  * **Hardware & Physical Checklist:**
    * [ ] **Physical Hardware:** Supply 1–2 working prototype or engineering sample units to the RISE Board Farm.
    * [ ] **Hardware Documentation & Specs:** Provide board schematics, SoC memory maps, block diagrams, jumper configurations, and component datasheets.
    * [ ] **Mechanical & Thermal Specs:** Document exact mechanical clearance, dimensional constraints, and thermal/airflow expectations for racked continuous operation.
    * [ ] **Power Envelope:** Document peak/instantaneous power consumption under simultaneous all-cores + NPU/GPU stress to ensure safe PDU sizing.
    * [ ] **Physical Modifications:** Document any mandatory physical pad soldering or board surgery needed to access remote power/reset circuits or specific I/O connectors.
    * [ ] **Network & Console Interfaces:** Dedicated network interface supporting standard DHCP and U-Boot network boot methods (TFTP/PXE). Out-of-band UART interface with documented baud rate and parity settings (standard 3-pin TX/RX/GND).
    * [ ] **Out-of-Band Management:** Boards MUST automatically initialize and boot upon power restoration OR expose accessible header pins/jumpers for simple external relay control if front-panel power button presses are required (without necessitating complex hardware modifications).
  * **Firmware & Bootloader Checklist:**
    * [ ] **Firmware & Bootloader Source:** Provide functional prebuilt binaries, build instructions, and public or private source repositories for OpenSBI and U-Boot capable of reaching a boot prompt.
    * [ ] **Remote Flashing & DFU Recovery:** Supply recovery binaries, flashing scripts, and operational mechanisms to reliably trigger DFU/bootrom recovery mode remotely (e.g., via software triggers or debug harnesses, without requiring physical touch or configuration) to facilitate zero-touch firmware updates.
    * [ ] **MAC Address Persistence:** Document non-volatile storage mechanisms (e.g., U-Boot `fnv` storage) for preserving deterministic MAC addresses across reflashes.
    * [ ] **Prebuilt Bootline Blobs:** Temporary prebuilt core bootline blobs (e.g., OpenSBI, U-Boot) and proprietary co-processor firmware are fully permitted during initial bench bring-up.
  * **Linux Kernel Checklist:**
    * [ ] **Kernel Enablement:** Out-of-tree vendor kernel forks (e.g., Linux 6.1/6.6 vendor trees) are permitted for early bring-up, but not preferred. Vendors must grant repository access or supply kernel patches/trees to Board Farm maintainers.
  * **RISC-V Architecture Checklist:**
    * [ ] **ISA & Extensions:** Clearly define and document the supported RISC-V ISA and hardware extensions (e.g., RVA22 with RVV 1.0).

* **Board Farm Support & Services Provided:**
  * **Private Lab Staging:** Dedicated host exporter allocation on an isolated, firewalled VLAN (boards can fetch from the internet but cannot communicate with the broader Board Farm).
  * **Restricted Access Control:** Interactive SSH access via a secured jump host (bastion). Access is strictly restricted to core maintainers and vendor engineers for early bench bring-up.
  * **Remote Operations Tooling:** Automated serial console logging and remote power control (PDU socket control and optional power-button relay bypass). Vendors and core maintainers are empowered with self-serve command execution (via the provided control plane on the jump host) to power-cycle their boards independently.

---

### Stage 2: Pilot Pool

* **Target Scope:** Automated CI runner testing, distribution packager enablement, and kernel regression testing.
* **Vendor Requirements Checklist:**
  * **Hardware & Physical Checklist:**
    * [ ] **Verification Compliance:** Board variant must successfully pass all Stage 1 verification suites (automated power cycling, automated firmware flashing, and TFTP/PXE netboot verified).
    * [ ] **Form Factor & Allocation:** Supply 10+ physical units racked at the RISE Board Farm (custom caddy or standardized motherboard footprint like ATX/ITX) with a 10–15% vendor replacement pool.
  * **Firmware & Bootloader Checklist:**
    * [ ] **Source Accessibility:** Public source repositories/branches (open source mirrors or vendor public forks for OpenSBI, U-Boot, Buildroot) accessible to maintainers.
    * [ ] **Firmware Upstreaming Plan:** Provide a documented upstreaming plan outlining the timelines and targeted mailing list patch series for pushing core bootloader enablement (e.g., OpenSBI, U-Boot) upstream.
    * [ ] **Boot Standards:** Must provide a fully compliant **UEFI** boot environment conforming to **EBBR (Embedded Base Boot Requirements)** and **RISC-V BBR** (e.g., U-Boot with `CONFIG_EFI_LOADER=y` or EDK2). This ensures standard, unmodified OS installers boot seamlessly without custom board scripts. *(Note: UEFI Secure Boot is optional).*
    * [ ] **Binary Blob Governance:** Supply SHA256 integrity checksum manifests, payload memory maps, and a documented Binary Sunset Plan (with specific timelines agreed upon with Board Farm maintainers) committing to open-sourcing or eliminating prebuilt core bootline blobs (e.g., OpenSBI, U-Boot). Dedicated proprietary co-processor or GPU/NPU firmware are exempt from the sunset plan.
  * **Linux Kernel Checklist:**
    * [ ] **Linux Upstreaming Plan:** Provide a documented Linux Upstreaming Plan (with specific timelines agreed upon with Board Farm maintainers) outlining active, in-progress, and planned [`lore.kernel.org`](https://lore.kernel.org/linux-riscv/) patch series for device enablement.
  * **RISC-V Architecture Checklist:**
    * [ ] **ISA Extension Validation:** All documented custom and standard ISA extensions accurately reported and verified under a mainline kernel environment without regression.

* **Board Farm Support & Services Provided:**
  * **Distribution Maintainer Access:** Access expanded to targeted Linux distribution packagers:
    * Ubuntu 24.04 and Ubuntu 26.04 (targeting RVA23 compliant hardware)
    * Debian 13
    * Gentoo (active 64-bit RISC-V support)
    * RHEL 10 (Developer Preview for RISC-V)
  * **CI Runner Integration:** Integration into GitHub Actions self-hosted runner pool (`board-farm-controller`) for automated PR testing.
  * **Mainline Regression Testing:** Automated builds of [`torvalds/linux`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git) master/rc kernels executed with `kselftest`.


---

### Stage 3: Production Pool

* **Target Scope:** Production bare-metal compute pool for general RISC-V developers and ecosystem maintainers (providing shared community CI execution).
* **Vendor Requirements Checklist:**
  * **Hardware & Physical Checklist:**
    * [ ] **Out-of-Band Management:** Redfish / OpenBMC out-of-band management interface functional on host exporters.
  * **Firmware & Bootloader Checklist:**
    * [ ] **UEFI OS Provisioning:** Unwavering UEFI baseline support enabling dynamic remote OS imaging from production Ironic bare-metal servers.
    * [ ] **Upstream Submission Progress:** Upstream PRs in final review for OpenSBI ([`riscv-software-src/opensbi`](https://github.com/riscv-software-src/opensbi)) and U-Boot ([`u-boot/u-boot`](https://github.com/u-boot/u-boot)).
    * [ ] **Binary Sunset Plan Completion:** Verified completion of the committed Binary Sunset Plan, successfully substituting any previous prebuilt core bootline blobs with open-source alternatives.
  * **Linux Kernel Checklist:**
    * [ ] **Linux Upstreaming Plan Completion:** Upstream patches merged or in final review for all SoC drivers, clock trees, pin controllers, and board Device Trees targeting the [`linux-riscv`](https://git.kernel.org/pub/scm/linux/kernel/git/riscv/linux.git) maintainer branches and standard [`torvalds/linux`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git) releases.
  * **RISC-V Architecture Checklist:**
    * [ ] **Declared Architecture Compliance:** Full hardware compatibility with the board's explicitly targeted architectural profile (e.g., RVA22/RVA23, ensuring features like Hypervisor `H` or Vector `V` operate reliably for production workloads).

* **Board Farm Support & Services Provided:**
  * **OpenStack Bare-Metal Integration:** Full integration into multi-tenant OpenStack Nova / Ironic bare-metal infrastructure with Redfish out-of-band management.
  * **Tier-1 CI Integration:** Deployed as the dedicated, high-availability baseline for GitHub Actions runner pools backing major upstream open-source projects (e.g., Linux Kernel, GCC/LLVM, CPython, PyTorch, CNCF, Llama.cpp, and more).
  * **Public Developer Pool:** On-demand self-service allocation for ecosystem developers, toolchain maintainers (GCC/LLVM), and language runtime teams (OpenJDK, Rust, Go).
  * **Production SLA Support:** Racked in production RISE datacenter infrastructure with best-effort (e.g., 3–5 business days) remote-hands hardware support and automated telemetry monitoring.
