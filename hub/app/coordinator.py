import asyncio
import logging
import shutil
import re
from typing import Dict, Any, Tuple
from app.config import LG_COORDINATOR, BOARD_DEFINITIONS
from app.db import upsert_place, add_event

logger = logging.getLogger("hub.coordinator")

async def parse_place_show(place_name: str) -> Tuple[str, str, Dict[str, str]]:
    """
    Invokes `labgrid-client -x {LG_COORDINATOR} -p {place_name} show`
    Returns (status, acquired_by, tags)
    """
    cmd = ["labgrid-client", "-x", LG_COORDINATOR, "-p", place_name, "show"]
    status = "idle"
    acquired_by = None
    tags = {}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
        output = stdout.decode("utf-8", errors="replace")

        for line in output.splitlines():
            line_str = line.strip()
            if line_str.startswith("acquired:"):
                val = line_str.split(":", 1)[1].strip()
                if val and val.lower() != "none":
                    status = "acquired"
                    acquired_by = val
                else:
                    status = "idle"
            elif line_str.startswith("tags:"):
                tag_str = line_str.split(":", 1)[1].strip()
                for pair in tag_str.split(","):
                    if "=" in pair:
                        k, v = pair.strip().split("=", 1)
                        tags[k.strip()] = v.strip()

    except Exception as e:
        logger.debug(f"Failed to query place show for {place_name}: {e}")
        status = "offline"

    return status, acquired_by, tags

async def sync_coordinator_state():
    """
    Polls the Labgrid coordinator for places and synchronizes state into SQLite.
    """
    if not shutil.which("labgrid-client"):
        logger.warning("labgrid-client binary not found in PATH. Coordinator polling skipped.")
        return

    try:
        proc = await asyncio.create_subprocess_exec(
            "labgrid-client", "-x", LG_COORDINATOR, "places",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=4.0)
        output = stdout.decode("utf-8", errors="replace")
        discovered_places = set()

        for line in output.splitlines():
            place = line.strip()
            if not place or place.startswith("Usage") or "error" in place.lower():
                continue
            discovered_places.add(place)

        for place in discovered_places:
            status, acquired_by, tags = await parse_place_show(place)
            upsert_place(
                name=place,
                status=status,
                acquired_by=acquired_by,
                tags=tags,
                matches=[f"labgrid.bak.milne.osuosl.org/{place}/*"]
            )

    except Exception as e:
        logger.warning(f"Error querying coordinator at {LG_COORDINATOR}: {e}")
