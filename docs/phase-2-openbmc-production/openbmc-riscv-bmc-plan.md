# OpenBMC RISC-V Lab BMC — Implementation Plan

**Status:** Draft | **Authors:** [Puneetha Ramachandra](mailto:puneetha@google.com), [Ludovic Henry](mailto:ludovic.henry@qti.qualcomm.com)

## Context

You have 200–300 RISC-V machines spread across ~8–12 exporter hosts (24–48 machines per host).
Each exporter host has:
- USB-to-serial adapters (one per RISC-V board) for console access
- A USB-controlled PSU/hub (one port per RISC-V board) for power control
- Network connectivity to the RISC-V boards

Goal: replace the LabGrid-based management with an OpenBMC-compatible interface exposing
Redfish per-machine, so that any Redfish client (Ansible, Metal³, python-redfish, etc.) can
manage each RISC-V board as if it had a dedicated BMC.

## Architecture Overview

```
                        ┌──────────────────────────────────────────┐
                        │  Exporter Host (x86 Linux, runs OpenBMC) │
                        │                                          │
  machines.yaml ───────►│  riscv-bmc-agent                         │
  (shared, git)         │  - reads global config                   │
                        │  - detects which USB devices are local   │
                        │  - publishes D-Bus objects for each      │
                        │                                          │
                        │  /xyz/openbmc_project/state/chassis0     │
                        │  /xyz/openbmc_project/state/chassis1     │
                        │  ...chassis23                            │
                        │                                          │
                        │  obmc-console@host0.service              │
                        │  obmc-console@host1.service              │
                        │  ...                                     │
                        │                                          │
                        │  bmcweb (Redfish + WebSocket SOL)        │
                        │  GET /redfish/v1/Systems/system0         │
                        │  GET /redfish/v1/Systems/system1         │
                        └──────────────────────────────────────────┘
```

OpenBMC runs on the exporter host itself (not on the RISC-V boards).
The exporter host IS the BMC.

## Key Research Findings (OpenBMC internals)

### phosphor-state-manager multi-host
- Launched with `-c N` flag, creates `/xyz/openbmc_project/state/chassis{N}` and `host{N}`
- Service name: `xyz.openbmc_project.State.Chassis{N}` per instance
- SMP aggregation: chassis0 can aggregate chassis1..N (enabled by default, max 12,
  configurable via `num-chassis-smp` meson option — raise this for 24–48 boards)
- Persist paths use `{}` format: `chassis{}-POHCounter`, `host{}-PersistData`

### obmc-console multi-instance
- Systemd template: `obmc-console@%i.service` / `obmc-console@%i.socket`
- Config file per instance: `/etc/obmc-console/server.{id}.conf`
- Abstract Unix socket: `@obmc-console.{id}` (e.g. `@obmc-console.host0`)
- bmcweb connects to the socket for WebSocket SOL

### bmcweb multi-host (Redfish)
- Build flag: `-Dexperimental-redfish-multi-computer-system=enabled`
- Status: experimental but actively developed, scheduled to stabilize by 2027
- Discovery: reads D-Bus inventory for `xyz.openbmc_project.Inventory.Item.System`
  objects; each one becomes a `/redfish/v1/Systems/{name}` endpoint
- Also reads `xyz.openbmc_project.Inventory.Decorator.Asset` for serial/model/name

### phosphor-inventory-manager
- Inventory items at `/xyz/openbmc_project/inventory/system/chassis{N}`
- YAML-driven object creation (event/action pattern)
- Asset decorator carries: Manufacturer, Model, PartNumber, SerialNumber, SparePartNumber
- Associations link inventory items to sensors and state objects

## The Single Config File Design

### Core insight: USB device serial numbers as global unique IDs

Every USB device has a serial number field in its USB descriptor, accessible via udev:

```
/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A9B2C3D4-if00-port0
                                              ^^^^^^^^
                                              USB serial number
```

Read it: `udevadm info /dev/ttyUSB0 | grep ID_SERIAL_SHORT`

This number is:
- Globally unique (per adapter, not per host)
- Stable across reboots on any host
- Stable if the adapter is moved to a different exporter host
- Independent of which `/dev/ttyUSBN` number the kernel assigns

Same principle applies to USB hubs with `uhubctl`: hubs have their own USB serial numbers.

**Caveat:** Cheap CH340/CP2102 clone adapters often ship with zeroed-out serial numbers.
Use FTDI FT232R, FTDI FT2232H, or program unique serials into CP2102 with `cp210x-cfg`.
Verify with: `lsusb -v | grep iSerial`

### machines.yaml

```yaml
# /etc/riscv-bmc/machines.yaml
# Single file, shared across all exporter hosts (git-managed, Ansible-distributed).
# Each machine is identified by globally unique USB hardware IDs.
# The agent on each host reads this file and only instantiates objects
# for machines whose USB devices are physically present on that host.

version: 1

defaults:
  console_baud: 115200
  power_on_delay_ms: 500

machines:
  - id: riscv-001
    display_name: "RISC-V Board 001"
    asset:
      manufacturer: "SiFive"
      model: "HiFive Unmatched"
      serial_number: "SV001-A"     # board's own serial, for Redfish Asset info
    console:
      usb_serial_id: "A9B2C3D4"   # USB serial of the USB-serial adapter
      baud: 115200
    power:
      usb_hub_serial_id: "HUB001AA"  # USB serial of the USB hub
      port: 1                          # port number on that hub

  - id: riscv-002
    display_name: "RISC-V Board 002"
    asset:
      manufacturer: "SiFive"
      model: "HiFive Unmatched"
      serial_number: "SV001-B"
    console:
      usb_serial_id: "A9B2C3D5"
      baud: 115200
    power:
      usb_hub_serial_id: "HUB001AA"
      port: 2

  # ... up to 300 entries total, covering all exporter hosts
```

### How the agent resolves this at runtime

```python
# On startup, the agent:
# 1. Reads machines.yaml
# 2. Enumerates local USB serial adapters via udev
# 3. Matches by usb_serial_id
# 4. Only instantiates D-Bus objects for matched (locally present) machines
# 5. Assigns D-Bus index 0..N to matched machines in stable sorted order

import pyudev
context = pyudev.Context()

def find_local_serial_ttys():
    """Returns {usb_serial_id: tty_path} for all USB-serial adapters on this host."""
    result = {}
    for device in context.list_devices(subsystem='tty'):
        serial_id = device.get('ID_SERIAL_SHORT')
        if serial_id:
            result[serial_id] = device.device_node
    return result

def find_local_hubs():
    """Returns {usb_serial_id: hub_location} for uhubctl."""
    # Parse uhubctl -l output or use pyudev usb subsystem
    ...
```

## Component: riscv-bmc-agent (the bridge daemon)

### Role
- Reads `machines.yaml`
- Detects which machines are local via USB device presence
- Publishes D-Bus objects for each local machine
- Handles power transitions via `uhubctl`
- Generates `obmc-console` config files dynamically
- Writes `phosphor-inventory-manager` YAML for asset info

### Language and D-Bus library

Use **Python + `sdbus-python`** (modern, async-native, actively maintained).
Alternative: `dasbus` (simpler API, uses GLib main loop).

Avoid `dbus-python` (deprecated) and `pydbus` (unmaintained).

### D-Bus interfaces to implement per machine

#### 1. Chassis power state
```
Object path:  /xyz/openbmc_project/state/chassis{N}
Service name: xyz.openbmc_project.State.Chassis{N}
Interface:    xyz.openbmc_project.State.Chassis

Properties:
  CurrentPowerState  (string, read)
    "xyz.openbmc_project.State.Chassis.PowerState.On"
    "xyz.openbmc_project.State.Chassis.PowerState.Off"

  RequestedPowerTransition  (string, read-write)
    "xyz.openbmc_project.State.Chassis.Transition.On"   → uhubctl port on
    "xyz.openbmc_project.State.Chassis.Transition.Off"  → uhubctl port off
```

#### 2. Host boot state
```
Object path:  /xyz/openbmc_project/state/host{N}
Service name: xyz.openbmc_project.State.Host{N}
Interface:    xyz.openbmc_project.State.Host

Properties:
  CurrentHostState  (string, read)
    "xyz.openbmc_project.State.Host.HostState.Off"
    "xyz.openbmc_project.State.Host.HostState.Running"
    "xyz.openbmc_project.State.Host.HostState.Quiesced"

  RequestedHostTransition  (string, read-write)
    "xyz.openbmc_project.State.Host.Transition.On"
    "xyz.openbmc_project.State.Host.Transition.Off"
    "xyz.openbmc_project.State.Host.Transition.Reboot"
```

#### 3. Inventory + Asset (for Redfish System info)
```
Object path: /xyz/openbmc_project/inventory/system/chassis{N}
Interfaces:
  xyz.openbmc_project.Inventory.Item
    Present: true
    PrettyName: "riscv-001"

  xyz.openbmc_project.Inventory.Item.System
    (marker interface — presence triggers bmcweb to create Redfish System)

  xyz.openbmc_project.Inventory.Decorator.Asset
    Manufacturer: "SiFive"
    Model: "HiFive Unmatched"
    SerialNumber: "SV001-A"
    PartNumber: ""

  xyz.openbmc_project.Inventory.Decorator.ManagedHost
    (links inventory item to host{N} state object)
```

### Daemon structure (Python pseudocode)

```python
#!/usr/bin/env python3
import sdbus
import yaml
import pyudev
import asyncio
import subprocess

class RiscvBmcAgent:
    def __init__(self, config_path):
        self.config = yaml.safe_load(open(config_path))
        self.local_ttys = self.find_local_serial_ttys()
        self.local_hubs = self.find_local_hubs()
        self.local_machines = self.resolve_local_machines()

    def resolve_local_machines(self):
        machines = []
        for m in self.config['machines']:
            tty_serial = m['console']['usb_serial_id']
            hub_serial = m['power']['usb_hub_serial_id']
            if tty_serial in self.local_ttys and hub_serial in self.local_hubs:
                machines.append(m)
        # Sort for stable D-Bus index assignment
        return sorted(machines, key=lambda m: m['id'])

    async def run(self):
        bus = sdbus.sd_bus_open_system()
        for idx, machine in enumerate(self.local_machines):
            await self.register_chassis(bus, idx, machine)
            await self.register_host(bus, idx, machine)
            await self.register_inventory(bus, idx, machine)
            self.write_console_config(idx, machine)
        await asyncio.get_event_loop().run_forever()

    def power_on(self, machine):
        hub_loc = self.local_hubs[machine['power']['usb_hub_serial_id']]
        port = machine['power']['port']
        subprocess.run(['uhubctl', '-l', hub_loc, '-p', str(port), '-a', '1'], check=True)

    def power_off(self, machine):
        hub_loc = self.local_hubs[machine['power']['usb_hub_serial_id']]
        port = machine['power']['port']
        subprocess.run(['uhubctl', '-l', hub_loc, '-p', str(port), '-a', '0'], check=True)

    def write_console_config(self, idx, machine):
        tty = self.local_ttys[machine['console']['usb_serial_id']]
        baud = machine['console'].get('baud', self.config['defaults']['console_baud'])
        config_path = f"/etc/obmc-console/server.host{idx}.conf"
        with open(config_path, 'w') as f:
            f.write(f"[default]\n")
            f.write(f"tty = {tty}\n")
            f.write(f"baud = {baud}\n")
        # Start/restart obmc-console@host{idx}.service
        subprocess.run(['systemctl', 'restart', f'obmc-console@host{idx}.service'])
```

## Yocto Layer Structure

```
meta-riscv-bmc/
├── conf/
│   ├── layer.conf
│   └── machine/
│       └── riscv-bmc-host.conf     # machine config for x86-64 exporter host
│           # KERNEL_FEATURES += "..."
│           # MACHINE_FEATURES = "..."
│           # inherit x86 / qemux86-64 as base
├── recipes-core/
│   └── images/
│       └── riscv-bmc-image.bb      # IMAGE_INSTALL += "..."
├── recipes-phosphor/
│   ├── state/
│   │   └── phosphor-state-manager_%.bbappend
│   │       # EXTRA_OEMESON += "-Dnum-chassis-smp=48"
│   │       # SYSTEMD_SERVICE:${PN} += "xyz.openbmc_project.State.Chassis@.service"
│   ├── console/
│   │   └── obmc-console_%.bbappend
│   │       # No static TTYS — riscv-bmc-agent writes configs dynamically
│   └── bmcweb/
│       └── bmcweb_%.bbappend
│           # EXTRA_OEMESON += "-Dexperimental-redfish-multi-computer-system=enabled"
│           # EXTRA_OEMESON += "-Dredfish-system-uri-name=system"
└── recipes-riscv-bmc/
    └── riscv-bmc-agent/
        ├── riscv-bmc-agent.bb
        │   # SRC_URI = "..."
        │   # RDEPENDS:${PN} = "python3 python3-sdbus python3-pyudev uhubctl"
        │   # SYSTEMD_SERVICE:${PN} = "riscv-bmc-agent.service"
        └── files/
            ├── riscv-bmc-agent.py
            ├── riscv-bmc-agent.service
            └── machines.yaml           # the shared config, baked into image
                                        # OR: loaded from NFS/git-ops at runtime
```

### riscv-bmc-host.conf (machine config)

```bitbake
# conf/machine/riscv-bmc-host.conf
require conf/machine/qemux86-64.conf   # or actual x86 BSP for your exporter hardware

MACHINE_FEATURES = "usbhost serial"
DISTRO_FEATURES:append = " usb"

# OpenBMC distro feature flags
DISTRO_FEATURES:append = " obmc-phosphor-state-management"
```

## obmc-console Multi-Instance Setup

The agent generates configs at runtime. Static example for reference:

```ini
# /etc/obmc-console/server.host0.conf
[default]
tty = /dev/ttyUSB0        # resolved from usb_serial_id at agent startup
baud = 115200
logfile = /var/log/obmc-console/host0.log
```

Enable instances in the image:
```bitbake
# In riscv-bmc-image.bb or obmc-console bbappend
OBMC_CONSOLE_TTYS = ""   # empty — agent manages instances dynamically

# The systemd template is already shipped by obmc-console:
# obmc-console@.service is enabled; agent calls systemctl start obmc-console@host{N}
```

Redfish SOL endpoint (created automatically by bmcweb once console socket exists):
```
/redfish/v1/Systems/system{N}/Actions/ComputerSystem.Reset
/redfish/v1/Managers/bmc/SerialInterfaces/host{N}   ← WebSocket SOL
```

## bmcweb Configuration for Redfish

```bitbake
# recipes-phosphor/bmcweb/bmcweb_%.bbappend
EXTRA_OEMESON += " \
    -Dexperimental-redfish-multi-computer-system=enabled \
    -Dinsecure-disable-ssl=disabled \
    -Dredfish=enabled \
    -Dhttp-body-limit=512 \
"
```

Once `xyz.openbmc_project.Inventory.Item.System` objects exist in D-Bus, bmcweb
automatically creates:
```
GET /redfish/v1/Systems/                    → lists all systems
GET /redfish/v1/Systems/riscv-001           → system detail (power state, asset info)
POST /redfish/v1/Systems/riscv-001/Actions/ComputerSystem.Reset
    Body: {"ResetType": "ForceOff"}         → triggers chassis power off via D-Bus
GET /redfish/v1/Managers/bmc               → the exporter host BMC itself
```

## Deployment at Scale

### Config distribution

Option A — baked into image (simplest, needs image rebuild to add machines):
```bitbake
SRC_URI += "file://machines.yaml"
```

Option B — mounted from NFS / config management (recommended for 300 machines):
```ini
# riscv-bmc-agent.service
[Unit]
After=network-online.target nss-lookup.target
Requires=network-online.target

[Service]
ExecStartPre=/usr/bin/fetch-config  # pulls machines.yaml from git/S3/NFS
ExecStart=/usr/bin/riscv-bmc-agent --config /etc/riscv-bmc/machines.yaml
Restart=on-failure
```

Option C — Ansible-managed (push machines.yaml to each exporter, agent auto-reloads):
```yaml
# Ansible task
- name: Deploy machines config
  copy:
    src: machines.yaml
    dest: /etc/riscv-bmc/machines.yaml
  notify: Restart riscv-bmc-agent
```

### SIGHUP reload (no restart needed to add machines)

The agent should handle `SIGHUP` by re-reading `machines.yaml`, diffing against currently
registered machines, and adding/removing D-Bus objects + console service instances
accordingly.

### Multi-exporter Redfish aggregation (optional, for unified API)

If you want a single Redfish endpoint for all 300 machines:

Use **Redfish Aggregation** (a bmcweb feature): one "aggregator" bmcweb instance proxies
to N subordinate bmcweb instances (one per exporter host). Each machine then appears at:
```
/redfish/v1/AggregationService/AggregationSources/{exporter}/
/redfish/v1/Systems/{exporter}.system{N}
```

This requires bmcweb built with `-Dredfish-aggregation=enabled` on the aggregator node.
The aggregator itself can run on any host or in a container.

## USB Serial Number — Practical Notes

### Verifying uniqueness
```bash
# List all USB serial adapters and their hardware serial numbers
for tty in /dev/ttyUSB*; do
    serial=$(udevadm info "$tty" | grep ID_SERIAL_SHORT | cut -d= -f2)
    echo "$tty: $serial"
done

# Check for duplicates (bad adapters)
udevadm info /dev/ttyUSB* | grep ID_SERIAL_SHORT | sort | uniq -d
```

### Programming serial numbers into CP2102 adapters
```bash
# If your adapters have blank/duplicate serials, program unique ones:
cp210x-cfg -d <bus>:<dev> -S "RISCV-$(printf '%04d' $N)"
```

### udev rule to create stable symlinks (alternative to relying on agent detection)
```
# /etc/udev/rules.d/99-riscv-consoles.rules
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{serial}=="A9B2C3D4", \
    SYMLINK+="riscv-console-001"
```

## phosphor-state-manager: Raising the Multi-Host Limit

The default SMP cap is 12 chassis. For 48 boards per exporter:

```bitbake
# recipes-phosphor/state/phosphor-state-manager_%.bbappend
EXTRA_OEMESON += "-Dnum-chassis-smp=48"
```

This controls how many chassis instances chassis0 aggregates. Each instance is still
launched as a separate systemd service instance.

## Prior Art and Lessons from Similar Projects

### sushy-tools (OpenStack)
- Wraps libvirt VMs with a Redfish API (closest architectural parallel)
- Key lesson: they use a driver model (`SushyEmulator` backend) — consider the same
  pattern so your agent can swap out `uhubctl` for other power controllers without
  rewriting the D-Bus layer
- Source: https://opendev.org/openstack/sushy-tools

### VirtualBMC (OpenStack)
- Wraps libvirt VMs with IPMI (not Redfish) — less relevant but same topology
- Key lesson: runs one process per VM, which doesn't scale; consider one process managing
  all machines on a host (which is what this plan does)

### LabGrid exporter model
- LabGrid treats each resource (serial, power, network) as independent; you combine them
  at the coordinator layer
- Key lesson: LabGrid's resource identification by USB path is fragile across kernel
  reboots — USB serial number is strictly better
- Your approach supersedes LabGrid for anything Redfish clients can consume

### Metal³ (Kubernetes bare-metal)
- Uses Redfish (via `gofish`) to provision bare-metal hosts
- Once your Redfish endpoints are live, Metal³ works against them with no modification
- Key lesson: Metal³ requires `InsecureBootCapability` and accurate `BootProgress` state;
  implement `xyz.openbmc_project.State.Boot.Progress` D-Bus interface if you want Metal³
  
## Implementation Phases

### Phase 1 — Single machine proof of concept
- Build OpenBMC for one exporter host (use `qemux86-64` machine as base)
- Write minimal `riscv-bmc-agent` for one machine: power + console
- Verify Redfish: `GET /redfish/v1/Systems/system0`, power on/off

### Phase 2 — Multi-host on one exporter
- Enable `experimental-redfish-multi-computer-system`
- Implement dynamic D-Bus index assignment from USB serial matching
- Test obmc-console multi-instance
- Verify SOL via WebSocket

### Phase 3 — Shared config file
- Move to `machines.yaml` with USB serial IDs
- Test moving an adapter between exporter hosts (config unchanged, agent auto-detects)
- Add SIGHUP reload

### Phase 4 — Scale to full fleet
- Deploy to all exporter hosts via Ansible
- Set up Redfish aggregation if unified endpoint is needed
- Integrate with your existing Ansible/Metal³/Ironic tooling

## Key Files and Repos to Read

| Repo | File | Why |
|------|------|-----|
| phosphor-state-manager | `chassis_state_manager_main.cpp` | chassis{N} instantiation |
| phosphor-state-manager | `chassis_state_manager_smp.cpp` | SMP aggregation logic |
| phosphor-state-manager | `meson.options` | `num-chassis-smp` option |
| obmc-console | `conf/obmc-console@.service.in` | multi-instance template |
| obmc-console | `config.c` | config file parsing |
| bmcweb | `meson.options` | `experimental-redfish-multi-computer-system` |
| bmcweb | `redfish-core/include/utils/systems_utils.hpp` | D-Bus discovery logic |
| phosphor-inventory-manager | `manager.cpp` | inventory object creation |
| openbmc/openbmc | `meta-phosphor/` | reference layer structure |
| openbmc/openbmc | `meta-ibm/` | real multi-host machine example |
