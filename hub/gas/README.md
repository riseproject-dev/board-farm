# Public Dashboard & Google Apps Script Cache Relay (`hub/gas`)

This guide walks through setting up and maintaining the public **RISE Board Farm Hub** web dashboard (`https://riseproject-dev.github.io/board-farm/hub/static/`) backed by a stateless **Google Apps Script (`CacheService`)** relay.

---

## 1. Architecture & Security Model

```text
[OSU OSL Labgrid Controller: /opt/board-farm-hub]
   ├── Every 3s:  POSTs lightweight reservation state (`hub_reservations`, ~600 B)
   └── Every 30s: POSTs full hardware telemetry + events (`hub_telemetry`, ~4.4 KB)
          │
          │  (HTTPS POST authenticated via secret PUSH_TOKEN)
          ▼
[Google Apps Script Web App (`hub/gas/Code.gs` + `CacheService`)]
          │
          │  (Public HTTPS GET JSON)
          ▼
[GitHub Pages Dashboard (`hub/static/index.html`)]
   └── Polls GET `<GAS_EXEC_URL>` every 3s and renders the Vue 3 UI
```

### Why This Is Safe to Publish in a Public Repository
* **No inbound ports on the lab network**: The OSU OSL controller (`10.6.4.11`) only makes **outbound** HTTPS `POST` requests.
* **No secrets in Git**:
  * The secret `PUSH_TOKEN` is **never** stored in `Code.gs` or anywhere in the Git repository.
  * On the labgrid controller, the token lives only in `/opt/board-farm-hub/tokens/gas.token` (`chmod 640`, group `rise`, excluded by `.gitignore` and `deploy.sh`).
  * On Google Apps Script, the matching token lives only in **Project Settings → Script Properties** (`PUSH_TOKEN`).
* **Public read-only URL**: The Google Apps Script `/exec` URL in `config.py` and `static/index.html` is safe to commit publicly because unauthenticated callers can only `GET` the public dashboard status; any `POST` without the valid `PUSH_TOKEN` is rejected (`{"status": "unauthorized"}`).

---

## 2. Step-by-Step Setup Guide

### Step 1: Generate a Secret `PUSH_TOKEN`
Generate a random 64-character hex string on your workstation (do **not** commit this string to Git):

```bash
openssl rand -hex 32
```

Keep this 64-character string handy—you will paste the exact same value into **Google Apps Script** (Step 2) and onto the **Labgrid Controller** (Step 3).

---

### Step 2: Create and Deploy the Google Apps Script Relay

> **Important — Use a Personal `@gmail.com` Account:**
> Do **not** create the script under a corporate `@google.com` Workspace account. Corporate accounts restrict web app sharing to *"Anyone within google.com"* and place `/a/macros/google.com/` behind a corporate SSO login wall, which blocks unauthenticated `POST` requests from the OSU OSL controller and blocks external users from viewing the dashboard.

1. **Create the Project**:
   * Sign into [https://script.google.com](https://script.google.com) with a personal `@gmail.com` account.
   * Click **+ New project** (top-left) and rename the project to **`RISE Board Farm Relay`**.
2. **Copy `Code.gs`**:
   * Delete the default `function myFunction() {}` placeholder in the `Code.gs` editor.
   * Copy the **entire contents** of [`hub/gas/Code.gs`](./Code.gs) and paste it into the editor.
   * Press **`Ctrl + S`** (or click the **Save project** icon).
   * *(Note: You do not need to manually create any database or cache tables; `CacheService.getScriptCache()` creates the `hub_reservations` and `hub_telemetry` keys in memory automatically.)*
3. **Configure the Secret `PUSH_TOKEN` Property**:
   * On the left sidebar of the Apps Script editor, click **Project Settings (⚙️ gear icon)**.
   * Scroll to the bottom under **Script Properties** and click **Add script property**:
     * **Property**: `PUSH_TOKEN`
     * **Value**: *(paste the 64-character hex string from Step 1)*
   * Click **Save script properties**.
4. **Deploy as a Public Web App**:
   * Click the blue **Deploy** button (top-right) → **New deployment**.
   * Click the **⚙️ gear icon** next to *"Select type"* and choose **Web app**.
   * Configure:
     * **Description**: `v1`
     * **Execute as**: **`Me`**
     * **Who has access**: **`Anyone`** *(must be `Anyone` so the labgrid server and public browsers can access it without Google sign-in)*
   * Click **Deploy**.
   * When prompted to authorize access: click **Authorize access** → select your `@gmail.com` account → click **Advanced** → click **Go to RISE Board Farm Relay (unsafe)** → click **Allow**.
5. **Copy & Verify the Web App URL**:
   * Copy the generated **Web app URL**, which looks like:
     ```text
     https://script.google.com/macros/s/AKfycb.../exec
     ```
     *(Verify it contains `/macros/s/` and **not** `/a/macros/google.com/`.)*
   * Open that `/exec` URL in your browser to verify it returns:
     ```json
     {"status":"ok","coordinator":"127.0.0.1:20408","reservations_updated_at":null,"telemetry_updated_at":null,"boards":[],"events":[]}
     ```

> **Updating `Code.gs` in the Future:**
> In Google Apps Script, saving edits in `Code.gs` does not automatically update the live `/exec` URL. Whenever you edit `Code.gs`, click **Deploy → Manage deployments → ✏️ (Edit) → Version: `New version` → Deploy**.

---

### Step 3: Save `PUSH_TOKEN` on the Labgrid Controller (`10.6.4.11`)

1. Connect to the OSU OSL labgrid controller via SSH (see [`experiment/osu_osl/README.md`](../../experiment/osu_osl/README.md) for VPN/SSH setup):
   ```bash
   ./experiment/osu_osl/ssh-osu.sh labgrid
   ```
2. On the labgrid controller (`10.6.4.11`), save your 64-character `PUSH_TOKEN` from Step 1 into `/opt/board-farm-hub/tokens/gas.token` with `rise` group read permissions:
   ```bash
   sudo mkdir -p /opt/board-farm-hub/tokens
   echo '<YOUR_64_CHAR_PUSH_TOKEN>' | sudo tee /opt/board-farm-hub/tokens/gas.token > /dev/null
   sudo chgrp -R rise /opt/board-farm-hub/tokens
   sudo chmod 750 /opt/board-farm-hub/tokens
   sudo chmod 640 /opt/board-farm-hub/tokens/gas.token
   exit
   ```

---

### Step 4: Configure the Relay URL & Deploy `hub/` to the Controller

1. **Update [`hub/app/config.py`](../app/config.py)**:
   Ensure your `/exec` URL is listed in `REMOTE_RELAYS` alongside the token file path on the controller:
   ```python
   REMOTE_RELAYS: List[Tuple[str, str]] = [
       (
           os.environ.get(
               "GAS_RELAY_URL",
               "https://script.google.com/macros/s/<YOUR_DEPLOYMENT_ID>/exec",
           ),
           os.environ.get("GAS_TOKEN_FILE", "/opt/board-farm-hub/tokens/gas.token"),
       ),
   ]
   ```
   *(Multiple relays are supported: you can add additional `(url, token_file)` tuples to `REMOTE_RELAYS` to fan out pushes to multiple endpoints simultaneously.)*

2. **Update [`hub/static/index.html`](../static/index.html)**:
   Set `DEFAULT_REMOTE_API_URL` near the top of the `<script>` block to the same `/exec` URL:
   ```javascript
   const DEFAULT_REMOTE_API_URL = "https://script.google.com/macros/s/<YOUR_DEPLOYMENT_ID>/exec";
   ```

3. **Deploy to `/opt/board-farm-hub` on the Labgrid Controller**:
   From your workstation:
   ```bash
   cd hub
   ./deploy.sh
   ```
   `deploy.sh` syncs the updated code into `/opt/board-farm-hub` (preserving `/opt/board-farm-hub/tokens/`, `venv/`, and `hub.db`) and restarts `board-farm-hub.service`.

4. **Verify Relay Push Logs on the Controller**:
   ```bash
   ../experiment/osu_osl/ssh-osu.sh labgrid "sudo journalctl -u board-farm-hub.service -n 25 --no-pager"
   ```
   You should see:
   ```text
   INFO hub.relay: Remote relay push enabled for 1 endpoint(s): ['https://script.google.com/macros/s/.../exec']
   INFO hub.relay: Remote relay https://script.google.com/macros/s/.../exec connected: first 'reservations' push succeeded.
   ```
   Refreshing your `/exec` URL in a browser will now show the live JSON for all boards.

---

### Step 5: Publish the Visual Dashboard via GitHub Pages

1. Commit and push your updated `hub/` files to the `main` branch on GitHub.
2. In the GitHub repository, navigate to **Settings → Pages** (`https://github.com/riseproject-dev/board-farm/settings/pages`).
3. Under **Build and deployment**:
   * **Source**: `Deploy from a branch`
   * **Branch**: change `None` to **`main`**, folder **`/ (root)`**, and click **Save**.
4. After ~60 seconds, the live public dashboard is served at:
   **`https://riseproject-dev.github.io/board-farm/hub/static/`**

*(You can also override which relay URL the dashboard queries at any time via the `?api=` query parameter: `https://riseproject-dev.github.io/board-farm/hub/static/?api=<CUSTOM_RELAY_URL>`.)*
