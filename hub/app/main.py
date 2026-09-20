import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    HOST, PORT, LG_COORDINATOR,
    POLL_INTERVAL_SECS, COORDINATOR_POLL_INTERVAL_SECS
)
from app.db import (
    init_db, get_all_boards_aggregated, get_recent_events, add_event
)
from app.coordinator import sync_coordinator_state
from app.telemetry import run_telemetry_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("hub.main")

active_subscribers = set()

async def broadcast_event(event_type: str, data: dict):
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    for queue in list(active_subscribers):
        try:
            await queue.put(payload)
        except Exception:
            active_subscribers.discard(queue)

async def background_scheduler():
    """Runs coordinator sync and hardware telemetry polling loops."""
    logger.info("Starting background coordinator and telemetry worker...")
    coord_counter = 0
    while True:
        try:
            # 1. Poll Labgrid Coordinator every 3s
            await sync_coordinator_state()

            # 2. Poll Board Hardware Telemetry every POLL_INTERVAL_SECS
            coord_counter += COORDINATOR_POLL_INTERVAL_SECS
            if coord_counter >= POLL_INTERVAL_SECS:
                coord_counter = 0
                await run_telemetry_loop()

            # Broadcast update to connected SSE clients
            boards = get_all_boards_aggregated()
            await broadcast_event("boards_update", {"boards": boards})

        except Exception as e:
            logger.error(f"Error in background scheduler cycle: {e}")

        await asyncio.sleep(COORDINATOR_POLL_INTERVAL_SECS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Initial immediate pass
    asyncio.create_task(sync_coordinator_state())
    asyncio.create_task(run_telemetry_loop())
    task = asyncio.create_task(background_scheduler())
    yield
    task.cancel()

app = FastAPI(title="RISE Board Farm Hub", version="1.0.0", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/v1/health")
async def get_health():
    boards = get_all_boards_aggregated()
    online_count = sum(1 for b in boards if b.get("is_online"))
    return {
        "status": "healthy",
        "coordinator": LG_COORDINATOR,
        "total_boards": len(boards),
        "online_boards": online_count,
    }

@app.get("/api/v1/boards")
async def get_boards():
    return get_all_boards_aggregated()

@app.get("/api/v1/events")
async def get_events():
    return get_recent_events(30)

@app.post("/api/v1/refresh")
async def trigger_refresh():
    await sync_coordinator_state()
    await run_telemetry_loop()
    boards = get_all_boards_aggregated()
    await broadcast_event("boards_update", {"boards": boards})
    return {"status": "refreshed", "boards": len(boards)}

@app.get("/api/v1/stream")
async def sse_stream():
    queue = asyncio.Queue()
    active_subscribers.add(queue)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Send initial snapshot immediately
            initial_data = get_all_boards_aggregated()
            yield f"event: boards_update\ndata: {json.dumps({'boards': initial_data})}\n\n"
            while True:
                msg = await queue.get()
                yield msg
        except asyncio.CancelledError:
            active_subscribers.discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.get("/metrics")
async def prometheus_metrics():
    boards = get_all_boards_aggregated()
    lines = [
        "# HELP board_online Online SSH reachability (1 = online, 0 = offline)",
        "# TYPE board_online gauge",
    ]
    for b in boards:
        val = 1 if b.get("is_online") else 0
        lines.append(f'board_online{{board="{b["name"]}",ip="{b["ip_address"]}"}} {val}')

    lines.extend([
        "# HELP board_acquired Labgrid place reservation (1 = acquired, 0 = idle)",
        "# TYPE board_acquired gauge",
    ])
    for b in boards:
        val = 1 if b.get("status") == "acquired" else 0
        lines.append(f'board_acquired{{board="{b["name"]}"}} {val}')

    lines.extend([
        "# HELP board_load_1m 1-minute CPU load average",
        "# TYPE board_load_1m gauge",
    ])
    for b in boards:
        load = b.get("load_1m") or 0.0
        lines.append(f'board_load_1m{{board="{b["name"]}"}} {load:.2f}')

    lines.extend([
        "# HELP board_ram_used_mb Used RAM in Megabytes",
        "# TYPE board_ram_used_mb gauge",
    ])
    for b in boards:
        ram = b.get("ram_used_mb") or 0
        lines.append(f'board_ram_used_mb{{board="{b["name"]}"}} {ram}')

    lines.extend([
        "# HELP board_lifetime_boot_cycles Cumulative detected boot cycles",
        "# TYPE board_lifetime_boot_cycles counter",
    ])
    for b in boards:
        cycles = b.get("lifetime_uboot_cycles") or 0
        lines.append(f'board_lifetime_boot_cycles{{board="{b["name"]}"}} {cycles}')

    lines.extend([
        "# HELP k8s_node_ready Kubernetes worker node ready status (1 = ready, 0 = not ready)",
        "# TYPE k8s_node_ready gauge",
    ])
    for b in boards:
        if b.get("is_k8s_worker"):
            k8s = b.get("k8s_status", {})
            val = 1 if k8s.get("ready") else 0
            lines.append(f'k8s_node_ready{{board="{b["name"]}"}} {val}')

    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
