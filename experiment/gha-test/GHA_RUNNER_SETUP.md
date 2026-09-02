# GitHub Actions Self-Hosted Runner Setup Guide

This document explains how to register and test the containerized **GitHub Actions Self-Hosted Runner (`gha-runner`)** with an online GitHub repository fork.

---

## Architecture Overview

```text
  GitHub.com Repository ──(HTTPS Poll/Job Dispatch)──> gha-runner Docker Container
                                                                │
                                                                v
                                                       Pytest-Labgrid Test Client
                                                                │
                                                  ┌─────────────┴─────────────┐
                                                  v                           v
                                        labgrid-coordinator          labgrid-exporter
                                          (Port 20408)             (PDU & Serial TCP)
```

---

## Step-by-Step Setup Guide

### Step 1: Fork or Create a GitHub Repository
1. Push or fork the repository containing `experiment/gha-test` and `.github/workflows/kernel_test.yml` to your GitHub account (e.g. `https://github.com/<your-username>/board-farm`).

---

### Step 2: Generate a Self-Hosted Runner Registration Token
1. Open your repository on GitHub in your browser.
2. Navigate to: **Settings ➔ Actions ➔ Runners**.
3. Click **New self-hosted runner**.
4. Select **Linux** as the Runner OS.
5. In the snippet provided under *Configure*, find the `--token` flag and copy the token string:
   ```bash
   ./config.sh --url https://github.com/your-username/board-farm --token A1B2C3D4E5EXAMPLETOKEN
   ```

---

### Step 3: Launch the 4-Container Stack with Your Credentials

Run `docker compose` with your `GITHUB_REPOSITORY` and `RUNNER_TOKEN`:

```bash
cd experiment/gha-test

GITHUB_REPOSITORY="your-username/board-farm" \
RUNNER_TOKEN="A1B2C3D4E5EXAMPLETOKEN" \
sudo -E docker compose up -d --build
```

#### What happens automatically:
1. `lab-gateway`, `labgrid-coordinator`, and `labgrid-exporter` start up.
2. `gha-runner` executes [`entrypoint.sh`](file:///usr/local/google/home/puneetha/RISE/git-repo/board-farm/experiment/gha-test/entrypoint.sh), registers itself with your GitHub repository, and enters listening mode (`./run.sh`).
3. You will see the new runner status as **Idle / Online** under **Settings ➔ Actions ➔ Runners** on GitHub.

---

### Step 4: Trigger the Workflow Live on GitHub

1. Go to your GitHub repository ➔ **Actions** tab.
2. Click **Phase 1 Labgrid Pilot Kernel Test** in the left sidebar.
3. Click **Run workflow** ➔ Select target `qemu-board-01` ➔ Click **Run workflow**.

---

### Step 5: Teardown

To stop the containers and unregister the runner when finished:

```bash
sudo docker compose down
```
