import os
from typing import Dict, Any

HOST = os.environ.get("HUB_HOST", "0.0.0.0")
PORT = int(os.environ.get("HUB_PORT", "8080"))
DB_PATH = os.environ.get("HUB_DB_PATH", os.path.expanduser("~/board-farm-hub/hub.db"))
LG_COORDINATOR = os.environ.get("LG_COORDINATOR", "127.0.0.1:20408")
POLL_INTERVAL_SECS = int(os.environ.get("POLL_INTERVAL_SECS", "30"))
COORDINATOR_POLL_INTERVAL_SECS = int(os.environ.get("COORDINATOR_POLL_INTERVAL_SECS", "3"))

BOARD_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "a210-board-01": {
        "short_name": "a210-1",
        "ip": "10.6.4.12",
        "serial_port": "/dev/ttyUSB0",
        "mac": "48:da:00:00:01:00",
        "soc": "T-Head C920 Dual-Core RISC-V",
        "arch": "riscv64",
        "ram_gb": 4,
        "emmc_gb": 32,
    },
    "a210-board-02": {
        "short_name": "a210-2",
        "ip": "10.6.4.13",
        "serial_port": "/dev/ttyUSB1",
        "mac": "48:da:00:00:02:00",
        "soc": "T-Head C920 Dual-Core RISC-V",
        "arch": "riscv64",
        "ram_gb": 4,
        "emmc_gb": 32,
    },
    "a210-board-03": {
        "short_name": "a210-3",
        "ip": "10.6.4.14",
        "serial_port": "/dev/ttyUSB2",
        "mac": "48:da:00:00:03:00",
        "soc": "T-Head C920 Dual-Core RISC-V",
        "arch": "riscv64",
        "ram_gb": 4,
        "emmc_gb": 32,
    },
    "a210-board-04": {
        "short_name": "a210-4",
        "ip": "10.6.4.15",
        "serial_port": "/dev/ttyUSB3",
        "mac": "48:da:00:00:04:00",
        "soc": "T-Head C920 Dual-Core RISC-V",
        "arch": "riscv64",
        "ram_gb": 4,
        "emmc_gb": 32,
    },
    "a210-board-05": {
        "short_name": "a210-5",
        "ip": "10.6.4.16",
        "serial_port": "/dev/ttyUSB4",
        "mac": "48:da:00:00:05:00",
        "soc": "T-Head C920 Dual-Core RISC-V",
        "arch": "riscv64",
        "ram_gb": 4,
        "emmc_gb": 32,
        "k8s_worker": True,
    },
}
