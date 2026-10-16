/**
 * RISE Board Farm Hub — Google Apps Script Cache Relay (Code.gs)
 *
 * Receives 3-second reservation updates (`type: "reservations"`) and
 * 30-second full telemetry snapshots (`type: "telemetry"`) from the OSU OSL
 * labgrid controller (`hub.py`) via `doPost(e)`, stores them in
 * `CacheService.getScriptCache()`, and serves the merged JSON state to the
 * public HTML dashboard via `doGet(e)`.
 *
 * Secret configuration (never stored in source code):
 *   In Google Apps Script -> Project Settings (gear icon) -> Script Properties:
 *   Add property `PUSH_TOKEN` = <contents of /opt/board-farm-hub/tokens/gas.token>
 */

const CACHE_TTL_SECONDS = 21600; // 6 hours (maximum allowed by CacheService)
const KEY_RESERVATIONS = "hub_reservations";
const KEY_TELEMETRY = "hub_telemetry";
const KEY_EXPECTED_TOKEN = "__expected_push_token__";

/**
 * Reads the expected push token from CacheService (backed by Script Properties).
 */
function getExpectedToken_(cache) {
  let token = cache.get(KEY_EXPECTED_TOKEN);
  if (!token) {
    token = PropertiesService.getScriptProperties().getProperty("PUSH_TOKEN");
    if (token) {
      cache.put(KEY_EXPECTED_TOKEN, token, CACHE_TTL_SECONDS);
    }
  }
  return token;
}

/**
 * Constant-time string comparison to prevent timing side-channels.
 */
function tokensMatch_(provided, expected) {
  if (!provided || !expected || typeof provided !== "string" || typeof expected !== "string") {
    return false;
  }
  if (provided.length !== expected.length) {
    return false;
  }
  let diff = 0;
  for (let i = 0; i < provided.length; i++) {
    diff |= provided.charCodeAt(i) ^ expected.charCodeAt(i);
  }
  return diff === 0;
}

/**
 * Formats a JSON HTTP response with CORS support via ContentService.
 */
function jsonResponse_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Handles POST requests from the labgrid controller (`hub/app/relay.py`):
 * - Every 3s:  { type: "reservations", token, coordinator, updated_at, reservations }
 * - Every 30s: { type: "telemetry",    token, coordinator, updated_at, boards, events }
 */
function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonResponse_({ status: "error", message: "Empty POST body" });
    }

    const payload = JSON.parse(e.postData.contents);
    const cache = CacheService.getScriptCache();
    const expectedToken = getExpectedToken_(cache);

    if (!tokensMatch_(payload.token, expectedToken)) {
      return jsonResponse_({ status: "unauthorized", message: "Invalid push token" });
    }

    const now = Date.now();

    if (payload.type === "reservations" && payload.reservations) {
      cache.put(
        KEY_RESERVATIONS,
        JSON.stringify({
          coordinator: payload.coordinator || "",
          updated_at: payload.updated_at || now,
          reservations: payload.reservations,
        }),
        CACHE_TTL_SECONDS
      );
      return jsonResponse_({ status: "ok", updated: "reservations" });
    }

    if (payload.type === "telemetry" && Array.isArray(payload.boards)) {
      cache.put(
        KEY_TELEMETRY,
        JSON.stringify({
          coordinator: payload.coordinator || "",
          updated_at: payload.updated_at || now,
          boards: payload.boards,
          events: Array.isArray(payload.events) ? payload.events : [],
        }),
        CACHE_TTL_SECONDS
      );
      return jsonResponse_({ status: "ok", updated: "telemetry", boards: payload.boards.length });
    }

    return jsonResponse_({ status: "error", message: "Unknown payload type" });
  } catch (err) {
    return jsonResponse_({ status: "error", message: String(err) });
  }
}

/**
 * Handles GET requests from the public `index.html` dashboard:
 * Fetches both `hub_telemetry` (30s) and `hub_reservations` (3s) from
 * CacheService in one call and overlays the latest 3s reservation state
 * onto each board.
 */
function doGet(e) {
  try {
    const cache = CacheService.getScriptCache();
    const raw = cache.getAll([KEY_TELEMETRY, KEY_RESERVATIONS]);

    const telData = raw[KEY_TELEMETRY] ? JSON.parse(raw[KEY_TELEMETRY]) : null;
    const resData = raw[KEY_RESERVATIONS] ? JSON.parse(raw[KEY_RESERVATIONS]) : null;

    const reservationsMap = (resData && resData.reservations) ? resData.reservations : {};
    let boards = (telData && Array.isArray(telData.boards)) ? telData.boards : [];

    // If only 3s reservations have arrived before the first 30s telemetry push,
    // synthesize minimal board entries so the dashboard still renders immediately.
    if (boards.length === 0 && Object.keys(reservationsMap).length > 0) {
      boards = Object.keys(reservationsMap).sort().map(function(name) {
        const r = reservationsMap[name];
        return {
          name: name,
          short_name: name,
          status: r.status || "idle",
          acquired_by: r.acquired_by || null,
          last_changed_at: r.last_changed_at || null,
          is_online: r.status !== "offline",
        };
      });
    } else {
      // Overlay the freshest 3-second reservation status onto the 30-second telemetry objects
      boards = boards.map(function(board) {
        const latestRes = reservationsMap[board.name];
        if (latestRes) {
          board.status = latestRes.status || board.status;
          board.acquired_by = latestRes.acquired_by !== undefined ? latestRes.acquired_by : board.acquired_by;
          board.last_changed_at = latestRes.last_changed_at || board.last_changed_at;
        }
        return board;
      });
    }

    return jsonResponse_({
      status: "ok",
      coordinator: (resData && resData.coordinator) || (telData && telData.coordinator) || "127.0.0.1:20408",
      reservations_updated_at: resData ? resData.updated_at : null,
      telemetry_updated_at: telData ? telData.updated_at : null,
      boards: boards,
      events: (telData && Array.isArray(telData.events)) ? telData.events : [],
    });
  } catch (err) {
    return jsonResponse_({ status: "error", message: String(err), boards: [], events: [] });
  }
}
