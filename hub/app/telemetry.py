import asyncio
import logging
import re
import socket
from typing import Dict, Any, Tuple
from app.config import BOARD_DEFINITIONS
from app.db import upsert_telemetry

logger = logging.getLogger("hub.telemetry")

async def check_port_open(ip: str, port: int = 22, timeout: float = 1.5) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

async def poll_board_telemetry(board_name: str, ip: str, is_k8s_worker: bool = False):
    is_online = await check_port_open(ip, 22, timeout=1.5)
    if not is_online:
        upsert_telemetry(
            board_id=board_name,
            is_online=False,
            uptime_seconds=0,
            load_avg=[0.0, 0.0, 0.0],
            ram_used_mb=0,
            ram_total_mb=0,
            disk_used_gb=0.0,
            disk_total_gb=0.0,
            kernel="",
            k8s_status={"worker": is_k8s_worker, "status": "offline"}
        )
        return

    # Batch script executed via SSH over 1 round trip
    remote_cmd = (
        "cat /proc/uptime; echo '---'; "
        "cat /proc/loadavg; echo '---'; "
        "uname -r; echo '---'; "
        "free -m; echo '---'; "
        "df -h /; echo '---'; "
    )
    if is_k8s_worker:
        remote_cmd += (
            f"kubectl --kubeconfig /etc/kubernetes/kubelet.conf get node {board_name} -o jsonpath='Ready:{{.status.conditions[?(@.type==\"Ready\")].status}}' 2>/dev/null || echo 'Unknown'; echo '---'; "
            "ip -brief addr show dev flannel.1 2>/dev/null || echo 'None'; echo '---'"
        )

    ssh_args = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3",
        "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
        f"root@{ip}", remote_cmd
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=4.0)
        output = stdout.decode("utf-8", errors="replace")
        sections = output.split("---")

        uptime_seconds = 0
        if len(sections) > 0 and sections[0].strip():
            try:
                uptime_seconds = int(float(sections[0].strip().split()[0]))
            except Exception:
                pass

        load_avg = [0.0, 0.0, 0.0]
        if len(sections) > 1 and sections[1].strip():
            try:
                parts = sections[1].strip().split()
                load_avg = [float(parts[0]), float(parts[1]), float(parts[2])]
            except Exception:
                pass

        kernel = sections[2].strip() if len(sections) > 2 else ""

        ram_total = 0
        ram_used = 0
        if len(sections) > 3 and sections[3].strip():
            for line in sections[3].splitlines():
                if line.startswith("Mem:"):
                    vals = line.split()
                    if len(vals) >= 3:
                        ram_total = int(vals[1])
                        ram_used = int(vals[2])

        disk_total = 0.0
        disk_used = 0.0
        if len(sections) > 4 and sections[4].strip():
            lines = [l for l in sections[4].splitlines() if l.strip()]
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 3:
                    # Convert to float GB
                    def parse_gb(s: str) -> float:
                        s = s.upper()
                        if "G" in s:
                            return float(s.replace("G", ""))
                        if "M" in s:
                            return float(s.replace("M", "")) / 1024.0
                        return 0.0
                    disk_total = parse_gb(parts[1])
                    disk_used = parse_gb(parts[2])

        k8s_status = {"worker": is_k8s_worker}
        if is_k8s_worker:
            k8s_node_cond = sections[5].strip() if len(sections) > 5 else "Unknown"
            flannel_info = sections[6].strip() if len(sections) > 6 else ""
            k8s_ready = "Ready:True" in k8s_node_cond
            overlay_up = "flannel.1" in flannel_info
            k8s_status.update({
                "ready": k8s_ready,
                "node_condition": k8s_node_cond,
                "overlay_active": overlay_up,
                "overlay_dev": "flannel.1",
                "flannel_ip": flannel_info.split()[2] if len(flannel_info.split()) >= 3 else ""
            })

        upsert_telemetry(
            board_id=board_name,
            is_online=True,
            uptime_seconds=uptime_seconds,
            load_avg=load_avg,
            ram_used_mb=ram_used,
            ram_total_mb=ram_total,
            disk_used_gb=disk_used,
            disk_total_gb=disk_total,
            kernel=kernel,
            k8s_status=k8s_status
        )

    except Exception as e:
        logger.debug(f"Error collecting telemetry for {board_name} ({ip}): {e}")

async def run_telemetry_loop():
    """Polls all cluster boards concurrently."""
    tasks = []
    for name, defn in BOARD_DEFINITIONS.items():
        is_k8s = defn.get("k8s_worker", False)
        tasks.append(poll_board_telemetry(name, defn["ip"], is_k8s))
    await asyncio.gather(*tasks, return_exceptions=True)
