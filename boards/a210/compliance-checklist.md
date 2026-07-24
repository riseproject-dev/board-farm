# Alibaba Zhihe A210 Compliance Checklist

This checklist tracks the compliance of the Alibaba Zhihe A210 board against the [Target Hardware Onboarding & Upstreaming Compliance Policy](../compliance-requirements.md).

## Stage 1: Isolated Bring-up Bench (Current Active Phase)

### Hardware & Physical Checklist
* [x] **Physical Hardware:** Supply 1–2 working prototype or engineering sample units to the RISE Board Farm.
  * *20 boards provided.*
* [x] **Hardware Documentation & Specs:** Provide board schematics, SoC memory maps, block diagrams, jumper configurations, and component datasheets.
  * *Docs and specs links shared with developer tooling wg. Official datasheet: [https://developer.zhcomputing.com/en/docs/A210/A210_Datasheet/](https://developer.zhcomputing.com/en/docs/A210/A210_Datasheet/).*
* [x] **Mechanical & Thermal Specs:** Document exact mechanical clearance, dimensional constraints, and thermal/airflow expectations for racked continuous operation.
  * *Shared on an email thread.*
* [x] **Power Envelope:** Document peak/instantaneous power consumption under simultaneous all-cores + NPU/GPU stress to ensure safe PDU sizing.
  * *Shared on an email thread.*
* [x] **Physical Modifications:** Document any mandatory physical pad soldering or board surgery needed to access remote power/reset circuits or specific I/O connectors.
  * *No board surgery or physical pad soldering required.*
* [x] **Network & Console Interfaces:** Dedicated network interface supporting standard DHCP and U-Boot network boot methods (TFTP/PXE). Out-of-band UART interface with documented baud rate and parity settings (standard 3-pin TX/RX/GND).
  * *Onboard Gigabit Ethernet and UART Header J4 confirmed.*
* [x] **Out-of-Band Management:** Boards MUST automatically initialize and boot upon power restoration OR expose accessible header pins/jumpers for simple external relay control if front-panel power button presses are required (without necessitating complex hardware modifications).
  * *Managed via networked PDU and remote jump host. Vendor provided modified board with auto-boot upon power on.*

### Firmware & Bootloader Checklist
* [x] **Firmware & Bootloader Source:** Provide functional prebuilt binaries, build instructions, and public or private source repositories for OpenSBI and U-Boot capable of reaching a boot prompt.
  * *OpenSBI ([https://git.osuosl.org/osuosl/zhihe-a210-opensbi](https://git.osuosl.org/osuosl/zhihe-a210-opensbi)) and U-Boot ([https://git.osuosl.org/osuosl/zhihe-a210-u-boot](https://git.osuosl.org/osuosl/zhihe-a210-u-boot)) source repositories mirrored on OSU-OSL.*
* [ ] **Remote Flashing & DFU Recovery:** Supply recovery binaries, flashing scripts, and operational mechanisms to reliably trigger DFU/bootrom recovery mode remotely (e.g., via software triggers or debug harnesses, without requiring physical touch or configuration) to facilitate zero-touch firmware updates.
  * *Pending DFU mode verification.*
* [ ] **MAC Address Persistence:** Document non-volatile storage mechanisms (e.g., U-Boot `fnv` storage) for preserving deterministic MAC addresses across reflashes.
  * *Pending validation of U-Boot environment storage persistence.*
* [x] **Early Boot Firmware Blobs:** Temporary prebuilt core bootloader binary blobs (e.g., OpenSBI, U-Boot) and proprietary co-processor firmware are fully permitted during initial bench bring-up.
  * *`a210-aon.bin` (SHA256: `d24a9a6c8aab1f3d3049211b6509a503172c381778dcf1c9f23291e5082e999c`) required for Always-On (AON) low-power processor initialization; acceptable for all stages without sunset requirement.*

### Linux Kernel Checklist
* [x] **Kernel Enablement:** Out-of-tree vendor kernel forks (e.g., Linux 6.1/6.6 vendor trees) are permitted for early bring-up, but not preferred. Vendors must grant repository access or supply kernel patches/trees to Board Farm maintainers.
  * *Vendor Linux kernel mirror is actively maintained at [https://git.osuosl.org/osuosl/a210-linux](https://git.osuosl.org/osuosl/a210-linux).*

### RISC-V Architecture Checklist
* [x] **ISA & Extensions:** Clearly define and document the supported RISC-V ISA and hardware extensions (e.g., RVA22 with RVV 1.0).
  * *Datasheet officially confirms `RV64GCV` (IMAFDC + Vector). Full RVA23 capability testing is pending lab validation.*

---

## Stage 2: Pilot Pool (Target Phase)

### Hardware & Physical Checklist
* [ ] **Verification Compliance:** Board variant must successfully pass all Stage 1 verification suites (automated power cycling, automated firmware flashing, and TFTP/PXE netboot verified).
  * *Pending execution of automated Stage 1 test suites.*
* [ ] **Form Factor & Allocation:** Supply 10+ physical units racked at the RISE Board Farm (custom caddy or standardized motherboard footprint like ATX/ITX) with a 10–15% vendor replacement pool.
  * *20 boards available, pending custom board mount 3D printing.*

### Firmware & Bootloader Checklist
* [x] **Source Accessibility:** Public source repositories/branches (open source mirrors or vendor public forks for OpenSBI, U-Boot, Buildroot) accessible to maintainers.
  * *Public Git repositories established out of OSU-OSL: [OpenSBI](https://git.osuosl.org/osuosl/zhihe-a210-opensbi), [U-Boot](https://git.osuosl.org/osuosl/zhihe-a210-u-boot), [Buildroot](https://git.osuosl.org/osuosl/zhihe-a210-buildroot).*
* [ ] **Firmware Upstreaming Plan:** Provide a documented upstreaming plan outlining the timelines and targeted mailing list patch series for pushing core bootloader enablement (e.g., OpenSBI, U-Boot) upstream.
  * *Pending upstream roadmap for OpenSBI and U-Boot from the vendor.*
* [ ] **Boot Standards:** Must provide a fully compliant **UEFI** boot environment conforming to **EBBR (Embedded Base Boot Requirements)** and **RISC-V BBR** (e.g., U-Boot with `CONFIG_EFI_LOADER=y` or EDK2). This ensures standard, unmodified OS installers boot seamlessly without custom board scripts. *(Note: UEFI Secure Boot is optional).*
  * *Currently unsupported by the vendor's U-Boot fork.*
* [x] **Binary Blob Governance:** Supply SHA256 integrity checksum manifests, payload memory maps, and a documented Binary Sunset Plan (with specific timelines agreed upon with Board Farm maintainers) committing to open-sourcing or eliminating prebuilt core bootloader binary blobs (e.g., OpenSBI, U-Boot). Dedicated proprietary co-processor or GPU/NPU firmware are exempt from the sunset plan.
  * *`a210-aon.bin` is exempt from sunsetting as it is a dedicated Always-On (AON) processor binary.*

### Linux Kernel Checklist
* [ ] **Linux Upstreaming Plan:** Provide a documented Linux Upstreaming Plan (with specific timelines agreed upon with Board Farm maintainers) outlining active, in-progress, and planned `lore.kernel.org` patch series for device enablement.
  * *Pending pipeline mapping of upstream patches from the vendor.*

### RISC-V Architecture Checklist
* [ ] **ISA Extension Validation:** All documented custom and standard ISA extensions accurately reported and verified under a mainline kernel environment without regression.
  * *Pending kselftest validation on mainline kernel.*

---

## Stage 3: Production Pool

### Hardware & Physical Checklist
* [ ] **Out-of-Band Management:** Redfish / OpenBMC out-of-band management interface functional on host exporters.
  * *Pending OpenBMC/Redfish enablement on host exporters.*

### Firmware & Bootloader Checklist
* [ ] **UEFI OS Provisioning:** Unwavering UEFI baseline support enabling dynamic remote OS imaging from production Ironic bare-metal servers.
  * *Blocked: Native UEFI boot is unsupported on this hardware variant.*
* [ ] **Upstream Submission Progress:** Upstream PRs in final review for OpenSBI and U-Boot.
  * *Pending core upstream PR submissions.*
* [x] **Binary Sunset Plan Completion:** Verified completion of the committed Binary Sunset Plan, successfully substituting any previous prebuilt core bootloader binary blobs with open-source alternatives.
  * *No sunset plan required. The provided `a210-aon.bin` is an exempt Always-On (AON) processor binary.*

### Linux Kernel Checklist
* [ ] **Linux Upstreaming Plan Completion:** Upstream patches merged or in final review for all SoC drivers, clock trees, pin controllers, and board Device Trees targeting the `linux-riscv` maintainer branches and standard `torvalds/linux` releases.
  * *Blocked: No upstream kernel patches have been submitted to mainline yet.*

### RISC-V Architecture Checklist
* [ ] **Declared Architecture Compliance:** Full hardware compatibility with the board's explicitly targeted architectural profile (e.g., RVA22/RVA23, ensuring features like Hypervisor `H` or Vector `V` operate reliably for production workloads).
  * *Pending RVA23 operational workload validations.*
