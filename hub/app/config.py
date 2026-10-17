import os
from typing import Dict, Any, List, Tuple

HOST = os.environ.get("HUB_HOST", "0.0.0.0")
PORT = int(os.environ.get("HUB_PORT", "8080"))
DB_PATH = os.environ.get("HUB_DB_PATH", "/opt/board-farm-hub/hub.db")
LG_COORDINATOR = os.environ.get("LG_COORDINATOR", "127.0.0.1:20408")
SSH_KEY_PATH = os.environ.get("HUB_SSH_KEY", "")
POLL_INTERVAL_SECS = int(os.environ.get("POLL_INTERVAL_SECS", "30"))
COORDINATOR_POLL_INTERVAL_SECS = int(os.environ.get("COORDINATOR_POLL_INTERVAL_SECS", "3"))
CLUSTER_LOCATION = os.environ.get("HUB_LOCATION", "osuosl-milne")

# List of (relay_url, token_file_path) pairs for pushing live board state.
# - relay_url: Public web app endpoint (e.g. Google Apps Script /exec URL).
# - token_file_path: Shared path on the labgrid controller host containing the
#   secret token (chmod 640 root/user:rise, never committed to Git).
REMOTE_RELAYS: List[Tuple[str, str]] = [
    (
        os.environ.get(
            "GAS_RELAY_URL",
            "https://script.google.com/macros/s/AKfycbwv98a34Xys62GcmMtx_3crm_dAxvrvpWIRZLm1QwHxpkmnmkL2igX_pfGXwEqkD4se/exec",
        ),
        os.environ.get("GAS_TOKEN_FILE", "/opt/board-farm-hub/tokens/gas.token"),
    ),
]


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
