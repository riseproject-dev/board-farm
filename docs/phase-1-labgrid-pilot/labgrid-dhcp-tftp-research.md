# Labgrid Architecture: Components, Network Services, and Boot Flow

**Status:** Draft | **Authors:** [Puneetha Ramachandra](mailto:puneetha@google.com), [Ludovic Henry](mailto:ludovic.henry@qti.qualcomm.com)

## The Four Roles

Labgrid splits a board farm into four distinct roles. Three are Labgrid processes; one is entirely outside Labgrid.

**Coordinator** is a registry and lock server. It knows what resources (boards) exist and who currently holds them. It is never in the data path for actual hardware interaction - once it grants a lock, it steps aside.

**Exporter** runs on the host physically wired to the DUT. It exposes local `/dev` resources - serial port, power relay, USB-SD-mux - as RPC endpoints over the network. It must run on the machine with the physical connections.

**Client** is the test runner (pytest + labgrid). It orchestrates everything: acquires locks from the Coordinator, drives hardware through the Exporter, and pushes boot files to the TFTP host directly.

**DHCP/TFTP** are not Labgrid components. They are standard network services the DUT uses during network boot. The DUT never knows Labgrid exists - from its perspective it just sees a DHCP server and a TFTP server, same as any network boot.

## Who Talks to Whom

|From|To|Protocol|Purpose|
|-|-|-|-|
|Client|Coordinator|WebSocket|Acquire/release resource lock|
|Client|Exporter|gRPC / msgpack over TCP|Power on/off, serial I/O, sd-mux|
|Client|TFTP host|SSH + rsync|Stage kernel/dtb before boot|
|DUT|DHCP server|UDP broadcast (L2)|Get an IP address|
|DUT|TFTP server|UDP/69 (unicast)|Fetch kernel, dtb, initrd|

## Boot Flow 1: U-Boot TFTP (Labgrid-driven)

In this model Labgrid is in the loop at every step. The `UBootDriver` talks over serial, interrupts the autoboot countdown, and issues all commands explicitly. DHCP option 67 (`bootfile-name`) is not used - the strategy sets the path itself.

```
Client          Coordinator      Exporter        DCHP/TFTP host     DUT
  |                  |               |                |              |
  |--acquire(A)----->|               |                |              |
  |<--granted;-------|<--resources---|                |              |
  |                                   \               |              |
  |--ssh + rsync kernel B--------------\------------->|              |
  |   symlink at internal/Image         \             |              |
  |   stage() returns "board-a/Image"    \            |              |
  |                                       \           |              |
  |--power_off(A)--->|                     \          |              |
  |--power_on(A)---->|                      \         |              |
  |                  |--GPIO/USB cmd--------->|       |         [powers on]
  |                                           |       |              |
  |--read_serial()-->|                        |       |              |
  |  (watching for U-Boot prompt)             |       |              |
  |                  |<--serial: autoboot-----|<--------------[U-Boot starts]
  |                                           |       |              |
  |--uboot.run("setenv autoload no")--------->|--------------------->|
  |--uboot.run("dhcp")----------------------->|--------------------->|
  |                                           |       |<--DISCOVER---|
  |                                           |       |--OFFER:----->|
  |                                           |       |   IP: X.X.X.X         |
  |                                           |       |   siaddr: <TFTP host> |
  |                                           |       |              |
  |--uboot.run("setenv serverip <TFTP IP>")-->|--------------------->|
  |--uboot.run("tftp $addr board-a/Image")--->|--------------------->|
  |                                           |       |<--fetch board-a/Image-|
  |                                           |       |---Image----->|
  |--uboot.run("tftp $addr board-a/board.dtb")->|------------------->|
  |                                           |       |<--fetch dtb--|
  |                                           |       |---dtb------->|
  |--uboot.run("booti $kernel_addr_r - $dtb_addr")->|--------------->|
  |                    |<--serial: "login:"---|<--------------[kernel boots]
  |                                           |       |              |
  |--ShellDriver takes over via serial or SSH----------------------->|
```

### How kernel B gets mapped to board A

This is a combination of filesystem convention and the strategy driving U-Boot over serial. dnsmasq plays no role in kernel-to-board mapping.

**Per-board TFTP subdirectory (`RemoteTFTPProvider`)**

Each board in `exporter.yaml` declares a `RemoteTFTPProvider` with two fields:

```yaml
k3-pico-itx-tftp-1:
  cls: 'RemoteTFTPProvider'
  host: '192.168.254.17'
  internal: '/home/ubuntu/git/k3-host/tftp-root/k3-pico-itx/'  # absolute path on TFTP host
  external: 'k3-pico-itx/'                                       # TFTP-relative path
```

* `internal` is the absolute filesystem path on the TFTP host where this board's files live.
* `external` is the path a TFTP client uses to reach those files, relative to the TFTP root.

The per-board subdir name is whatever the admin puts in `external` - typically the board name. There is no MAC address logic anywhere in labgrid's TFTP provider code.

**File staging (`TFTPProviderDriver.stage()`)**

When a test calls `tftp.stage("/path/to/Image")`, the driver (`labgrid/driver/provider.py`):

1. Constructs `symlink = internal + basename(filename)` → `/srv/tftp/board-a/Image`
2. SSHes to the TFTP host via `ManagedFile.sync_to_resource()`:

   * Copies the file to a SHA256-content-addressed cache: `/var/cache/labgrid/<user>/<sha256>/Image`
   * Creates a symlink: `/srv/tftp/board-a/Image` → cache path
3. Returns `external + basename` → `"board-a/Image"`

That string is what gets passed directly to U-Boot's `tftp` command.

**The strategy drives U-Boot over serial**

```python
# threexc/boardgarden boards/muse-pi-pro/strategy.py
helpers.uboot_set_server_ip(self)
helpers.uboot_tftpboot_file(self, "$kernel_addr_r", "muse-pi-pro", "Image")
helpers.uboot_tftpboot_file(self, "$dtb_addr",      "muse-pi-pro", "k1-musepi-pro.dtb")
self.uboot.boot("tftp")  # sends "booti $kernel_addr_r - $dtb_addr"
```

```python
# boards/common/src/boardfarm_common/helpers.py
def uboot_set_server_ip(strategy, serverip=default_serverip):
    strategy.uboot.run("setenv autoload no")
    strategy.uboot.run("dhcp", timeout=10)   # gets IP only; autoload=no suppresses auto-TFTP
    strategy.uboot.run(f"setenv serverip {serverip}")

def uboot_tftpboot_file(strategy, loadaddr, board_name, file_name):
    strategy.uboot.run(f"tftp {loadaddr} {board_name}/{file_name}")
```

The strategy explicitly passes the full TFTP path to U-Boot. There is no DHCP option 67 or `dhcp-boot=` in dnsmasq. `setenv autoload no` before `dhcp` suppresses U-Boot's built-in behavior of auto-fetching whatever option 67 says - Labgrid wants to control that itself.

**Three layers of isolation:**

1. **Network** - each board is on its own NIC with its own dnsmasq instance (`bind-interfaces`). Board A cannot get board C's DHCP lease.
2. **Filesystem** - each board has its own TFTP subdirectory. Files for board A land at `board-a/`, never `board-c/`.
3. **Protocol** - the strategy explicitly passes `board-a/Image` to U-Boot. Even if network isolation broke down, the path is hardcoded per-board in the strategy.

## Boot Flow 2: PXE / UEFI (firmware-driven)

In this model Labgrid is largely a bystander during the boot sequence. The firmware (EDK II / UEFI, iPXE, or a PXE-capable U-Boot in "distro boot" mode) handles everything autonomously over the network before any interactive console prompt appears. There is no serial interaction during the download phase - Labgrid cycles power and then waits for a login prompt.

This is the direction boards with EDK II boot chains are heading (e.g. the SpacemiT K3 in `board-farm-playground`, and the RISC-V boards in `boardgarden`), though EDK II PXE support on those boards is still in progress - hence the commented-out `dhcp-boot=grubriscv64.efi` in their dnsmasq configs.

```
Client          Coordinator      Exporter        DCHP/TFTP host     DUT
  |                  |               |                |              |
  |--acquire(A)----->|               |                |              |
  |<--granted;-------|<--resources---|                |              |
  |                                   \               |              |
  |--ssh + rsync kernel B--------------\------------->|              |
  |   (MUST happen before power-on; no serial phase   |              |
  |    to wait in later)                 \            |              |
  |                                       \           |              |
  |--power_on(A)---->|                     \          |              |
  |                  |--GPIO/USB cmd--------->|       |         [powers on]
  |                                           |       |              |
  |  (Labgrid is silent; firmware drives all) |       |        [EDK II init]
  |                                           |       |<--DISCOVER---|
  |                                           |       |--OFFER:----->|
  |                                           |       |   IP: X.X.X.X            |
  |                                           |       |   siaddr: <TFTP host>    |
  |                                           |       |   opt67: grubriscv64.efi |
  |                                           |       |              |
  |                                           |       |<--fetch grubriscv64.efi--|
  |                                           |       |--grubriscv64.efi-------->|
  |                                           |       |              |
  |                                           |       |         [GRUB runs]
  |                                           |       |<--try: grub/grub.cfg-<UUID>--|
  |                                           |       |   (not found)                |
  |                                           |       |<--try: grub/grub.cfg-C0A8FE12--|
  |                                           |       |   (not found)                  |
  |                                           |       |<--try: grub/grub.cfg-01-50-0a-52-0b-e6-66--|
  |                                           |       |--grub.cfg-01-<MAC>------------------------>|
  |                                           |       |              |
  |                                           |       |<--fetch board-a/Image---------|
  |                                           |       |--Image----------------------->|
  |                                           |       |<--fetch board-a/board.dtb-----|
  |                                           |       |--dtb------------------------->|
  |                                           |       |              |
  |                  |<--serial: "login:"-----|<--------------[kernel boots]
  |                                           |                      |
  |--ShellDriver takes over------------------>|                      |
```

### MAC address lookups in PXE: what is standard vs. admin convention

This is a critical distinction that's easy to get wrong.

**What the bootloader enforces (standard, automatic):**

The bootloader automatically looks for its **config file** using MAC-based filenames. It does this with no admin involvement - it is built into the bootloader:

For **GRUB** (net boot), config is searched in this order from the directory where the GRUB EFI binary lives:

```
grub/grub.cfg-<EFI-UUID>
grub/grub.cfg-<IP-in-hex>           e.g. grub/grub.cfg-C0A8FE12
grub/grub.cfg-01-<mac-hyphenated>   e.g. grub/grub.cfg-01-50-0a-52-0b-e6-66
grub/grub.cfg                       (fallback)
```

For **pxelinux/syslinux** (BIOS PXE), config is searched in this order relative to the directory where `pxelinux.0` lives:

```
pxelinux.cfg/01-<mac-hyphenated>    e.g. pxelinux.cfg/01-50-0a-52-0b-e6-66
pxelinux.cfg/<IP-in-hex>            e.g. pxelinux.cfg/C0A8FE12
pxelinux.cfg/<IP-hex-shrinking>     (progressively shorter prefixes)
pxelinux.cfg/default
```

The `01-` prefix is the ARP hardware type byte (1 = Ethernet). This lookup is the bootloader's job - no dnsmasq or labgrid configuration needed.

**What is admin convention (not enforced by anything):**

The paths to the **kernel, dtb, and initrd** inside those config files can point anywhere under the TFTP root. The bootloader does not automatically look for kernels in MAC-named subdirectories. Putting kernels under `<mac>/vmlinuz` is purely a choice the admin writes into the config file content. Nothing enforces or discovers it.

Labgrid uses its own convention: per-board subdirectories named after the board (from the `external` field), not by MAC. The per-MAC GRUB config file then references those board-named paths:

```grub
# grub/grub.cfg-01-50-0a-52-0b-e6-66  (board A's MAC - found automatically by GRUB)
set default=0
set timeout=0

menuentry "Linux" {
    linux   board-a/Image console=ttyS0,115200 root=/dev/mmcblk0p2 rootwait
    devicetree board-a/board.dtb
    # ^^^^^ these paths are admin convention, not enforced by GRUB
    # they match the 'external' field in board A's RemoteTFTPProvider config
}
```

GRUB resolves `linux` and `devicetree` paths relative to its `$prefix` (the directory where the GRUB EFI binary lives, set at net boot time). If `grubriscv64.efi` is at the TFTP root, then `board-a/Image` resolves to `<tftp-root>/board-a/Image` - the same location that `TFTPProviderDriver.stage()` wrote it.

**Labgrid has zero MAC address logic.** There is no MAC-based path construction anywhere in `labgrid/resource/remote.py`, `labgrid/driver/provider.py`, or any strategy file. The framework does not know board MAC addresses. The `external` field is whatever the admin named it.

### dnsmasq config for PXE

The only addition versus the U-Boot TFTP config is `dhcp-boot=`:

```ini
interface=enxc84d4433b782
bind-interfaces
dhcp-range=192.168.254.18,192.168.254.30,255.255.255.240,24h
dhcp-option=option:router,192.168.254.17
enable-tftp
tftp-root=/srv/tftp
dhcp-boot=grubriscv64.efi   # sets option 67 + siaddr; absent in U-Boot TFTP setup
```

`dhcp-boot=` does two things: sets DHCP option 67 (`bootfile-name`) to `grubriscv64.efi`, and sets `siaddr` (next-server) to the dnsmasq host's IP. Every board on that segment gets the same boot filename - they all load the same GRUB binary. Per-board differentiation happens in GRUB via the MAC-based config lookup.

_Note(Ludovic): These IP ranges and masks are specific to my setup at home_

### TFTP directory layout for PXE

```
tftp-root/
  grubriscv64.efi                        <- option 67 target; one binary for all boards
  grub/
    grub.cfg                             <- fallback
    grub.cfg-01-50-0a-52-0b-e6-66        <- board A (static, maintained outside labgrid)
    grub.cfg-01-aa-bb-cc-dd-ee-ff        <- board B
  board-a/                               <- RemoteTFTPProvider external="board-a/"
    Image    -> /var/cache/labgrid/.../Image    (symlink, written by stage() at test time)
    board.dtb -> /var/cache/labgrid/.../board.dtb
  board-b/
    Image -> ...
    board.dtb -> ...
```

The `grub/` files are **static infrastructure** maintained outside Labgrid alongside the dnsmasq config - Labgrid never generates or modifies them. The `board-a/` leaf files are managed dynamically by `stage()` before each test.

### iPXE

iPXE has no built-in automatic MAC-based config lookup. It boots an embedded or DHCP-supplied iPXE script. However, the MAC address is available as a scripting variable (`${net0/mac}`), so an admin can script per-board behavior explicitly:

```ipxe
chain tftp://${next-server}/${net0/mac:hexhyp}/boot.ipxe
```

This is entirely script-driven - nothing happens automatically by MAC. It is the most flexible option but requires all the per-board routing logic to be written in the iPXE script.

### Labgrid has no native PXE support

There is no `PXEStrategy`, `PXEDriver`, or PXE-related code anywhere in the labgrid source. Strategies, drivers, and resources that exist: `UBootStrategy`, `BareboxStrategy`, `ShellStrategy`, `DockerStrategy`, `TFTPProviderDriver`, `NFSProviderDriver`, `HTTPProviderDriver`. No PXE.

The strategy for a PXE-booted board is simply:

```python
self.power.cycle()
self.target.activate(self.shell)  # block until login prompt appears on serial
```

The firmware does everything in between.

## Boot Method Comparison

|Aspect|U-Boot TFTP|UEFI PXE (GRUB)|iPXE|
|-|-|-|-|
|Who drives the download|Labgrid, via serial|Firmware, autonomously|Firmware, via script|
|DHCP option 67 needed|No|Yes (`dhcp-boot=grubriscv64.efi`)|Yes (iPXE script filename)|
|Per-board config lookup|None - Labgrid passes path explicitly|Bootloader auto-looks up `grub.cfg-01-<mac>`|Script-driven (`${net0/mac}`)|
|Kernel/dtb path source|`stage()` return value, passed to `tftp`|Hardcoded in static per-MAC GRUB config|Hardcoded in per-board iPXE script|
|Who writes kernel/dtb path|Labgrid strategy Python code|Admin, in static GRUB config file|Admin, in static iPXE script|
|MAC used for path lookup|Never|Config file name only; kernel paths are admin choice|Only if admin scripts it|
|Stage timing|After serial interrupt, before boot commands|Before power-on|Before power-on|
|Serial interaction during boot|Yes (interrupt, setenv, tftp, booti)|No|No|
|Labgrid native driver|`UBootDriver` + `UBootStrategy`|None; power + wait for shell|None; power + wait for shell|
|Isolation layers|Network + filesystem + explicit serial path|Network + MAC-based GRUB config + filesystem|Network + script-routed + filesystem|

## Where DHCP and TFTP Must Live

Placement is determined by **network physics**, not by Labgrid's process model.

**DHCP** must run on a host that shares an L2 broadcast domain with the DUT's boot NIC. DHCP DISCOVER is sent to 255.255.255.255 and cannot cross a router. Options:

* Run DHCP on the host directly cabled to the DUT (most common in small farms).
* Run DHCP anywhere on the same L2 segment (same switch, no routing hop).
* Use a DHCP relay (`dhcrelay` / `ip helper-address`) to bridge broadcast across a router (common in larger farms).

In practice DHCP almost always lives on the Exporter host, since that host already has the DUT-facing NIC.

**TFTP** is unicast UDP/69. Once the DUT has an IP it makes a directed connection, so TFTP only needs IP reachability to the DUT. No L2 constraint.

* For U-Boot TFTP: `serverip` is set by the strategy over serial, independently of DHCP.
* For PXE: the TFTP server address comes from DHCP `siaddr` / option 66, also no L2 constraint.

**`RemoteTFTPProvider.host`** is not the address the DUT connects to for TFTP. It is the address the **test client SSHes into** to stage files. It can be any SSH-reachable host - same machine as DHCP, same machine as the Exporter, or a completely separate storage server.

### Component placement summary

|Component|Fixed to Exporter host?|Actual constraint|
|-|-|-|
|Labgrid Exporter process|**Yes**|Needs `/dev` access: serial, power relay, sd-mux|
|Labgrid Coordinator|No|Any network-reachable host|
|DHCP daemon|No, but constrained|Must share L2 with DUT's NIC, or use a DHCP relay|
|TFTP daemon|No|Any host with IP route to DUT|
|`RemoteTFTPProvider.host`|No|Any SSH-reachable host; client stages files here|

## Real-World Examples

### `luhenry/board-farm-playground` - everything co-located, U-Boot TFTP

One Raspberry Pi hosts Coordinator, Exporter, and dnsmasq (DHCP + TFTP).

```
[Raspberry Pi]  192.168.254.17
  - labgrid-coordinator
  - labgrid-exporter
  - dnsmasq (DHCP + TFTP on enxc84d4433b782)
  - tftp-root: /home/ubuntu/git/k3-host/tftp-root/
       k3-pico-itx/
           Image    -> /var/cache/labgrid/.../Image   (symlink, written at test time)
           k1.dtb   -> ...
     |
     | enxc84d4433b782
     |
[SpacemiT K3 DUT]  192.168.254.18
```

`dnsmasq/k3-pico-itx.conf`:

```ini
interface=enxc84d4433b782
bind-interfaces
dhcp-range=192.168.254.18,192.168.254.30,255.255.255.240,24h
dhcp-option=option:router,192.168.254.17
enable-tftp
tftp-root=/home/ubuntu/git/k3-host/tftp-root
# dhcp-boot=grubriscv64.efi  <- commented out; EDK II PXE not yet functional on this board
```

Repo: https://github.com/luhenry/board-farm-playground

### `threexc/boardgarden` (BayLibre) - TFTP on a dedicated machine, U-Boot TFTP

DHCP stays on `ecogrid` (L2-adjacent to boards), TFTP is split to `ecovault` (dedicated storage).

```
[ecogrid]  <- Coordinator + Exporter + DHCP
  |  (directly cabled to all boards)
  |
[DUTs]  -> DHCP from ecogrid -> IP assigned
        -> serverip set to 192.168.40.134 by strategy over serial
        -> TFTP from ecovault

[ecovault]  192.168.40.134
  - tftpd serving /srv/tftp/
       muse-pi-pro/    Image -> /var/cache/labgrid/...
       bananapi-f3/
       orangepi-rv2/
```

All boards in `exporter.yaml` use `RemoteTFTPProvider.host: '192.168.40.134'`. The test runner SSHes to `ecovault` to stage files; boards fetch from `ecovault` over TFTP.

If PXE were enabled on this farm, `ecovault`'s `/srv/tftp/` would gain:

```
/srv/tftp/
  grubriscv64.efi
  grub/
    grub.cfg-01-<muse-pi-pro MAC>    <- one static file per board, maintained outside labgrid
    grub.cfg-01-<bananapi-f3 MAC>
    grub.cfg-01-<orangepi-rv2 MAC>
  muse-pi-pro/    <- already managed by stage() today, no change needed
  bananapi-f3/
  orangepi-rv2/
```

Repo: https://github.com/threexc/boardgarden  
Architecture diagram: `docs/network.mmd` / `docs/network.png` in that repo

## Key Gotcha: dnsmasq `bind-interfaces`

On a host with multiple NICs (uplink + DUT-facing dongle), dnsmasq by default sends DHCP OFFERs out whichever interface the routing table selects - usually the uplink, not the DUT-facing NIC. The DUT loops forever sending DISCOVERs and never gets a lease.

Always use `bind-interfaces` + `interface=<dev>` to pin dnsmasq to the correct interface. Documented in detail in `board-farm-playground/notes.md` sections 5.1, 7, and 17.3.

## Relevant Source Locations

|File|What it does|
|-|-|
|`labgrid/resource/remote.py`|`RemoteTFTPProvider` - `host`, `internal`, `external` fields; no MAC logic|
|`labgrid/driver/provider.py`|`TFTPProviderDriver.stage()` - constructs symlink, returns TFTP-relative path|
|`labgrid/util/managedfile.py`|`ManagedFile.sync_to_resource()` - SSHes to host, copies file, creates symlink|
|`labgrid/driver/ubootdriver.py`|`UBootDriver.run()`, `boot()` - serial console commands|
|`labgrid/strategy/ubootstrategy.py`|Reference `UBootStrategy` - interrupt, prompt, boot|
|`boardgarden/boards/muse-pi-pro/strategy.py`|Full U-Boot TFTP flow: stage + serverip + tftp + booti|
|`boardgarden/boards/common/.../helpers.py`|`uboot_set_server_ip()`, `uboot_tftp_file()`|

## Further Reading

* Official Labgrid docs: https://labgrid.readthedocs.io/en/latest/
* ELC Europe 2018 - "Automated Embedded Linux Testing with Labgrid" by Jan Luebbe: https://elinux.org/ELC_Europe_2018_Presentations
* FOSDEM labgrid talks (2019/2020): search https://fosdem.org for "labgrid"
* BayLibre blog: https://baylibre.com/blog/
* syslinux/pxelinux docs: https://wiki.syslinux.org/wiki/index.php?title=PXELINUX
* GRUB net boot manual: https://www.gnu.org/software/grub/manual/grub/grub.html#Network

