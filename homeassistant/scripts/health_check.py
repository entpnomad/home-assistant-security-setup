#!/usr/bin/env python3
"""Health check and auto-recovery for HA Green.

Runs via cron in the Advanced SSH addon every 10 minutes.
Checks HA Core, Frigate, and Mosquitto. Escalates recovery actions:
  1. Restart individual addon if down
  2. Restart HA Core after 3 consecutive API failures
  3. Reboot host after 3 more consecutive failures (max 1/day)

Sends Discord alerts on any recovery action.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, date

STATE_FILE = "/tmp/health_check_state.json"
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
SUPERVISOR_HEADERS = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"core_failures": 0, "last_reboot_date": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def get_discord_webhook():
    """Read Discord webhook URL from secrets.yaml."""
    try:
        with open("/homeassistant/secrets.yaml") as f:
            for line in f:
                if line.startswith("discord_webhook:"):
                    url = line.split(":", 1)[1].strip().strip('"').strip("'")
                    return url
    except Exception as e:
        log(f"Could not read discord webhook: {e}")
    return None


def discord_notify(message):
    """Send a Discord notification."""
    webhook_url = get_discord_webhook()
    if not webhook_url:
        log("No Discord webhook available, skipping notification")
        return
    try:
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log("Discord notification sent")
    except Exception as e:
        log(f"Discord notification failed: {e}")


def check_ha_core():
    """Check if HA Core API is responsive."""
    if not SUPERVISOR_TOKEN:
        log("WARNING: No SUPERVISOR_TOKEN, cannot check HA Core")
        return None
    try:
        req = urllib.request.Request(
            "http://supervisor/core/api/",
            headers=SUPERVISOR_HEADERS,
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception as e:
        log(f"HA Core API check failed: {e}")
        return False


def check_frigate():
    """Check if Frigate API is responsive."""
    try:
        resp = urllib.request.urlopen(
            "http://ccab4aaf-frigate-fa:5000/api/version", timeout=10
        )
        return resp.status == 200
    except Exception as e:
        log(f"Frigate API check failed: {e}")
        return False


def check_addon_state(addon_slug):
    """Check addon state via ha CLI."""
    try:
        result = subprocess.run(
            ["ha", "addons", "info", addon_slug],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.splitlines():
            if line.strip().startswith("state:"):
                state = line.split(":", 1)[1].strip()
                return state == "started"
        return False
    except Exception as e:
        log(f"Addon state check failed for {addon_slug}: {e}")
        return False


def restart_addon(addon_slug, name):
    """Restart an addon and notify."""
    log(f"Restarting {name} ({addon_slug})...")
    try:
        result = subprocess.run(
            ["ha", "addons", "restart", addon_slug],
            capture_output=True, text=True, timeout=120,
        )
        success = result.returncode == 0
        status = "succeeded" if success else "failed"
        log(f"Restart {name}: {status}")
        discord_notify(
            f"🔧 **Health Check Recovery**\n"
            f"Restarted **{name}** — {status}\n"
            f"_{datetime.now().strftime('%Y-%m-%d %H:%M')}_"
        )
        return success
    except Exception as e:
        log(f"Failed to restart {name}: {e}")
        return False


def restart_core():
    """Restart HA Core and notify."""
    log("Restarting HA Core...")
    discord_notify(
        "⚠️ **Health Check Recovery**\n"
        "HA Core API unresponsive after 3 checks — restarting Core\n"
        f"_{datetime.now().strftime('%Y-%m-%d %H:%M')}_"
    )
    try:
        result = subprocess.run(
            ["ha", "core", "restart"],
            capture_output=True, text=True, timeout=180,
        )
        return result.returncode == 0
    except Exception as e:
        log(f"Failed to restart Core: {e}")
        return False


def reboot_host(state):
    """Reboot the host (max 1 per day)."""
    today = date.today().isoformat()
    if state.get("last_reboot_date") == today:
        log("Already rebooted today, skipping host reboot to prevent loop")
        discord_notify(
            "🚨 **Health Check Alert**\n"
            "HA Core still unresponsive after restart + previous reboot today.\n"
            "**Manual intervention needed.** Skipping reboot to prevent loop.\n"
            f"_{datetime.now().strftime('%Y-%m-%d %H:%M')}_"
        )
        return
    log("Rebooting host...")
    state["last_reboot_date"] = today
    save_state(state)
    discord_notify(
        "🚨 **Health Check Recovery**\n"
        "HA Core still unresponsive after restart — **rebooting host**\n"
        f"_{datetime.now().strftime('%Y-%m-%d %H:%M')}_"
    )
    # Small delay so Discord message sends before reboot
    time.sleep(3)
    subprocess.run(["ha", "host", "reboot"], timeout=30)


def main():
    if not SUPERVISOR_TOKEN:
        log("ERROR: SUPERVISOR_TOKEN not set, exiting")
        sys.exit(1)

    state = load_state()
    all_healthy = True

    # Check Frigate
    frigate_ok = check_frigate()
    if frigate_ok is False:
        all_healthy = False
        # Double-check via addon state before restarting
        if not check_addon_state("ccab4aaf_frigate-fa"):
            restart_addon("ccab4aaf_frigate-fa", "Frigate")
        else:
            log("Frigate API failed but addon is running, may be starting up")

    # Check Mosquitto
    mosquitto_ok = check_addon_state("core_mosquitto")
    if not mosquitto_ok:
        all_healthy = False
        restart_addon("core_mosquitto", "Mosquitto")

    # Check HA Core (escalating recovery)
    core_ok = check_ha_core()
    if core_ok is False:
        all_healthy = False
        state["core_failures"] = state.get("core_failures", 0) + 1
        log(f"Core failure count: {state['core_failures']}")

        if state["core_failures"] >= 6:
            # 6 consecutive failures (60 min) = reboot host
            reboot_host(state)
        elif state["core_failures"] >= 3:
            # 3 consecutive failures (30 min) = restart Core
            restart_core()
    elif core_ok is True:
        if state.get("core_failures", 0) > 0:
            log(f"Core recovered after {state['core_failures']} failure(s)")
        state["core_failures"] = 0

    save_state(state)

    if all_healthy:
        log("All services healthy")


if __name__ == "__main__":
    main()
