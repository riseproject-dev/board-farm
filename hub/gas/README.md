# Google Apps Script Cache Relay (`hub/gas`)

This folder contains the stateless cache relay (`Code.gs`) for hosting a public **RISE Board Farm Hub** dashboard without exposing the OSU OSL lab controller to inbound public traffic.

## Architecture

```text
[Labgrid Host: hub.py]
   ├── Every 3s:  POSTs lightweight reservation state (`hub_reservations`)
   └── Every 30s: POSTs full hardware telemetry + events (`hub_telemetry`)
          │
          ▼
[Google Apps Script (`Code.gs` + `CacheService`)]
          │
          ▼
[Public Static `index.html` (e.g. GitHub Pages)]
   └── Polls GET `<GAS_EXEC_URL>` every 3s
```

---

## Setup Instructions (5 Minutes)

### 1. Generate the Secret Token on the Labgrid Controller Host
SSH into the labgrid controller and create the shared token file under `/opt/board-farm-hub/tokens` (never committed to Git):

```bash
sudo mkdir -p /opt/board-farm-hub/tokens
sudo chown -R $USER /opt/board-farm-hub
chmod 700 /opt/board-farm-hub/tokens
openssl rand -hex 32 > /opt/board-farm-hub/tokens/gas.token
chmod 600 /opt/board-farm-hub/tokens/gas.token
cat /opt/board-farm-hub/tokens/gas.token
```

Copy the printed 64-character hex string for Step 2.

### 2. Create and Configure the Google Apps Script Project
1. Using a personal `@gmail.com` account (so external users can access the deployed web app), open [https://script.google.com](https://script.google.com) and click **New project**.
2. Paste the contents of [`Code.gs`](./Code.gs) into the editor (`Code.gs`) and press **Ctrl+S / Cmd+S**.
3. Click **Project Settings (⚙️ gear icon)** on the left sidebar:
   * Scroll down to **Script Properties** and click **Add script property**.
   * **Property**: `PUSH_TOKEN`
   * **Value**: *(paste the 64-character token from Step 1)*
   * Click **Save script properties**.

### 3. Deploy as a Public Web App
1. In the top right of the Apps Script editor, click **Deploy → New deployment**.
2. Click the gear icon next to **Select type** and choose **Web app**.
3. Set:
   * **Execute as**: `Me`
   * **Who has access**: `Anyone`
4. Click **Deploy**, authorize the script when prompted, and copy the **Web app URL** (`https://script.google.com/macros/s/.../exec`).

### 4. Configure the URL in `config.py` and `static/index.html`
1. In [`hub/app/config.py`](../app/config.py), put your Web app URL in `REMOTE_RELAYS`:
   ```python
   REMOTE_RELAYS = [
       (
           "https://script.google.com/macros/s/<YOUR_DEPLOYMENT_ID>/exec",
           "/opt/board-farm-hub/tokens/gas.token",
       ),
   ]
   ```
2. In [`hub/static/index.html`](../static/index.html), set `DEFAULT_REMOTE_API_URL` (or pass `?api=<URL>` in the browser address bar):
   ```javascript
   const DEFAULT_REMOTE_API_URL = "https://script.google.com/macros/s/<YOUR_DEPLOYMENT_ID>/exec";
   ```
3. Redeploy `hub/` to the controller with `./deploy.sh`.
