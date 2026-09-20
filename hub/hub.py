#!/usr/bin/env python3
"""
RISE Board Farm Hub CLI & Entrypoint
"""
import sys
import argparse
import asyncio
import uvicorn
from app.config import HOST, PORT
from app.db import init_db, get_all_boards_aggregated
from app.coordinator import sync_coordinator_state
from app.telemetry import run_telemetry_loop

async def run_poll():
    print("Initializing SQLite database...")
    init_db()
    print("Syncing with Labgrid coordinator...")
    await sync_coordinator_state()
    print("Polling board hardware telemetry...")
    await run_telemetry_loop()
    boards = get_all_boards_aggregated()
    print(f"\n--- Aggregated Cluster State ({len(boards)} boards) ---")
    for b in boards:
        print(f"[{b['name']}] Status: {b['status']} | Online: {b['is_online']} | IP: {b['ip_address']} | Uptime: {b['uptime_seconds']}s | Load: {b['load_1m']} | K8s: {b.get('is_k8s_worker')}")

def main():
    parser = argparse.ArgumentParser(description="RISE Board Farm Hub")
    subparsers = parser.add_subparsers(dest="command")

    # Run command
    run_parser = subparsers.add_parser("run", help="Start the FastAPI web server")
    run_parser.add_argument("--host", default=HOST, help="Bind host (default: %(default)s)")
    run_parser.add_argument("--port", type=int, default=PORT, help="Bind port (default: %(default)s)")

    # Poll command
    subparsers.add_parser("poll", help="Run a single polling cycle and print output")

    args = parser.parse_args()

    if args.command == "poll":
        asyncio.run(run_poll())
    else:
        host = getattr(args, "host", HOST)
        port = getattr(args, "port", PORT)
        print(f"Starting RISE Board Farm Hub on http://{host}:{port}")
        uvicorn.run("app.main:app", host=host, port=port, reload=False, workers=1)

if __name__ == "__main__":
    main()
