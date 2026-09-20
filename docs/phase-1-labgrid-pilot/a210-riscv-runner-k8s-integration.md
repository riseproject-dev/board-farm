# Zhihe A210 Board Farm: RISE RISC-V Runner Kubernetes Integration

**Status:** In Progress / Experimental  
**Authors:** [Puneetha Ramachandra](mailto:puneetha@google.com), [Ludovic Henry](mailto:ludovic.henry@qti.qualcomm.com)  
**Last Updated:** September 2026  

---

## 1. Executive Summary & Objective

The **RISE RISC-V Runner Project** provides automated CI/CD compute infrastructure for native RISC-V workloads, including package building, Python wheel compilation, and toolchain validation. While the primary control plane and standard virtualized runners reside in cloud infrastructure (Scaleway), physical hardware workers are required to test SoC-specific ISA extensions, hardware performance counters, and real silicon behavior.

This document describes the ongoing experiment and live operational integration of the **Zhihe A210 board farm** at the Oregon State University Open Source Lab (OSU OSL) as worker nodes in the RISE Kubernetes cluster.

### Key Goals
1. Connect physical Zhihe A210 boards (starting with `a210-board-05`) to the remote Scaleway Kubernetes control plane.
2. Bridge the on-premise OSU OSL subnet (`10.6.4.0/24`) with the cloud Kubernetes cluster via secure OpenVPN tunneling.
3. Resolve OS discrepancies between standard Ubuntu runner playbooks and Debian bookworm stock firmware.
4. Integrate hardware discovery and reporting for Zhihe A210's dual T-Head Xuantie C920 cores into the RISE Kubernetes Device Plugin.
5. Fix kernel networking prerequisites (specifically `CONFIG_VXLAN`) required for Flannel CNI overlay networking.
6. Provide an extensible, maintainable baseline for scaling to all 5 A210 boards in the OSU OSL lab rack.

---

## 2. Infrastructure Architecture & Network Topology

The integration bridges two environments: the cloud-hosted Kubernetes control plane on Scaleway and the physical board farm at OSU OSL.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Scaleway Cloud Infrastructure                         │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ Kubernetes Control Plane (`k8s-control-plane` / v1.30.2)            │   │
│   │  ├── API Server: 10.4.0.1:6443 / 51.159.208.204                    │   │
│   │  ├── Kube-Scheduler & Controller Manager                            │   │
│   │  ├── Flannel CNI DaemonSet (VXLAN Backend, Subnet: 10.244.0.0/16)   │   │
│   │  └── RISE Device Plugin DaemonSet (RISC-V Hardware Resource Alloc)   │   │
│   └──────────────────────────────────┬──────────────────────────────────┘   │
└──────────────────────────────────────┼──────────────────────────────────────┘
                                       │
                         Secure OpenVPN Gateway Tunnel
                                       │
┌──────────────────────────────────────┼──────────────────────────────────────┐
│                  OSU OSL Lab Rack (10.6.4.0/24 Subnet)                      │
│                                      │                                      │
│  ┌───────────────────────────────────▼───────────────────────────────────┐  │
│  │ Labgrid Controller Host: `labgrid.bak.milne.osuosl.org` (10.6.4.11)   │  │
│  │  ├── Labgrid Coordinator (Port 20408) & Exporter Service              │  │
│  │  ├── Serial Multiplexer (/dev/ttyUSB0 - /dev/ttyUSB4 @ 115200)        │  │
│  │  └── TFTP & DHCP Network Boot Services                                │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │ Rack Ethernet Switch                 │
│         ┌────────────┬───────────────┼───────────────┬────────────┐         │
│         ▼            ▼               ▼               ▼            ▼         │
│     ┌───────┐    ┌───────┐       ┌───────┐       ┌───────┐    ┌───────┐     │
│     │a210-01│    │a210-02│       │a210-03│       │a210-04│    │a210-05│     │
│     │.12    │    │.13    │       │.14    │       │.15    │    │.16    │     │
│     │(Idle) │    │(Idle) │       │(Idle) │       │(Idle) │    │(K8s)  │     │
│     └───────┘    └───────┘       └───────┘       └───────┘    └───────┘     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Network Configuration Details
| Node / Component | IP Address | Role / Function | Notes |
|---|---|---|---|
| Scaleway Control Plane | `10.4.0.1` / `51.159.208.204` | K8s API Server (`kubeadm`) | Manages cluster pods, leases, and schedulers |
| Labgrid Controller Host | `10.6.4.11` | Labgrid coordinator, console server, TFTP | OpenVPN client peer; acts as local jump host |
| `a210-board-01` | `10.6.4.12` | Board 01 (C920 dual-core) | Serial: `/dev/ttyUSB0` |
| `a210-board-02` | `10.6.4.13` | Board 02 (C920 dual-core) | Serial: `/dev/ttyUSB1` |
| `a210-board-03` | `10.6.4.14` | Board 03 (C920 dual-core) | Serial: `/dev/ttyUSB2` |
| `a210-board-04` | `10.6.4.15` | Board 04 (C920 dual-core) | Serial: `/dev/ttyUSB3` |
| **`a210-board-05`** | **`10.6.4.16`** | **Pilot Worker Node in K8s** | **Serial: `/dev/ttyUSB4`; Hostname: `a210-board-05`** |

---

## 3. Operating System & Node Provisioning

### 3.1 Debian bookworm Stock Environment
The stock A210 image deployed at OSU OSL runs **Debian GNU/Linux 12 (bookworm)**:
```text
Linux a210-board-05 7.2.3-osl+ #1 SMP PREEMPT Tue Jul 21 04:36:20 UTC 2026 riscv64 GNU/Linux
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
NAME="Debian GNU/Linux"
VERSION_ID="12"
VERSION="12 (bookworm)"
```

In contrast, the standard `riscv-runner` deployment scripts assume Ubuntu, pulling Ubuntu-specific packages (such as `containerd.io` from Docker's Ubuntu APT repository) and expecting Ubuntu service configurations.

### 3.2 Hand-Rolled Bootstrap Procedure on `a210-board-05`
To validate Kubernetes node registration before completing full Ansible playbooks, the runtime stack was bootstrapped manually:

1. **Kernel Sysctls & Modules**:
   ```bash
   modprobe overlay
   modprobe br_netfilter

   cat <<EOF | tee /etc/modules-load.d/k8s.conf
   overlay
   br_netfilter
   EOF

   cat <<EOF | tee /etc/sysctl.d/k8s.conf
   net.bridge.bridge-nf-call-iptables  = 1
   net.bridge.bridge-nf-call-ip6tables = 1
   net.ipv4.ip_forward                 = 1
   EOF

   sysctl --system
   ```

2. **Container Runtime (`containerd`)**:
   Debian bookworm provides upstream `containerd` and `runc` in its standard package repository:
   ```bash
   apt-get update && apt-get install -y containerd runc
   mkdir -p /etc/containerd
   containerd config default | tee /etc/containerd/config.toml
   # Configure systemd cgroup driver
   sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
   systemctl restart containerd
   systemctl enable containerd
   ```

3. **Kubernetes Utilities (`v1.30.2`)**:
   Installed via the official `pkgs.k8s.io` repository:
   ```bash
   mkdir -p -m 755 /etc/apt/keyrings
   curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
   echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list

   apt-get update
   apt-get install -y kubelet=1.30.2-1.1 kubeadm=1.30.2-1.1 kubectl=1.30.2-1.1
   apt-mark hold kubelet kubeadm kubectl
   ```

4. **Node Join & Tainting**:
   The node joined the cluster using the discovery token and CA hash from Scaleway:
   ```bash
   kubeadm join 51.159.208.204:6443 --token <token> \
       --discovery-token-ca-cert-hash sha256:<ca_hash>
   ```

   To prevent untargeted general cluster pods from scheduling onto the board during initial testing, a NoSchedule taint was applied:
   ```bash
   kubectl taint nodes a210-board-05 riseproject.dev/node-type=unmanaged:NoSchedule
   ```

5. **Ansible Playbook Generalization**:
   The `riscv-runner` provisioning repository has been updated (branch `ansible-debian-support`) with OS-family detection (`ansible_os_family == "Debian"`) so all 5 boards can be provisioned and reprovisioned automatically.

---

## 4. Hardware Detection & Kubernetes Device Plugin

### 4.1 Zhihe A210 Hardware Identification
The Zhihe A210 features dual 64-bit superscalar RISC-V cores based on the T-Head Xuantie C920 architecture. The hardware identification registers discovered from the board are:

- **Vendor ID (`mvendorid`)**: `0x5b7` (T-Head Semiconductor)
- **Architecture ID (`marchid`)**: `0x8000000009140d00` (Xuantie C920 / C910 series with vendor extension flags)
- **Implementation ID (`mimpid`)**: `0x100d000`
- **Device Tree Compatibility**: `canaan,k230`, `zhihe,a210`, `thead,c920`

### 4.2 The `riscv_hwprobe(2)` System Call Bug
When the RISE Device Plugin (`detect.go`) attempted to query hardware capabilities on `a210-board-05`, the `riscv_hwprobe` system call failed:

```text
riscv_hwprobe failed: invalid argument (errno 22)
```

#### Diagnosis
In the Linux kernel's RISC-V `sys_hwprobe` implementation:
- Calling `riscv_hwprobe` with `cpusetsize = 0` and `cpus = NULL` directs the kernel to query extensions across **all online CPUs**.
- The vendor kernel for the A210 has a discrepancy in multi-core frequency scaling and CPU topology accounting, causing the all-CPU query to return `EINVAL` (`-1`).
- However, querying an explicit CPU mask for a single core (e.g., `CPU 0`) succeeds and accurately returns all supported hardware extensions:
  - `RISCV_HWPROBE_IMA_EXT_0`: `IMA`, `F`, `D`, `C`, `V` (Vector 1.0 / vendor vector), `Zba`, `Zbb`, `Zbs`.

#### Solution & Pull Request
We patched `hwprobe_riscv64.go` in `riseproject-dev/riscv-runner` to gracefully fall back to querying CPU 0 via `unix.CPUSet` whenever the all-CPU probe fails:

```go
func probeSingleCPU(cpu int) ([]Pair, error) {
    var set unix.CPUSet
    set.Set(cpu)
    pairs := make([]Pair, len(allKeys))
    for i, k := range allKeys {
        pairs[i].Key = k
    }
    _, _, errno := unix.Syscall6(
        unix.SYS_RISCV_HWPROBE,
        uintptr(unsafe.Pointer(&pairs[0])),
        uintptr(len(pairs)),
        uintptr(unsafe.Sizeof(set)),
        uintptr(unsafe.Pointer(&set)),
        0, 0,
    )
    if errno != 0 {
        return nil, errno
    }
    return pairs, nil
}
```

The pull request also registers the `zhihe-a210` SoC triple in `detect.go` and is submitted on branch **`device-plugin-zhihe-a210`** ([PR Link](https://github.com/riseproject-dev/riscv-runner/pull/new/device-plugin-zhihe-a210)).

---

## 5. CNI Networking & Kernel Compilation (`CONFIG_VXLAN`)

### 5.1 Flannel CNI Crash
Once the node joined the Kubernetes cluster, the `kube-flannel-ds` DaemonSet pod was scheduled onto `a210-board-05` but crash-looped with exit code 1:

```text
I0919 21:05:43.123456       1 main.go:340] Determining IP address of default interface
I0919 21:05:43.123789       1 main.go:353] Using interface eth0 with address 10.6.4.16
I0919 21:05:43.124012       1 main.go:370] Defaulting external address to interface address (10.6.4.16)
E0919 21:05:43.135001       1 main.go:275] Failed to create vxlan interface: link type vxlan not supported
```

### 5.2 Root Cause Analysis
Checking the running kernel's build configuration on the board confirmed the missing driver:
```bash
zcat /proc/config.gz | grep -i vxlan
# CONFIG_VXLAN is not set
```

#### Why Hot-Loading `vxlan.ko` Fails
We compiled a standalone `vxlan.ko` module matching the kernel headers. However, inserting it failed with:
```text
insmod: ERROR: could not insert module vxlan.ko: Unknown symbol in module
dmesg: vxlan: Unknown symbol udp_tunnel_update_gro_rcv (err -2)
dmesg: vxlan: Unknown symbol udp_tunnel_update_gro_lookup (err -2)
```

In the Linux kernel, Generic Receive Offload (GRO) functions for UDP tunneling (`udp_tunnel_update_gro_rcv`) reside in `net/ipv4/udp_offload.c`. These functions are part of monolithic `vmlinux` and are **only compiled if `CONFIG_NET_UDP_TUNNEL` is enabled during the initial kernel compilation**. Because `CONFIG_NET_UDP_TUNNEL` was disabled in the stock vendor kernel, the required symbols do not exist in `/proc/kallsyms`. Therefore, a full kernel recompile is mandatory.

### 5.3 Kernel Recompilation on Local Build Host
To avoid overloading lab infrastructure, the kernel was cross-compiled on the 96-core local build host:

1. **Source Tree**: Cloned the official matching tree from OSU OSL:
   `https://git.osuosl.org/osuosl/zhihe-a210-kernel.git` (Branch: `osl/a210-mainline`, Linux 7.2.3).
2. **Configuration Updates**:
   Using the exact running `.config` from `a210-board-05`, the following options were enabled:
   - `CONFIG_VXLAN=y` (built directly into `vmlinux`)
   - `CONFIG_NET_UDP_TUNNEL=y` (built directly into `vmlinux`)
   - `CONFIG_WIREGUARD=m`
   - `CONFIG_GENEVE=m`
   - `CONFIG_EXTRA_FIRMWARE="a210-aon.bin"` (vendor firmware preserved in `firmware/`)
3. **Compilation Command**:
   ```bash
   make -j$(nproc) ARCH=riscv CROSS_COMPILE=riscv64-linux-gnu- Image modules
   make ARCH=riscv INSTALL_MOD_PATH=/tmp/kernel-modules-install modules_install
   ```
4. **Produced Artifacts**:
   - Kernel Image: `arch/riscv/boot/Image` (29 MB, contains `vxlan_init` and `udp_tunnel_update_gro_rcv`)
   - Kernel Modules: `/lib/modules/7.2.3-osl+/` (vermagic matches live board: `7.2.3-osl+ SMP preempt mod_unload riscv`)

### 5.4 Live Kernel Deployment via Labgrid TFTP Netboot
Rather than modifying the on-board eMMC boot partition (`/dev/mmcblk0p3`), the new kernel was deployed using the Labgrid TFTP Netboot workflow developed during Phase 1:

1. **TFTP Staging**:
   The cross-compiled kernel was copied to `/var/lib/tftpboot/Image.vxlan` on `labgrid.bak.milne.osuosl.org` (`10.6.4.11`).
2. **Persistent Rootfs Netbooting**:
   The netboot automation script (`run_tftp_trial.py`) was enhanced to boot directly into the existing eMMC Debian root filesystem without requiring an installer ramdisk:
   ```bash
   # Configured U-Boot bootargs:
   console=ttyS4,115200 root=/dev/mmcblk0p4 rw rootwait earlycon clk_ignore_unused panic=30 loglevel=4

   # U-Boot boot execution:
   booti ${kernel_addr} - ${dtb_addr}
   ```
3. **Execution & Verification**:
   - `run_tftp_trial.py --board a210-board-05 --image Image.vxlan --rootfs emmc` interrupted the U-Boot prompt on `/dev/ttyUSB4`, fetched `Image.vxlan` and `a210-dev.dtb` over TFTP into RAM, and executed `booti`.
   - The board booted seamlessly into Debian 12 on `/dev/mmcblk0p4`.
   - Kernel verification: `uname -a` confirmed `7.2.3-osl+` with `CONFIG_VXLAN=y`.
   - Flannel CNI pod (`kube-flannel-ds-hm4j9`) transitioned immediately to **Running**.
   - The `flannel.1` VXLAN overlay interface initialized with subnet `10.244.29.0/32`.
   - The Kubernetes node `a210-board-05` transitioned to **`Ready`**!

### 5.5 Permanent eMMC Boot Partition Installation & Autonomous Resilience

#### The Outage & Root Cause Analysis
During overnight operation, `a210-board-05` experienced an unexpected hardware power cycle. Because the initial TFTP netboot (`booti`) loaded the kernel purely into volatile RAM, U-Boot defaulted back to its standard autonomous boot source: the on-board eMMC boot partition (`/dev/mmcblk0p3`).

However, partition 3 still held the stock vendor kernel (`7.2.3-osl+ #4`). When systemd booted this kernel, it attempted to load `binfmt_misc.ko` from `/lib/modules/7.2.3-osl+/`. Because the modules had been updated during our earlier module installation, an ABI struct mismatch occurred, triggering a kernel Oops:
```text
[13579.285400] Unable to handle kernel access to user memory without uaccess routines at virtual address 0000000000000088
[13579.359240] CPU: 3 UID: 0 PID: 466 Comm: systemd Tainted: G D 7.2.3-osl+ #4 PREEMPTLAZY
[13579.376853] epc : load_misc_binary+0x14/0x2ac [binfmt_misc]
```
This crash terminated PID 1 (`systemd`), halting network service initialization (`systemd-networkd`, `osl-setmac`) and leaving the board unreachable at `10.6.4.16`.

#### Resolution & Permanent Installation
To ensure 100% resilience across power cuts, reboots, and watchdog events:
1. The board was recovered via Labgrid TFTP netboot (`run_tftp_trial.py --board a210-board-05 --image Image.vxlan --rootfs emmc`).
2. The eMMC boot partition was mounted:
   ```bash
   mount /dev/mmcblk0p3 /mnt/boot
   ```
3. The stock kernel was safely backed up:
   ```bash
   cp /mnt/boot/Image /mnt/boot/Image.stock.bak
   ```
4. The verified `Image.vxlan` was installed to `/mnt/boot/Image` and synced:
   ```bash
   scp labgrid:/var/lib/tftpboot/Image.vxlan /mnt/boot/Image
   sync && umount /mnt/boot
   ```
5. **Autonomous Reboot Verification**:
   The board was rebooted (`reboot`) without Labgrid or TFTP intervention. U-Boot loaded `/mnt/boot/Image` directly from `/dev/mmcblk0p3`. The board booted cleanly in 35 seconds, running `Linux a210-5 7.2.3-osl+ #1 SMP PREEMPT`, mounting `binfmt_misc` cleanly without errors, bringing up `end0` (`10.6.4.16/22`), activating `flannel.1` (`10.244.29.0/32`), and reporting `Ready:True` in Kubernetes.

---

## 6. Live Cluster & Node Inventory Matrix

| Node Name | Hardware / SoC | IP Address | TTY Console | OS / Kernel | K8s State | Flannel CNI | Device Plugin | Target Workload |
|---|---|---|---|---|---|---|---|---|
| `a210-board-01` | Zhihe A210 (2x C920) | `10.6.4.12` | `/dev/ttyUSB0` | Debian 12 (7.1.8) | Unregistered | Pending | Pending | Standby / Labgrid |
| `a210-board-02` | Zhihe A210 (2x C920) | `10.6.4.13` | `/dev/ttyUSB1` | Debian 12 (7.1.8) | Unregistered | Pending | Pending | Standby / Labgrid |
| `a210-board-03` | Zhihe A210 (2x C920) | `10.6.4.14` | `/dev/ttyUSB2` | Debian 12 (7.2.3) | Unregistered | Pending | Pending | Standby / Labgrid |
| `a210-board-04` | Zhihe A210 (2x C920) | `10.6.4.15` | `/dev/ttyUSB3` | Debian 12 (7.2.3) | Unregistered | Pending | Pending | Standby / Labgrid |
| **`a210-board-05`** | **Zhihe A210 (2x C920)** | **`10.6.4.16`** | **`/dev/ttyUSB4`** | **Debian 12 (7.2.3-osl+ eMMC)** | **Joined & `Ready` (Tainted)** | **Running (`flannel.1`)** | **PR Submitted** | **Python Wheel Pilot** |

---

## 7. Next Steps & Ongoing Plan

1. **Deploy RISE Device Plugin DaemonSet**:
   - Apply updated device plugin container image built from branch `device-plugin-zhihe-a210` (featuring CPU 0 `riscv_hwprobe` fallback).
   - Confirm `a210-board-05` advertises allocatable capacity `riseproject.dev/zhihe-a210: 1`.
2. **Execute End-to-End Pilot Workload**:
   - Run a test Python wheel build pod requesting `riseproject.dev/zhihe-a210: 1` and tolerating the `unmanaged` taint.
   - Validate performance and stability under multi-threaded compilation.
3. **eMMC Kernel Persistence (Completed)**:
   - Successfully flashed `Image.vxlan` to `/dev/mmcblk0p3` (`/mnt/boot/Image`); autonomous boots verified resilient across power cycles.
4. **Scale to Remaining Boards**:
   - Apply the standardized kernel image and Debian Ansible playbooks across `a210-board-01` through `a210-board-04`.
