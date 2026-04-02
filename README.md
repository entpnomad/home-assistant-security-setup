# Self-Hosted Home Security with Home Assistant

Full configuration for a self-hosted security system using Home Assistant Green, Frigate NVR, Tapo cameras, Nuki smart lock, and Discord alerts. Zero subscriptions, zero cloud dependency. Runs unattended for months.

Blog post: [Self-hosted home security for multiple properties](https://founders.do/posts/self-hosted-home-security/)

## Architecture

```
                         +------------------+
                         |   Discord        |
                         |   (alerts +      |
                         |    HD snapshots)  |
                         +--------^---------+
                                  |
                                  | webhook
                                  |
+-------------+    RTSP    +------+----------+    MQTT    +-------------+
|   Tapo      +----------->|  Home Assistant |<----------->|   Nuki      |
|   Cameras   |            |  Green          |            |   Smart     |
|             |<---go2rtc--|                 |            |   Lock      |
+-------------+  (HD snap) |  + Frigate NVR  |            +-------------+
                           |  + Coral TPU    |
                           |  + Mosquitto    |
                           +-------+---------+
                                   |
                                   | Tailscale VPN
                                   |
                           +-------+---------+
                           |   Your phone /  |
                           |   laptop        |
                           |   (anywhere)    |
                           +-----------------+
```

### Detection pipeline

```
Camera (RTSP stream2, 640x360)
  -> Frigate (person detection via Coral TPU, ~10ms)
    -> MQTT publish
      -> Home Assistant automation triggers
        -> Grab detect frame (instant, 360p)
        -> Grab HD frame via go2rtc (on-demand, 1080p)
          -> POST both to Discord webhook
```

## Hardware

| Component | Purpose | Price | Link |
|---|---|---|---|
| Home Assistant Green | Automation hub | ~$99 | [home-assistant.io/green](https://www.home-assistant.io/green/) |
| Google Coral USB | AI accelerator for person detection | ~$60 | [coral.ai](https://coral.ai/products/accelerator/) |
| TP-Link Tapo C200 | Indoor camera with RTSP | ~$30 | [tapo.com](https://www.tapo.com/product/smart-camera/tapo-c200/) |
| Nuki Smart Lock 3.0 Pro | Keyless entry via MQTT | ~$250 | [nuki.io](https://nuki.io/en/smart-lock/) |

**Software (free):** [Frigate](https://frigate.video/), [Mosquitto](https://mosquitto.org/), [go2rtc](https://github.com/AlexxIT/go2rtc), [Tailscale](https://tailscale.com/)

**Total per property: ~$500. No subscriptions.**

## Quick Start

### 1. Flash and set up HA Green

Follow the [Home Assistant Green getting started guide](https://www.home-assistant.io/green/). Create your user account.

### 2. Install add-ons

From **Settings > Add-ons > Add-on Store**, install:

1. **Advanced SSH & Web Terminal** - remote shell access
2. **Tailscale** - VPN mesh for remote access
3. **Mosquitto broker** - MQTT
4. **Frigate (Full Access)** - NVR with AI detection

Add the Frigate repo first: three dots menu > Repositories > add `https://github.com/blakeblackshear/frigate-hass-addons`

Enable **Start on boot** and **Watchdog** on all add-ons.

### 3. Configure cameras

Set up Camera Account on each Tapo camera via the Tapo app (username and password for RTSP access).

Find camera IPs from your router or:
```bash
# Scan for RTSP devices on your network
for i in $(seq 1 254); do
  (nc -z -G 1 192.168.1.$i 554 2>/dev/null && echo "192.168.1.$i") &
done; wait
```

### 4. Push configs

Edit the config files in this repo - replace all `<PLACEHOLDER>` values with your actual IPs and credentials.

```bash
# Push to HA device (scp doesn't work on HA OS, use cat|ssh tee)
cat homeassistant/configuration.yaml | ssh ha-device 'sudo tee /homeassistant/configuration.yaml > /dev/null'
cat homeassistant/automations.yaml | ssh ha-device 'sudo tee /homeassistant/automations.yaml > /dev/null'
cat homeassistant/secrets.yaml | ssh ha-device 'sudo tee /homeassistant/secrets.yaml > /dev/null'
cat homeassistant/scripts/health_check.py | ssh ha-device 'sudo tee /homeassistant/scripts/health_check.py > /dev/null'
cat homeassistant/scripts/enforce_privacy.py | ssh ha-device 'sudo tee /homeassistant/scripts/enforce_privacy.py > /dev/null'
cat frigate/config.yml | ssh ha-device 'sudo tee /addon_configs/ccab4aaf_frigate-fa/config.yml > /dev/null'
```

### 5. Set up integrations

In HA web UI (**Settings > Devices & Services > Add Integration**):
- **MQTT** - select the Mosquitto addon option
- **Frigate** - URL: `http://ccab4aaf-frigate-fa:5000`

### 6. Set up cron jobs

In the SSH addon configuration, add init_commands:

```json
{
  "init_commands": [
    "pip3 install --break-system-packages -q pytapo requests",
    "printf '*/5 * * * * SUPERVISOR_TOKEN=%s /usr/bin/python3 /homeassistant/scripts/enforce_privacy.py >> /tmp/privacy_enforcer.log 2>&1\\n*/10 * * * * SUPERVISOR_TOKEN=%s /usr/bin/python3 /homeassistant/scripts/health_check.py >> /tmp/health_check.log 2>&1\\n' \"${SUPERVISOR_TOKEN}\" \"${SUPERVISOR_TOKEN}\" | crontab -",
    "crond"
  ]
}
```

Restart the SSH addon.

## Configuration

### What to change per property

| Placeholder | Where | What |
|---|---|---|
| `<DISCORD_WEBHOOK_URL>` | configuration.yaml, secrets.yaml | Discord channel webhook |
| `<CAMERA_1_IP>`, `<CAMERA_2_IP>` | frigate/config.yml | Camera LAN IPs |
| `<TAPO_USER>`, `<TAPO_PASS>` | frigate/config.yml | Camera RTSP credentials |
| `<TAPO_CLOUD_PASS>` | scripts/enforce_privacy.py | TP-Link cloud account password (for pytapo) |
| `<MQTT_PASSWORD>` | frigate/config.yml, secrets.yaml | Mosquitto password for Frigate |

### Nuki Smart Lock

The Nuki 3.0 Pro connects directly to Mosquitto via built-in Wi-Fi. Configure in the Nuki app: Features & Configuration > Smart Home > MQTT. Point it at your HA Green's LAN IP, port 1883, with a dedicated Mosquitto user. HA auto-discovers the lock via MQTT.

## Features

### Person detection with Discord alerts

Frigate detects persons via the Coral TPU. Home Assistant sends two Discord messages per detection:
1. **Instant**: low-res detect frame (~0.1s)
2. **HD follow-up**: 1080p frame grabbed on-demand via go2rtc (~2s)

### Daily security digest

Morning Discord summary with detection counts per camera, lock state, door state, and battery level. Configurable time via `input_datetime.daily_digest_time`.

### Privacy mode enforcement

Cron script runs every 5 minutes. Checks an `input_boolean` toggle per camera in HA. If enabled, forces privacy mode on via the local Tapo API (pytapo). Cameras go dark when you're home, reactivate when you leave.

### Health monitoring and auto-recovery

Cron script runs every 10 minutes. Checks HA Core, Frigate, and Mosquitto. Escalating recovery:

| Failures | Time | Action |
|---|---|---|
| 1 | 10 min | Restart failing addon |
| 3 | 30 min | Restart HA Core |
| 6 | 60 min | Reboot host (max 1/day) |

Discord notification on every recovery action. Prevents reboot loops.

## File structure

```
home-assistant-security-setup/
├── README.md
├── LICENSE
├── homeassistant/
│   ├── configuration.yaml      # Shell commands, input booleans, counters, rest commands
│   ├── automations.yaml        # Person detection, counters, daily digest
│   ├── secrets.yaml.template   # Required secrets with descriptions
│   └── scripts/
│       ├── enforce_privacy.py  # Privacy mode enforcement via pytapo
│       └── health_check.py     # Auto-recovery with escalating restarts
└── frigate/
    └── config.yml              # Frigate config: cameras, Coral TPU, MQTT, go2rtc
```

## License

MIT
