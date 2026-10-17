import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from app.config import LG_COORDINATOR, REMOTE_RELAYS

logger = logging.getLogger("hub.relay")


class _PostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows 301/302/303 redirects (used by Google Apps Script after doPost) with GET."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code in (301, 302, 303, 307, 308):
            return urllib.request.Request(
                newurl,
                headers={"Accept": "application/json, text/plain, */*"},
                method="GET",
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_PostRedirectHandler())
_IN_FLIGHT_TYPES = set()

# State tracking to avoid log spam on the 3-second loop
_LAST_ACTIVE_URLS: Optional[Tuple[str, ...]] = None
_FAILURE_COUNTS: Dict[str, int] = {}
_LAST_WARN_TIME: Dict[str, float] = {}
_HAS_LOGGED_SUCCESS: Dict[str, bool] = {}
_WARN_COOLDOWN_SECS = 300.0  # Log repeated failures at most once every 5 minutes


def _read_token_file(token_file_path: str) -> Optional[str]:
    """Reads the secret token from a local file on the labgrid host."""
    expanded = os.path.expanduser(token_file_path)
    if not os.path.isfile(expanded):
        return None
    try:
        with open(expanded, "r", encoding="utf-8") as f:
            token = f.read().strip()
        return token if token else None
    except Exception as e:
        logger.debug(f"Failed to read token file {expanded}: {e}")
        return None


def _get_active_relays() -> List[Tuple[str, str]]:
    """Returns configured (url, secret_token) pairs that have a valid URL and local token file."""
    global _LAST_ACTIVE_URLS
    active: List[Tuple[str, str]] = []
    for url, token_file in REMOTE_RELAYS:
        if not url or "REPLACE_WITH_DEPLOYMENT_ID" in url:
            continue
        token = _read_token_file(token_file)
        if not token:
            continue
        active.append((url, token))

    active_urls = tuple(url for url, _ in active)
    if active_urls != _LAST_ACTIVE_URLS:
        _LAST_ACTIVE_URLS = active_urls
        if active_urls:
            logger.info(f"Remote relay push enabled for {len(active_urls)} endpoint(s): {list(active_urls)}")
        else:
            logger.info("Remote relay push inactive (no configured relay with both a valid URL and token file).")

    return active


def _record_success(url: str, push_type: str):
    """Logs initial connection success and recovery after failures without spamming every 3s."""
    prev_failures = _FAILURE_COUNTS.pop(url, 0)
    _LAST_WARN_TIME.pop(url, None)
    if prev_failures > 0:
        logger.info(f"Remote relay {url} recovered after {prev_failures} failed attempt(s) (type={push_type}).")
        _HAS_LOGGED_SUCCESS[url] = True
    elif not _HAS_LOGGED_SUCCESS.get(url):
        logger.info(f"Remote relay {url} connected: first '{push_type}' push succeeded.")
        _HAS_LOGGED_SUCCESS[url] = True


def _record_failure(url: str, push_type: str, reason: str):
    """Logs the first failure immediately, then rate-limits repeated warnings to once per 5 minutes."""
    count = _FAILURE_COUNTS.get(url, 0) + 1
    _FAILURE_COUNTS[url] = count
    now = time.monotonic()
    last_warn = _LAST_WARN_TIME.get(url, 0.0)

    if count == 1:
        _LAST_WARN_TIME[url] = now
        logger.warning(f"Remote relay push to {url} failed (type={push_type}): {reason}")
    elif (now - last_warn) >= _WARN_COOLDOWN_SECS:
        _LAST_WARN_TIME[url] = now
        logger.warning(
            f"Remote relay push to {url} still failing ({count} consecutive failures, type={push_type}): {reason}"
        )


def _post_json_sync(url: str, payload: Dict[str, Any], timeout: float = 8.0) -> bool:
    """Sends a JSON POST request synchronously (called via asyncio.to_thread)."""
    push_type = payload.get("type", "unknown")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            resp_text = resp.read().decode("utf-8", errors="replace").strip()
            if resp.status >= 400:
                _record_failure(url, push_type, f"HTTP {resp.status}: {resp_text[:160]}")
                return False

            # Google Apps Script returns HTTP 200 with a JSON status field
            if resp_text.startswith("{"):
                try:
                    resp_json = json.loads(resp_text)
                    status = resp_json.get("status")
                    if status and status != "ok":
                        msg = resp_json.get("message", resp_text[:160])
                        _record_failure(url, push_type, f"Relay returned status='{status}': {msg}")
                        return False
                except Exception:
                    pass

            _record_success(url, push_type)
            return True
    except urllib.error.HTTPError as e:
        _record_failure(url, push_type, f"HTTPError {e.code} {e.reason}")
        return False
    except Exception as e:
        _record_failure(url, push_type, str(e))
        return False


async def _push_payload_to_all(payload_base: Dict[str, Any]):
    """Fans out payload_base to all active (url, token_file) relays concurrently."""
    relays = _get_active_relays()
    if not relays:
        return

    push_type = payload_base.get("type", "unknown")
    if push_type in _IN_FLIGHT_TYPES:
        logger.debug(f"Skipping {push_type} push: previous push still in flight.")
        return

    _IN_FLIGHT_TYPES.add(push_type)
    try:
        tasks = []
        for url, token in relays:
            payload = dict(payload_base)
            payload["token"] = token
            tasks.append(asyncio.to_thread(_post_json_sync, url, payload))

        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        _IN_FLIGHT_TYPES.discard(push_type)


async def push_reservations(boards: List[Dict[str, Any]]):
    """
    Called every 3 seconds: pushes lightweight coordinator reservation status
    for all boards (~30 bytes/board).
    """
    reservations = {
        b["name"]: {
            "status": b.get("status", "offline"),
            "acquired_by": b.get("acquired_by"),
            "last_changed_at": b.get("last_changed_at"),
        }
        for b in boards
    }
    payload = {
        "type": "reservations",
        "coordinator": LG_COORDINATOR,
        "updated_at": int(time.time() * 1000),
        "reservations": reservations,
    }
    await _push_payload_to_all(payload)


async def push_telemetry(boards: List[Dict[str, Any]], events: List[Dict[str, Any]]):
    """
    Called every 30 seconds: pushes complete hardware telemetry and recent
    activity events for all boards (~300 bytes/board).
    """
    payload = {
        "type": "telemetry",
        "coordinator": LG_COORDINATOR,
        "updated_at": int(time.time() * 1000),
        "boards": boards,
        "events": events,
    }
    await _push_payload_to_all(payload)
