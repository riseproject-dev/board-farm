# RISE Board Farm: TFTP Boot, GitHub Actions, and Flashing Design

**Status:** Draft | **Authors:** [Puneetha Ramachandra](mailto:puneetha@google.com), [Ludovic Henry](mailto:ludovic.henry@qti.qualcomm.com)

## 1. Objective

This document outlines the phased design for integrating GitHub-based kernel builds with the RISE Board Farm (targeting the Zhihe A210 boards hosted at OSU-OSL). It details the transition from the **Phase 1 (Labgrid Pilot)** to **Phase 2 (OpenStack/OpenBMC Production)**.

## 2. Phased Architecture Overview

To ensure a smooth transition, the boot requirements (specifically UEFI) are aligned across both phases.

```
+--------------------------------------------------------------------------+
| Phase 1: Labgrid Pilot (Targeted Testing)                                |
| GitHub Actions -> Labgrid (Serial/PDU) -> U-Boot (UEFI) -> TFTP          |
|                 -> SSH (Test Execution)                                  |
+--------------------------------------------------------------------------+
                                     |
                                     v (Transition: OpenBMC + Ironic)
+--------------------------------------------------------------------------+
| Phase 2: OpenStack Production (Cloud Bare-Metal)                         |
| GitHub Actions -> Glance -> Ironic -> External BMC (Pi) -> UEFI PXE      |
| -> IPA -> eMMC -> SSH (User Access)                                      |
+--------------------------------------------------------------------------+
```

## 3. Macro Phase 1: Labgrid Pilot

In Phase 1, we use a lightweight setup where GitHub Actions orchestrates the workflow and Labgrid manages the physical board interaction.

### 3.1. Architecture

* **Orchestrator:** GitHub Actions + runner on a board (arm64/amd64) running at OSU/OSL
* **Board Control & Boot:** Labgrid (PDU for power, USB-TTL for serial).
* **Test Execution:** SSH (over local network once the OS is booted).
* **File Server:** Local TFTP server on the gateway.

### 3.2. Workflow

There are two kinds of runners necessary for that setup:
- GitHub hosted runners: they are hosted directly by GitHub (e.g. `ubuntu-latest`, `ubuntu-24.04`, `ubuntu-24.04-arm`, etc.). They are hosted in a datacenter somewhere we do not have direct access to, and they are the fastest machine we have access to. The [RISE RISC-V Runners](https://riscv-runners.riseproject.dev/) are in this category as we can't assume where they are hosted
- A self-hosted `board-farm-controller` runner hosted at OSU-OSL. We are provisioning it to run on the same machine as the TFTP/DHCP and Labgrid Controller. This runner can't be doing heavy compute work (build, test) and it should be used exclusively to download/upload artifacts and interact with Labgrid. We _may_ (TBD) want to support multiple runners on this single machine to allow for multiple GHA workflows to use the cluster at the same time; Concurrency is controlled with <a href="https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency"><code>concurrency</code></a>

<table>
<tr>
  <th></th>
  <th>Steps</th>
  <th>Runner</th>
  <th>Description</th>
</tr>
<tr>
  <td>1</td>
  <td><strong>Build</strong></td>
  <td><code>ubuntu-24.04</code> or <code>ubuntu-24.04-riscv</code></td>
  <td>Compile the kernel/FIT image on a hosted runner (e.g. <code>ubuntu-24.04</code>, <code>ubuntu-24.04-arm</code>, <code>ubuntu-24.04-riscv</code>) and upload the image to GHA artifacts (<code>actions/upload-artifacts</code>)</td>
  </tr>
<tr>
  <td>2</td>
  <td><strong>Stage</strong></td>
  <td rowspan="5"><code>[self-hosted, board-farm-controller]</code><br/>All steps running sequentially in a single GHA job; Concurrency controlled by <a href="https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency"><code>concurrency</code></a></td>
  <td>Download the kernel/FIT image (<code>actions/download-artifacts</code>) and store it locally; If that runner is running on the TFTP/DHCP server, then it can simply store it on the local filesystem</td>
  </tr>
<tr>
  <td>3</td>
  <td><strong>Acquire</strong></td>
  <td>The runner uses <code>pytest-labgrid</code> to lock the target A210 board; The runner must have network access to the Labgrid Controller, or even be hosted all on the same machine</td>
  </tr>
<tr>
  <td>4</td>
  <td><strong>Boot (serial)</strong></td>
  <td>Labgrid:<br/>- Power-cycles the board via the PDU.<br/>- Intercepts the U-Boot prompt over serial.<br/>- Dynamically configures U-Boot env vars (IP, TFTP server).<br/>- Executes <code>tftpboot</code> and boots the image.</td>
  </tr>
<tr>
  <td>5</td>
  <td><strong>Test (SSH)</strong></td>
  <td>- The runner waits for the board's SSH daemon to become active.<br/>- The test script connects to the board via <strong>SSH</strong> to run the test suite.<br/>- <em>Fallback:</em> If SSH fails to connect, the runner dumps the serial console log to diagnose</td>
  </tr>
<tr>
  <td>6</td>
  <td><strong>Release:</strong></td>
  <td>The runner releases the board lock.</td>
  </tr>
</table>

A sample GHA workflow would look like the following:
```yaml
name: Kernel testing

on:
  workflow_dispatch:
    inputs:
      machine:
        description: Target machine to test on
        required: true
        type: string

jobs:
  build:
    name: Build Kernel
    runs-on: ubuntu-24.04
    steps:
      - name: build kernel
        run: ... # compile the kernel/FIT image
      - name: upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: kernel-image
          path: ... # path to the built kernel/FIT image

  test:
    name: Boot & Test Kernel
    needs: build
    runs-on: [self-hosted, board-farm-controller]
    # Concurrency is scoped per-machine so multiple workflows can't fight over the same board.
    concurrency:
      group: board-farm-${{ inputs.machine }}
      cancel-in-progress: false
    steps:
      - name: download artifacts
        uses: actions/download-artifact@v4
        with:
          name: kernel-image
          path: /path/to/tftp-root

      - name: acquire
        run: |
          # acquire labgrid machine ${{ inputs.machine }}

      - name: dhcp-setup
        run: |
          # does the right file mangling with the artifacts for the DHCP/TFTP server to pick up the files

      - name: boot
        run: |
          # do power cycling of machine ${{ inputs.machine }}, read console until it's booted, wait up to XX minutes

      - name: test
        run: |
          # connect via SSH to machine ${{ inputs.machine }}

      - name: release
        run: |
          # release labgrid machine ${{ inputs.machine }}
```

## 4. Macro Phase 2: OpenStack & OpenBMC Production

In Phase 2, the boards are managed as standard bare-metal compute instances within an OpenStack cloud.

### 4.1. Architecture

* **Orchestrator:** OpenStack Nova & Ironic.
* **Board Control:** External Raspberry Pi running OpenBMC.
  * **Power Control:** Redfish API mapping to Raspberry Pi GPIOs connected to the A210's physical power/reset headers.
  * **Console:** Serial-over-LAN (SoL) via Raspberry Pi UART connected to the A210's serial console.
* **User/CI Access:** SSH (standard cloud instance access).
* **File Server:** OpenStack Ironic managed PXE/TFTP/HTTP infrastructure.
* **Labgrid:** Decommissioned for these boards to avoid resource conflicts.

### 4.2. Workflow

1. **Build & Register:** GitHub Actions builds the OS image and uploads it to the OpenStack Image Service (Glance).
2. **Deploy Trigger:** The workflow triggers OpenStack to deploy the image to an A210 node.
3. **Provisioning (Ironic):**
   * Ironic uses the External OpenBMC (Redfish on the Pi) to set the boot device to PXE and power-on the A210.
   * The A210 network-boots the **Ironic Python Agent (IPA)** ramdisk via UEFI PXE.
   * IPA runs in-memory on the A210 board, fetches the image from Glance, and flashes it to the local eMMC/NVMe.
   * Ironic reboots the board into the newly flashed OS.
4. **Access:** The user or CI workflow accesses the deployed OS via SSH.

## 5. Key Transition Requirements (Phase 1 to Phase 2)

To ensure boards can transition from Phase 1 to Phase 2 without hardware or firmware modifications:

1. **U-Boot UEFI Support:**
   * The U-Boot binary deployed in Phase 1 **must** be compiled with EFI loader support enabled (`CONFIG_EFI_LOADER=y`).
   * Ironic relies on chainloading a UEFI bootloader (like GRUB `grubriscv64.efi`) over the network.
2. **Network Boot Prioritization:**
   * U-Boot should be configured to check PXE/DHCP boot targets before falling back to local storage.
3. **riscv64 Ironic Python Agent (IPA) Image:**
   * We must build and validate a custom `riscv64` IPA ramdisk image (using `diskimage-builder` or Buildroot) to enable Ironic to flash the eMMC on the RISC-V target.
4. **OpenBMC Integration:**
   * As the external Raspberry Pi BMCs are introduced, the physical serial and power connections will be routed through the Pi. Labgrid drivers in Phase 1 should be updated to use Redfish/IPMI (via the Pi) to validate the BMC path before the full OpenStack transition.

## 6. Developer Workflow & CI Integration (Phase 1)

This section describes the end-to-end workflows for developers running tests on the A210 hardware during Phase 1, covering both OS-level and application-level testing.

### 6.1. Kernel / OS Testing (Stateless TFTP Boot)

This workflow is for developers modifying the kernel or OS image, requiring a fresh boot from the built artifacts on every run. **This flow is highly board-specific.**

#### 6.1.1. Workflow Step-by-Step

1. **Code Push:** A developer pushes a kernel change to GitHub.
2. **Build (Cloud):** GitHub Actions compiles the kernel and packages it into a `fitImage`.
3. **Stage & Acquire (Lab):** The self-hosted runner downloads the `fitImage` to `/srv/tftp/a210/` and locks an available board via Labgrid.
4. **Boot (Serial):** Labgrid power-cycles the board and uses the serial console to trigger a U-Boot `tftpboot` of the new image.
5. **Verify (SSH):** Once the OS boots, the runner connects via SSH to execute the test suite.
6. **Release:** The board is unlocked.

#### 6.1.2. Example Test Definition (`tests/test_kernel.py`)

```py
import pytest

def test_boot_and_uname(target):
    """Verify the board boots the new kernel and reports the correct arch."""
    ssh = target.get_driver("SSHDriver")
    stdout, stderr, exit_code = ssh.run("uname -a")
    assert exit_code == 0
    assert "riscv64" in "".join(stdout)
```

#### 6.1.3. Labgrid Environment Configuration (`lab_env.yaml`)

```
targets:
  a210-board-01:
    resources:
      RemoteSerialPort:
        speed: 115200
        host: "192.168.1.50"
        port: 2001
      PDUPort:
        host: "192.168.1.60"
        port: 3
      NetworkService:
        address: "192.168.1.100"
        username: "root"
    drivers:
      SerialDriver:
        bindings:
          port: RemoteSerialPort
      ShellDriver:
        bindings:
          io: SerialDriver
        prompt: "root@a210:~#"
        login_prompt: "a210 login:"
        username: "root"
      SSHDriver:
        bindings:
          target: NetworkService
```

#### 6.1.4. Example GitHub Actions Workflow (`.github/workflows/a210_kernel_test.yml`)

```
name: A210 Kernel Test
on:
  workflow_dispatch:
  issue_comment:
    types: [created]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Kernel
        run: |
          make a210_defconfig
          make -j$(nproc) fitImage
      - name: Upload FIT Image
        uses: actions/upload-artifact@v4
        with:
          name: fitImage
          path: arch/riscv/boot/fitImage

  test-hw:
    if: |
      github.event_name == 'workflow_dispatch' ||
      (github.event.comment && startsWith(github.event.comment.body, '/run-kernel-tests'))
    needs: build
    runs-on: [self-hosted, osu-osl-lab]
    steps:
      - name: Download FIT Image
        uses: actions/download-artifact@v4
        with:
          name: fitImage
          path: /srv/tftp/a210/
      - name: Run Tests
        run: |
          pytest --lg-env=lab_env.yaml --lg-role=a210 --junitxml=results.xml tests/test_kernel.py
```

### 6.2. Application / Library Testing (Stateful Container Pool)

This workflow is for repositories that do not modify the OS but need to run application-level tests (e.g., OpenJDK, Go, Rust) on a stable RISC-V RVA23 Debian/Ubuntu environment. **This flow is capability-generic (agnostic to the specific SoC/board).**

#### 6.2.1. Design Comparison

* **Reflash on Every Run (Stateless):** Too slow (minutes of overhead per test run to reflash a full Debian/Ubuntu OS).
* **Ready-to-Use Pool with Sandboxing (Stateful Host + Container):** Fast execution (seconds to start a container), but requires resource isolation to prevent test interference and performance benchmarking skew.

#### 6.2.2. Selected Model: "Exclusive Container Pool"

To balance speed with benchmarking accuracy, we use a hybrid model:

1. We maintain a pool of boards running a stable, pre-flashed Debian/Ubuntu host.
2. We use Labgrid to lock the **entire physical board** for exclusive CPU/RAM access.
3. We run the tests inside a **Docker/Podman container** on the host.
4. We perform a **periodic hard reset (TFTP reflash)** nightly or on test failure to prevent host OS drift.

#### 6.2.3. Workflow Step-by-Step

1. **Code Push:** A developer pushes an application change.
2. **Acquire (Capability-based):** The runner requests an available board that matches the required capabilities (e.g., **`rva23`** profile and a specific OS like **`debian13`** or **`ubuntu2404`**), rather than a specific board model like `a210`.
3. **SSH & Stage:** The runner connects to the selected host via SSH and copies the application test workspace from the runner to the target board.
4. **Sandbox Execution:** The runner starts a RISC-V Debian/Ubuntu container on the target, mounting the copied workspace, and executes the tests.
5. **Teardown:** The container is destroyed, the temporary workspace on the target is cleaned up, and the board is unlocked.
6. **Hard Reset:** If the test fails or times out, a TFTP reflash is automatically triggered.

#### 6.2.4. Example Test Definition (`tests/test_app.py`)

```py
import pytest

def test_app_in_container(target):
    """Run application tests inside a sandboxed container on the target."""
    ssh = target.get_driver("SSHDriver")
  
    # 1. The runner/script has staged the files at /tmp/workspace.
  
    # 2. Run the test suite inside a clean Debian/Ubuntu container
    cmd = (
        "docker run --rm "
        "-v /tmp/workspace:/workspace "
        "-w /workspace "
        "riscv64/debian:latest ./run-tests.sh"
    )
    stdout, stderr, exit_code = ssh.run(cmd)
  
    assert exit_code == 0
```

#### 6.2.5. Example Labgrid Configuration for Capability Roles (`lab_env.yaml`)

To support capability-based targeting, we map generic roles (separating Debian and Ubuntu) to specific board targets in the Labgrid configuration:

```
targets:
  a210-board-01:
    resources:
      RemoteSerialPort:
        host: "192.168.1.50"
        port: 2001
      NetworkService:
        address: "192.168.1.100"
        username: "root"
  spacemit-k1-01:
    resources:
      RemoteSerialPort:
        host: "192.168.1.50"
        port: 2002
      NetworkService:
        address: "192.168.1.101"
        username: "root"

# Map generic capability roles (separated by OS) to physical boards
roles:
  rva23_debian13:
    - a210-board-01
  rva23_ubuntu2404:
    - spacemit-k1-01
```

#### 6.2.6. Example GitHub Actions Workflow (`.github/workflows/riscv_app_test.yml`)

```
name: RISC-V RVA23 Application Test
on:
  workflow_dispatch:
  issue_comment:
    types: [created]

jobs:
  test-hw:
    if: |
      github.event_name == 'workflow_dispatch' ||
      (github.event.comment && startsWith(github.event.comment.body, '/run-app-tests'))
    runs-on: [self-hosted, osu-osl-lab]
    steps:
      - uses: actions/checkout@v4  # Checks out the repository on the runner
    
      - name: Run Labgrid App Tests (Debian 13)
        run: |
          # Request a board by its specific Debian capability role
          pytest --lg-env=lab_env.yaml --lg-role=rva23_debian13 --junitxml=results.xml tests/test_app.py

      # Alternatively, to run on Ubuntu 24.04:
      # - name: Run Labgrid App Tests (Ubuntu 24.04)
      #   run: |
      #     pytest --lg-env=lab_env.yaml --lg-role=rva23_ubuntu2404 --junitxml=results.xml tests/test_app.py

      - name: Publish Test Results
        uses: EnricoMi/publish-unit-test-results-action@v2
        if: always()
        with:
          files: "results.xml"
```

### 6.3. Common Test Results Upload

For both workflows, results are captured from the self-hosted runner and uploaded to GitHub:

* **Console Logs:** Streamed in real-time.
* **JUnit Reports:** Saved via `pytest --junitxml=results.xml` and published using the `publish-unit-test-results-action` to display a rich summary on the PR.

## 7. Security Considerations

### 7.1. Self-Hosted Runner Security

Running self-hosted runners on public or shared repositories poses a significant security risk if untrusted code is allowed to run.

* **Mitigation:** The workflow is configured to trigger only via `workflow_dispatch` (manual) or via a ChatOps command (`/run-tests`) after a maintainer has reviewed the PR code. This prevents external contributors from executing arbitrary code within the OSU-OSL lab network.
* **Runner Permissions:** The GitHub Actions runner service should run under a dedicated, non-privileged system user (e.g., `gha-runner`), not `root`.

### 7.2. File System Permissions

The runner needs to copy the built image to the TFTP directory (e.g., `/srv/tftp/a210/`).

* **Mitigation:** Rather than running the runner as `root`, the `/srv/tftp/a210/` directory should be owned by a shared group (e.g., `tftpusers`) to which the `gha-runner` user belongs, with write permissions enabled for the group (`g+w`).

## 8. Risks, Gaps & Mitigations

### 8.1. RISC-V Ironic Python Agent (IPA) Image

* **Risk:** Pre-built IPA ramdisk images are not standard for `riscv64`.
* **Mitigation:** We must build a custom `riscv64` IPA image using `diskimage-builder` (DIB) with custom elements, or compile a minimal ramdisk via Buildroot/Yocto that runs the `ironic-python-agent` service. This is tracked as a Phase 2 prerequisite.

### 8.2. OpenBMC Hardware Availability (External BMC)

* **Risk:** The Zhihe A210 development board does not feature an on-board BMC.
* **Mitigation:** We will deploy an **external Raspberry Pi running OpenBMC** for each A210 board. The Pi will connect to the A210's power/reset headers via GPIO (for power control) and to the A210's UART via a serial connection (for Serial-over-LAN). This allows us to present a standard Redfish interface to OpenStack.

### 8.3. U-Boot UEFI Network Stability

* **Risk:** U-Boot network drivers under UEFI (Simple Network Protocol) can be unstable.
* **Mitigation:** If the native network driver fails under UEFI, we will use a supported USB-to-Ethernet dongle or chainload iPXE from U-Boot to handle the network transaction.

## 9. Application-Level Testing (Stateful Pool vs. Reflash)

This section addresses the workflow for repositories that do not modify the Kernel/OS, but require running application or library tests (e.g., OpenJDK, Go, Rust toolchains) on a stable RISC-V RVA23 Debian/Ubuntu environment.

### 9.1. Design Comparison

We evaluate two models for this use case:

1. **Reflash on Every Run (Stateless):**
   * *Pros:* Guaranteed clean state; no configuration drift; high security.
   * *Cons:* Extremely slow (minutes per run to reflash a full Debian/Ubuntu OS).
2. **Ready-to-Use Pool with Sandboxing (Stateful Host + Container):**
   * *Pros:* Fast execution (seconds to start a container); high throughput.
   * *Cons:* Shared kernel; potential for container escape; risk of host OS drift.

### 9.2. Selected Model: "Exclusive Container Pool" (Hybrid)

To balance execution speed with the resource isolation required for accurate testing (especially benchmarking), we implement an **Exclusive Container Pool** model.

```
+-------------------------------------------------------------------------+
| GitHub Actions -> Lock Board (Labgrid/Ironic) -> SSH to Host            |
|                 -> Start RISC-V Debian/Ubuntu Container -> Run Tests     |
|                 -> Destroy Container -> Unlock Board                    |
+-------------------------------------------------------------------------+
                                     |
                                     v (Periodic / On-Failure)
+-------------------------------------------------------------------------+
| Hard Reset: Trigger TFTP Reflash to restore Host OS to Golden Image      |
+-------------------------------------------------------------------------+
```

### 9.3. Workflow Steps

1. **Acquire (Exclusive Lock):** The CI runner requests a board from the pool. Even though tests run in a container, the **entire physical board is locked** to ensure exclusive CPU/RAM access (critical for benchmark reliability).
2. **Spin up Sandbox:** The runner connects to the host Debian/Ubuntu via SSH and starts a Docker/Podman container using a RISC-V Debian/Ubuntu image, mounting the test workspace.
3. **Execute Tests:** Tests are executed entirely within the container.
4. **Teardown:** The container is stopped and destroyed (`docker rm -f`). The runner executes a quick host-level cleanup script (cleaning `/tmp`, verifying no rogue processes are running).
5. **Periodic Hard Reset:** To mitigate host OS drift or potential security compromises, the gateway automatically triggers a **full TFTP reflash** of the board:
   * After any test failure or timeout.
   * On a periodic schedule (e.g., nightly).

## 10. Alternatives & Design Trade-offs

### 10.1. Orchestration: LAVA vs. Labgrid + GitHub Actions

* **LAVA (Linaro Automation and Validation Architecture):**
  * *Pros:* Enterprise-grade, handles massive multi-tenant board farms, built-in TFTP/DHCP management.
  * *Cons:* Very high administrative overhead (requires dedicated database, web servers, and complex configuration).
  * *Decision:* **Rejected for Pilot.** For a medium-sized farm, the combination of GitHub Actions (for scheduling/queuing) and Labgrid (for hardware control) is much lighter, easier to maintain, and provides similar capabilities.

### 10.2. Boot Method: Virtual Media (vMedia) vs. TFTP/PXE

Instead of TFTP, modern BMCs (via OpenBMC) support mounting a remote disk image over HTTPS.

* **Virtual Media Boot:**
  * *Pros:* Bypasses the need for local TFTP/DHCP infrastructure on the gateway. Bypasses potentially flaky U-Boot network drivers (U-Boot only needs standard USB storage support). Supports secure HTTPS.
  * *Cons:* Boot speed is limited by the BMC's ability to proxy disk reads over the network.
  * *Feasibility for A210:* **Medium-Low.** This requires the carrier board to have a physical USB OTG connection routing from the BMC's USB device controller to the A210 host's USB controller. If this hardware path does not exist, vMedia cannot be used.
  * *Decision:* **Alternative.** We will stick to TFTP/PXE as the primary boot method, but will evaluate vMedia if the A210 hardware supports it and U-Boot network drivers prove unstable.

