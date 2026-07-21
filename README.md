# RISE Board Farm

Welcome to the central repository for the **RISE RISC-V Board Farm** management software, hardware bring-up specifications, and CI integration architecture hosted at RISE Board Farm.

## About RISE

[RISE](https://riseproject.dev) is a collaborative, industry-led initiative under the Linux Foundation that accelerates open-source software development for the RISC-V architecture.

---

## 1. Vision & Purpose

The core mission of the **RISE Board Farm** is to **democratize access to physical RISC-V hardware**, accelerating software maturity, toolchain readiness, kernel enablement, and upstreaming across the entire ecosystem.

* **Moving Beyond QEMU:** Software emulation via QEMU is widely available, but physical silicon is essential for validating real-world hardware performance, cache hierarchies, memory controller behavior, hardware vector extensions (RVV), peripheral driver stability, and true hardware regression testing.
* **Empowering Open-Source Maintainers:** Providing reliable, automated bare-metal infrastructure enables distribution maintainers (Debian, Ubuntu, RHEL, Gentoo) and upstream developers to build, test, and benchmark daily mainline kernels and application toolchains directly on real RISC-V hardware.

---

## 2. Current Rollout Status

* **Deployment Location:** Physical hardware is hosted and co-located at the **Oregon State University Open Source Lab (RISE Board Farm)**.
* **Current Phase:** **Phase 1 (Labgrid Pilot MVP)**.
* **Active Hardware Cluster:** The pilot is built around an initial allocation of 20 **Alibaba Zhihe A210** boards donated by Alibaba.
* **Active Focus Areas:**
  * Configuring U-Boot TFTP boot and DHCP network boot pipelines.
  * Integrating GitHub Actions self-hosted runners (`board-farm-controller`) for automated PR validation.

---

## 3. Architecture Roadmap & Phased Execution

The board farm rollout is structured into two macro phases:
* **Phase 1 (Labgrid Pilot):** Delivers automated hardware access for kernel testing, CI runners, and SSH debugging using a lightweight Labgrid setup.
* **Phase 2 (OpenStack Cloud Production):** Scales management into a production multi-tenant bare-metal cloud leveraging OpenStack Ironic, Redfish APIs, and OpenBMC controllers.

```text
Phase 1 (MVP)                             Phase 2 (Production Cloud)
+-----------------------------------+     +-----------------------------------------+
| GitHub Actions Workflow           |     | OpenStack Nova / Ironic Bare-Metal Cloud|
|           │                       |     |                    │                    |
|           ▼                       |     |                    ▼                    |
| Labgrid (Coordinator + Exporter)  | ──► | OpenBMC (D-Bus / Redfish on Exporter)   |
|           │                       |     |                    │                    |
|           ▼                       |     |                    ▼                    |
| DUT Serial/Power + U-Boot TFTP    |     | UEFI PXE Netboot + IPA eMMC Flashing    |
+-----------------------------------+     +-----------------------------------------+
```

---

## 4. Navigation & Documentation Map

### 📁 Architectural Specs (`docs/`)
* **[Management Software Proposal](docs/00-overview/management-software-proposal.md):** Overall project scope, phases, roadmap, and use cases.
* **[Labgrid DHCP & TFTP Research](docs/phase-1-labgrid-pilot/labgrid-dhcp-tftp-research.md):** Labgrid 4-role process model, U-Boot TFTP vs PXE boot flows, and network isolation rules.
* **[OpenBMC RISC-V BMC Plan](docs/phase-2-openbmc-production/openbmc-riscv-bmc-plan.md):** Implementation plan for OpenBMC multi-host Redfish controllers on x86 exporter hardware.
* **[TFTP Boot & GHA Flashing Design](docs/architecture-design/tftp-boot-gha-and-flashing-design.md):** GitHub Actions workflows, TFTP boot, and exclusive container pool testing designs.
