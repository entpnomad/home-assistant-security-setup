# Home Assistant Security Setup

Configuration and management for a Home Assistant Green security system with Frigate NVR, Tapo cameras, Nuki smart lock, and Discord alerts.

## SSH Access

Connect via Tailscale:
```bash
ssh ha-device
```

SSH config example (`~/.ssh/config`):
```
Host ha-device
    HostName <TAILSCALE_HOSTNAME>
    User <USERNAME>
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    AddKeysToAgent yes
```

## System Overview

| Property | Value |
|---|---|
| Hardware | Home Assistant Green (aarch64) |
| OS | Home Assistant OS |
| AI Accelerator | Google Coral USB TPU |

## Installed Add-ons

| Add-on | Purpose |
|---|---|
| Advanced SSH & Web Terminal | Shell access for remote management |
| Tailscale | VPN mesh for remote access from anywhere |
| Frigate (Full Access) | NVR with real-time person detection via Coral TPU |
| Mosquitto broker | MQTT message broker for Frigate and Nuki |

## Integrations

| Integration | Type | Details |
|---|---|---|
| Frigate | Custom (HACS) | Connects to Frigate NVR at `http://ccab4aaf-frigate-fa:5000` |
| MQTT | Core | Connects to Mosquitto addon |
| Nuki Smart Lock | MQTT auto-discovery | Lock/unlock, door sensor, battery via MQTT |

## File System Paths (on the HA device)

| Path | Content |
|---|---|
| `/homeassistant/` | Main HA config (also symlinked as `/root/config`) |
| `/homeassistant/configuration.yaml` | Main configuration |
| `/homeassistant/automations.yaml` | Automation definitions |
| `/homeassistant/secrets.yaml` | Secrets (webhook URLs, passwords) |
| `/homeassistant/scripts/enforce_privacy.py` | Privacy mode enforcement script |
| `/homeassistant/scripts/health_check.py` | Health monitor + auto-recovery script |
| `/homeassistant/custom_components/frigate/` | Frigate HACS integration |
| `/addon_configs/ccab4aaf_frigate-fa/config.yml` | Active Frigate config |
| `/media/frigate/` | Frigate media (clips, exports, recordings) |

## Pushing Configs TO the Device

Note: `scp` does not work on HA OS (subsystem request failed). Use `cat | ssh sudo tee` instead.

```bash
cat homeassistant/configuration.yaml | ssh ha-device 'sudo tee /homeassistant/configuration.yaml > /dev/null'
cat homeassistant/automations.yaml | ssh ha-device 'sudo tee /homeassistant/automations.yaml > /dev/null'
cat frigate/config.yml | ssh ha-device 'sudo tee /addon_configs/ccab4aaf_frigate-fa/config.yml > /dev/null'
# Then restart HA: Settings > System > Restart
```

## Pulling Configs FROM the Device

```bash
ssh ha-device "cat /homeassistant/configuration.yaml" > homeassistant/configuration.yaml
ssh ha-device "cat /homeassistant/automations.yaml" > homeassistant/automations.yaml
ssh ha-device "cat /addon_configs/ccab4aaf_frigate-fa/config.yml" > frigate/config.yml
```

## Supervisor API Access

The SSH addon's regular shell does NOT have the `SUPERVISOR_TOKEN`. To use the Supervisor API:

```bash
STOKEN=$(ssh ha-device 'sudo cat /run/s6/container_environment/SUPERVISOR_TOKEN')
ssh ha-device "sudo curl -s -H 'Authorization: Bearer $STOKEN' http://supervisor/core/api/..."
```

Common Supervisor API operations:

```bash
# Restart HA Core
ssh ha-device "sudo curl -s -X POST -H 'Authorization: Bearer $STOKEN' http://supervisor/core/restart"

# Restart an addon
ssh ha-device "sudo curl -s -X POST -H 'Authorization: Bearer $STOKEN' http://supervisor/addons/ccab4aaf_frigate-fa/restart"

# Check addon status
ssh ha-device "sudo curl -s -H 'Authorization: Bearer $STOKEN' http://supervisor/addons/ccab4aaf_frigate-fa/info"

# Add an addon repository
ssh ha-device "sudo curl -s -X POST -H 'Authorization: Bearer $STOKEN' -H 'Content-Type: application/json' -d '{\"repository\":\"https://github.com/blakeblackshear/frigate-hass-addons\"}' http://supervisor/store/repositories"
```

## Frigate Configuration

- **Addon URL:** `http://ccab4aaf-frigate-fa:5000`
- **go2rtc API:** `http://ccab4aaf-frigate-fa:1984`
- **MQTT broker:** `core-mosquitto:1883`
- **Detection:** Google Coral USB TPU (`edgetpu` type)
- **Detection resolution:** 640x360 (stream2, sub-stream)
- **Detection FPS:** 2
- **Tracked objects:** Person only
- **Motion mask:** `0,0,0.355,0,0.356,0.045,0,0.045` (masks timestamp overlay)

## Nuki Smart Lock

Connected via built-in Wi-Fi directly to Mosquitto MQTT. Configure in the Nuki app:
- Features & Configuration > Smart Home > MQTT
- Host: HA Green's LAN IP, Port: 1883
- Dedicated Mosquitto user
- HA Auto-Discovery: enabled

## SSH Addon init_commands

The SSH addon crontab runs privacy enforcement (every 5 min) and health checks (every 10 min):

```json
{
  "init_commands": [
    "pip3 install --break-system-packages -q pytapo requests",
    "printf '*/5 * * * * SUPERVISOR_TOKEN=%s /usr/bin/python3 /homeassistant/scripts/enforce_privacy.py >> /tmp/privacy_enforcer.log 2>&1\\n*/10 * * * * SUPERVISOR_TOKEN=%s /usr/bin/python3 /homeassistant/scripts/health_check.py >> /tmp/health_check.log 2>&1\\n' \"${SUPERVISOR_TOKEN}\" \"${SUPERVISOR_TOKEN}\" | crontab -",
    "crond"
  ]
}
```

## Shell Commands and !secret

**Important:** `!secret` does NOT work inside `shell_command` strings in HA. The Discord webhook URL must be hardcoded in the shell_command on the device. Use `<DISCORD_WEBHOOK_URL>` as a placeholder in version control.

`!secret` DOES work in `rest_command` and other standard HA config sections.

## Secrets (not in git)

Required secrets in `/homeassistant/secrets.yaml`:
- `discord_webhook` - Discord channel webhook URL
- `frigate_mqtt_user` / `frigate_mqtt_password` - Mosquitto credentials for Frigate
- `nuki_mqtt_password` - Mosquitto credentials for Nuki lock

Camera RTSP credentials are in the Frigate config on the device.
