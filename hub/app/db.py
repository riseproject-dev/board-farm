import sqlite3
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.config import DB_PATH, BOARD_DEFINITIONS

def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS places (
            name TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'offline',
            acquired_by TEXT,
            reservation_token TEXT,
            tags TEXT NOT NULL DEFAULT '{}',
            matches TEXT NOT NULL DEFAULT '[]',
            last_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS board_telemetry (
            board_id TEXT PRIMARY KEY REFERENCES places(name),
            ip_address TEXT NOT NULL,
            serial_port TEXT NOT NULL,
            is_online BOOLEAN NOT NULL DEFAULT 0,
            uptime_seconds INTEGER DEFAULT 0,
            load_1m REAL DEFAULT 0.0,
            load_5m REAL DEFAULT 0.0,
            load_15m REAL DEFAULT 0.0,
            ram_used_mb INTEGER DEFAULT 0,
            ram_total_mb INTEGER DEFAULT 0,
            disk_used_gb REAL DEFAULT 0.0,
            disk_total_gb REAL DEFAULT 0.0,
            kernel_version TEXT,
            k8s_status TEXT DEFAULT '{}',
            polled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS cycle_counters (
            board_id TEXT PRIMARY KEY REFERENCES places(name),
            session_uboot_cycles INTEGER NOT NULL DEFAULT 0,
            lifetime_uboot_cycles INTEGER NOT NULL DEFAULT 0,
            session_fastboot_flashes INTEGER NOT NULL DEFAULT 0,
            lifetime_fastboot_flashes INTEGER NOT NULL DEFAULT 0,
            last_boot_time TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS events_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id TEXT,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Seed initial entries
        for name, defn in BOARD_DEFINITIONS.items():
            conn.execute("""
            INSERT OR IGNORE INTO places (name, status, tags)
            VALUES (?, 'idle', ?)
            """, (name, json.dumps({"arch": defn["arch"], "soc": defn["soc"]})))

            conn.execute("""
            INSERT OR IGNORE INTO board_telemetry (board_id, ip_address, serial_port)
            VALUES (?, ?, ?)
            """, (name, defn["ip"], defn["serial_port"]))

            conn.execute("""
            INSERT OR IGNORE INTO cycle_counters (board_id, session_uboot_cycles, lifetime_uboot_cycles)
            VALUES (?, 0, 1)
            """, (name,))
        conn.commit()

def upsert_place(name: str, status: str, acquired_by: Optional[str], tags: Dict[str, Any], matches: List[str]):
    with get_db_connection() as conn:
        conn.execute("""
        INSERT INTO places (name, status, acquired_by, tags, matches, last_changed_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(name) DO UPDATE SET
            status = excluded.status,
            acquired_by = excluded.acquired_by,
            tags = excluded.tags,
            matches = excluded.matches,
            last_changed_at = CURRENT_TIMESTAMP
        """, (name, status, acquired_by, json.dumps(tags), json.dumps(matches)))
        conn.commit()

def upsert_telemetry(board_id: str, is_online: bool, uptime_seconds: int, load_avg: List[float],
                     ram_used_mb: int, ram_total_mb: int, disk_used_gb: float, disk_total_gb: float,
                     kernel: str, k8s_status: Dict[str, Any]):
    with get_db_connection() as conn:
        # Check if uptime dropped, which indicates a reboot cycle!
        row = conn.execute("SELECT uptime_seconds FROM board_telemetry WHERE board_id = ?", (board_id,)).fetchone()
        if row and row["uptime_seconds"] > 0 and uptime_seconds < row["uptime_seconds"] and is_online:
            conn.execute("""
            UPDATE cycle_counters SET
                session_uboot_cycles = session_uboot_cycles + 1,
                lifetime_uboot_cycles = lifetime_uboot_cycles + 1,
                last_boot_time = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE board_id = ?
            """, (board_id,))
            conn.execute("""
            INSERT INTO events_log (board_id, event_type, message)
            VALUES (?, 'reboot', 'Detected board reboot event (uptime reset)')
            """, (board_id,))

        load_1m = load_avg[0] if len(load_avg) > 0 else 0.0
        load_5m = load_avg[1] if len(load_avg) > 1 else 0.0
        load_15m = load_avg[2] if len(load_avg) > 2 else 0.0

        conn.execute("""
        UPDATE board_telemetry SET
            is_online = ?,
            uptime_seconds = ?,
            load_1m = ?,
            load_5m = ?,
            load_15m = ?,
            ram_used_mb = ?,
            ram_total_mb = ?,
            disk_used_gb = ?,
            disk_total_gb = ?,
            kernel_version = ?,
            k8s_status = ?,
            polled_at = CURRENT_TIMESTAMP
        WHERE board_id = ?
        """, (is_online, uptime_seconds, load_1m, load_5m, load_15m,
              ram_used_mb, ram_total_mb, disk_used_gb, disk_total_gb,
              kernel, json.dumps(k8s_status), board_id))
        conn.commit()

def add_event(board_id: Optional[str], event_type: str, message: str):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO events_log (board_id, event_type, message) VALUES (?, ?, ?)",
                     (board_id, event_type, message))
        conn.commit()

def get_all_boards_aggregated() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.execute("""
        SELECT 
            p.name, p.status, p.acquired_by, p.reservation_token, p.tags, p.matches, p.last_changed_at,
            t.ip_address, t.serial_port, t.is_online, t.uptime_seconds,
            t.load_1m, t.load_5m, t.load_15m,
            t.ram_used_mb, t.ram_total_mb, t.disk_used_gb, t.disk_total_gb,
            t.kernel_version, t.k8s_status, t.polled_at,
            c.session_uboot_cycles, c.lifetime_uboot_cycles,
            c.session_fastboot_flashes, c.lifetime_fastboot_flashes, c.last_boot_time
        FROM places p
        LEFT JOIN board_telemetry t ON p.name = t.board_id
        LEFT JOIN cycle_counters c ON p.name = c.board_id
        ORDER BY p.name ASC
        """)
        results = []
        for r in cursor.fetchall():
            item = dict(r)
            item["tags"] = json.loads(item["tags"]) if item["tags"] else {}
            item["matches"] = json.loads(item["matches"]) if item["matches"] else []
            item["k8s_status"] = json.loads(item["k8s_status"]) if item["k8s_status"] else {}
            # Merge definition metadata
            defn = BOARD_DEFINITIONS.get(item["name"], {})
            item["short_name"] = defn.get("short_name", item["name"])
            item["mac"] = defn.get("mac", "")
            item["soc"] = defn.get("soc", "RISC-V 64-bit")
            item["arch"] = defn.get("arch", "riscv64")
            item["is_k8s_worker"] = defn.get("k8s_worker", False)
            results.append(item)
        return results

def get_recent_events(limit: int = 25) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM events_log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]
