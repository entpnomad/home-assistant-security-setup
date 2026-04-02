#!/usr/bin/env python3
"""Enforce privacy mode on Tapo cameras.
Only runs if the corresponding input_boolean is on in HA.
Runs via cron in the Advanced SSH addon every 5 minutes.
"""
import os
import requests
from pytapo import Tapo

CAMERAS = [
    {"name": "camera_1", "ip": "<CAMERA_1_IP>", "toggle": "input_boolean.camera_1_privacy_enforcer"},
    {"name": "camera_2", "ip": "<CAMERA_2_IP>", "toggle": "input_boolean.camera_2_privacy_enforcer"},
]
USERNAME = "admin"
PASSWORD = "<TAPO_CLOUD_PASS>"

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

def check_toggle(entity_id):
    if not SUPERVISOR_TOKEN:
        return True
    try:
        r = requests.get(
            f"http://supervisor/core/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
            timeout=5,
        )
        if r.ok and r.json().get("state") != "on":
            return False
    except Exception as e:
        print(f"Warning: could not check {entity_id}: {e}, proceeding anyway")
    return True

for cam in CAMERAS:
    if not check_toggle(cam["toggle"]):
        print(f"{cam['name']}: privacy enforcer disabled, skipping")
        continue
    try:
        t = Tapo(cam["ip"], USERNAME, PASSWORD)
        status = t.getPrivacyMode()
        if status.get("enabled") != "on":
            t.setPrivacyMode(True)
            print(f"{cam['name']}: privacy mode was off - enabled now")
        else:
            print(f"{cam['name']}: privacy mode already on")
    except Exception as e:
        print(f"{cam['name']}: error - {e}")
