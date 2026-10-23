# RISE Board Farm: Build-Centric TFTP Storage, Hetzner CI & Release Lifecycle

**Status:** Draft | **Authors:** [Hai Bi](mailto:bihai@google.com), [Puneetha Ramachandra](mailto:puneetha@google.com)

## 1. Overview & Motivation

### 1.1. Current State
On the OSU OSL controller (`10.6.4.11`), `/var/lib/tftpboot/` (or `/srv/tftp/`) currently operates as a single flat directory holding one active set of boot files (`Image`, `.dtb`, and rootfs) alongside a manual backup copy.

When a new build is staged into this flat directory:
1. **Concurrent Boot Race Condition:** Overwriting the active files in `/var/lib/tftpboot/` while another board is mid-boot can corrupt the in-progress TFTP transfer.
2. **No Multi-Build Testing or History:** Multiple boards cannot test different builds (e.g., Yocto vs. Debian vs. Kernel PR) simultaneously, and engineers cannot easily pick a known build from last week or last month to reproduce an issue.

### 1.2. Proposed Build-Centric Design
Instead of overwriting a single TFTP directory, every cross-compiled binary set is stored in its own **immutable, versioned build directory** (`/var/lib/tftpboot/builds/<build-id>/`) with atomic symlink labels (`latest-yocto`, `latest-debian`, `current-stable`):

* **Hetzner `x86_64` Build Servers:** Perform fast cross-compilation of the A210 Linux Kernel, Yocto (`meta-riscv`), and Debian 13 (`riscv64`) images.
* **GitHub Actions Delivery:** Transfers completed build bundles to `10.6.4.11`, places them in an immutable `/var/lib/tftpboot/builds/<build-id>/` directory, and updates labels.
* **On-Demand & Automated Booting:** Free A210 boards can be instructed via Labgrid to TFTP-boot **any** stored `<build-id>` into RAM (`initramfs`) without touching onboard eMMC storage.
* **Monthly Release Cycle & 3-Month Retention:** Once a month, a verified build is promoted to `releases/YYYY-MM-release/` and flashed back to the boards' onboard eMMC as the new persistent baseline. Build directories under `builds/` are retained for **3 months (90 days)** and then automatically pruned.

---

## 2. TFTP Directory Layout on `10.6.4.11`

```text
/var/lib/tftpboot/
├── builds/                                    <-- Auto-pruned after 90 days
│   ├── 2026-10-23_kernel_7.2.11_a1b2c3d/      <-- Write-once immutable folder
│   │   ├── Image
│   │   ├── a210-dev.dtb
│   │   ├── rootfs.cpio.gz
│   │   └── build-info.json                    <-- Git SHA, build type, timestamp
│   │
│   ├── 2026-10-23_yocto_8f3a1c2/
│   │   ├── Image
│   │   ├── a210-dev.dtb
│   │   ├── rootfs.cpio.gz
│   │   └── build-info.json
│   │
│   └── 2026-10-23_debian_7.2.11_c4d5e6f/
│       ├── Image
│       ├── a210-dev.dtb
│       ├── rootfs.cpio.gz
│       └── build-info.json
│
├── releases/                                  <-- Protected from 90-day auto-delete
│   ├── 2026-10-release/                       <-- Monthly baseline flashed to eMMC
│   └── 2026-11-release/
│
└── labels/                                    <-- Symlinks updated atomically
    ├── latest-kernel  -> ../builds/2026-10-23_kernel_7.2.11_a1b2c3d
    ├── latest-yocto   -> ../builds/2026-10-23_yocto_8f3a1c2
    ├── latest-debian  -> ../builds/2026-10-23_debian_7.2.11_c4d5e6f
    └── current-stable -> ../releases/2026-10-release
```

---

## 3. End-to-End Workflow (Hetzner → GitHub → OSU TFTP → A210)

### 3.1. Stage 1: Cross-Compilation on Hetzner (`x86_64` Builder)
1. A GitHub Actions workflow runs on a 48-core Hetzner `x86_64` runner (`[self-hosted, hetzner-x86-builder]`).
2. It cross-compiles the requested target for the Alibaba A210 (`rv64gcv` / `rv64gc`):
   * **Linux Kernel:** Built from `https://git.osuosl.org/osuosl/zhihe-a210-kernel` (`osl/a210-mainline` branch today; transitions to stock `git.kernel.org` `master` / `linux-next` once Alibaba's A210 patches land upstream).
   * **Yocto (`meta-riscv`):** Built via BitBake for the `zhihe-a210` machine target (`core-image-minimal` `cpio.gz`).
   * **Debian 13 (`trixie`):** Built from `https://git.osuosl.org/osuosl/a210-linux` (`mmdebstrap --arch=riscv64` + A210 kernel).
3. The job generates a unique `<build-id>` (e.g., `YYYY-MM-DD_<type>_<git-sha>`) and uploads `Image`, `a210-dev.dtb`, `rootfs.cpio.gz`, and `build-info.json` via `actions/upload-artifact@v4`.

### 3.2. Stage 2: Atomic Staging & Labeling on OSU OSL (`10.6.4.11`)
1. The self-hosted runner on `10.6.4.11` (`[self-hosted, board-farm-controller]`) downloads the artifact into a temporary staging path (`/tmp/staging-<build-id>/`).
2. Once the download is 100% complete, the runner moves it atomically into `/var/lib/tftpboot/builds/<build-id>/` and updates the corresponding symlink under `/var/lib/tftpboot/labels/` (`ln -sfn ../builds/<build-id> /var/lib/tftpboot/labels/latest-<type>`).
3. **Concurrency Guarantee:**
   * Because `/var/lib/tftpboot/builds/<build-id>/` is never modified after the atomic `mv`, an in-progress TFTP boot can never be overwritten by a subsequent build.
   * Multiple free boards can boot the same `<build-id>` or different `<build-id>`s simultaneously.

### 3.3. Stage 3: Booting Any Build on Free Boards
* **Automated CI Testing:** Immediately after staging `<build-id>`, the workflow acquires any free A210 board via Labgrid (`labgrid-client reserve` / `acquire`) and instructs U-Boot over serial to netboot from that specific build directory:
  ```text
  tftpboot ${kernel_addr_r} builds/<build-id>/Image
  tftpboot ${fdt_addr_r}    builds/<build-id>/a210-dev.dtb
  tftpboot ${ramdisk_addr_r} builds/<build-id>/rootfs.cpio.gz
  booti ${kernel_addr_r} ${ramdisk_addr_r}:${filesize} ${fdt_addr_r}
  ```
* **On-Demand Developer Selection (`workflow_dispatch`):** Engineers can manually trigger a boot job in GitHub Actions (or via CLI) by passing any `<build-id>` from the past 3 months (or a label like `latest-yocto` or `current-stable`) to boot on any free board.

### 3.4. Stage 4: Monthly Release Flashing (`eMMC`) vs. Daily RAM Testing
* **Daily / Continuous Testing (Stateless RAM Boot):** All routine CI and developer test runs boot into the A210's 8 GB RAM (`initramfs`). The onboard eMMC is untouched, so a simple power-cycle always restores the board to a clean state.
* **Monthly Release Promotion (Persistent eMMC Baseline):** Once a month, a well-tested build from `builds/` is promoted to `/var/lib/tftpboot/releases/YYYY-MM-release/` (and labeled `current-stable`), then flashed back to the boards' onboard eMMC so the persistent baseline OS across the farm stays up to date.

---

## 4. Sample GitHub Actions Workflow

```yaml
name: Build & Boot A210 Image

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      build_type:
        description: "Build type (kernel, yocto, debian)"
        required: true
        default: "yocto"
        type: choice
        options: [kernel, yocto, debian]
      existing_build_id:
        description: "Optional: Skip build and boot an existing <build-id> from the last 3 months"
        required: false
        type: string

jobs:
  cross-build:
    if: ${{ inputs.existing_build_id == '' }}
    runs-on: [self-hosted, hetzner-x86-builder]
    outputs:
      build_id: ${{ steps.meta.outputs.build_id }}
    steps:
      - uses: actions/checkout@v4

      - name: Generate Build ID
        id: meta
        run: |
          TYPE="${{ inputs.build_type || 'yocto' }}"
          DATE="$(date -u +%Y-%m-%d)"
          SHA="${GITHUB_SHA::7}"
          echo "build_id=${DATE}_${TYPE}_${SHA}_${GITHUB_RUN_NUMBER}" >> "$GITHUB_OUTPUT"

      - name: Cross-Compile Target on Hetzner
        run: |
          # Build Kernel (osl/a210-mainline), Yocto, or Debian into ./out/
          ./scripts/build-a210.sh "${{ inputs.build_type || 'yocto' }}" ./out/

      - name: Upload Build Bundle
        uses: actions/upload-artifact@v4
        with:
          name: ${{ steps.meta.outputs.build_id }}
          path: |
            out/Image
            out/a210-dev.dtb
            out/rootfs.cpio.gz
            out/build-info.json

  stage-and-boot:
    needs: [cross-build]
    if: always() && (needs.cross-build.result == 'success' || inputs.existing_build_id != '')
    runs-on: [self-hosted, board-farm-controller]
    env:
      BUILD_ID: ${{ inputs.existing_build_id || needs.cross-build.outputs.build_id }}
      BUILD_TYPE: ${{ inputs.build_type || 'yocto' }}
    steps:
      - name: Stage New Build to TFTP Directory
        if: ${{ inputs.existing_build_id == '' }}
        uses: actions/download-artifact@v4
        with:
          name: ${{ env.BUILD_ID }}
          path: /tmp/staging-${{ env.BUILD_ID }}

      - name: Atomic Move, Label Update & 90-Day Cleanup
        if: ${{ inputs.existing_build_id == '' }}
        run: |
          mkdir -p /var/lib/tftpboot/builds /var/lib/tftpboot/labels /var/lib/tftpboot/releases
          mv "/tmp/staging-${BUILD_ID}" "/var/lib/tftpboot/builds/${BUILD_ID}"
          ln -sfn "../builds/${BUILD_ID}" "/var/lib/tftpboot/labels/latest-${BUILD_TYPE}"

          # Prune build directories older than 90 days (releases/ is untouched)
          find /var/lib/tftpboot/builds/ -mindepth 1 -maxdepth 1 -type d -mtime +90 -exec rm -rf {} +

      - name: Acquire Free A210 Board & TFTP Boot Build
        run: |
          pytest --lg-env=lab_env.yaml \
                 --tftp-dir="builds/${BUILD_ID}" \
                 --junitxml=results.xml \
                 tests/test_boot.py
```

---

## 5. Expected 3-Month Storage Size & Retention Math

### 5.1. Artifact Size per Build
| Build Type | Kernel (`Image` + `.dtb`) | Rootfs (`rootfs.cpio.gz`) | Total Size per Build |
| :--- | :---: | :---: | :---: |
| **Yocto (`core-image-minimal`)** | ~20 MB | ~5 – 10 MB | **~25 – 30 MB** |
| **Linux Kernel CI (with minimal test initramfs)** | ~20 MB | ~10 – 15 MB | **~30 – 35 MB** |
| **Debian 13 (`trixie` netboot initramfs)** | ~20 MB | ~80 – 130 MB | **~100 – 150 MB** |

### 5.2. Total Storage Over a 3-Month (90-Day) Window
Assuming a steady CI build cadence over **90 days**:
* **Yocto CI** (2 builds/day × 90 days = 180 builds × 30 MB): **~5.4 GB**
* **Linux Kernel CI** (3 builds/day × 90 days = 270 builds × 35 MB): **~9.5 GB**
* **Debian Builds** (1 build/day × 90 days = 90 builds × 130 MB): **~11.7 GB**
* **Monthly Releases (`releases/`)** (12 monthly releases/year × 150 MB): **~1.8 GB**
* **Total Expected Disk Usage (90 Days):** **~28 – 30 GB total**

At ~30 GB for a full 3-month rolling window of all three workstreams, the entire build archive fits comfortably on the local storage of the OSU OSL controller (`10.6.4.11`).
