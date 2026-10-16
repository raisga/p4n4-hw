# p4n4-hw

Hardware designs and scripts for a **p4n4** platform based development board, built around the Raspberry Pi 5.

## Repository Structure

```
hw/
├── dev-board/               # KiCad project: main dev board (schematic + PCB)
├── prototypes/
│   └── leds-indicator/      # KiCad project: LED indicator prototype board
├── tests/                   # pytest suite for the scripts (fake RPi.GPIO, no Pi needed)
└── scripts/
    └── rpi5/
        ├── p4n4_hwd.py            # Hardware daemon: LED, button, health and MQTT status in one
        ├── install-hwd.sh         # Installs the daemon as a systemd service
        ├── systemd/               # Its unit file and settings template
        ├── p4n4_common.py         # Shared GPIO helpers, service catalogue, health utilities
        ├── p4n4_boot_sim.py       # Boot sequence simulator
        ├── p4n4_shutdown_sim.py   # Graceful shutdown simulator
        ├── p4n4_health_monitor.py # Service health monitor (TCP probe + GPIO LED)
        ├── p4n4_button_handler.py # Physical button interface (single / double / long press)
        └── p4n4_mqtt_indicator.py # MQTT traffic activity indicator
```

## Hardware

All PCB designs use [KiCad](https://www.kicad.org/) (v8+). They're work in progress: the
board and PCB files are still empty placeholders.

| Design | Location | Description |
|---|---|---|
| Dev Board | `dev-board/` | Main development board schematic and PCB layout |
| LEDs Indicator | `prototypes/leds-indicator/` | Prototype indicator board for status LEDs |

## Scripts

All scripts run on a **Raspberry Pi 5** and share a common GPIO pin assignment:

| Pin | Role |
|---|---|
| GPIO 17 (BCM) | Status LED (all scripts) |
| GPIO 27 (BCM) | Push button (`p4n4_hwd.py` and `p4n4_button_handler.py`) |

Shared logic (GPIO setup, LED helpers, service catalogue, health checks, restart and shutdown) lives in `p4n4_common.py` and is imported by every script.

On a node, run **`p4n4_hwd.py`**, the daemon: it does what the health monitor, the button
handler and the MQTT indicator do, in one process. Those three are single-purpose versions
for trying one thing out; they drive the same pins, so run only one script at a time.

**Requirements:** the `RPi.GPIO` API, and `paho-mqtt` 2.0 or later for the daemon and the MQTT indicator.

On the Raspberry Pi 5, `RPi.GPIO` has to be the [`rpi-lgpio`](https://rpi-lgpio.readthedocs.io/)
drop-in. The original `RPi.GPIO` can't drive the Pi 5's GPIO, which moved to the RP1 chip; it
fails with "Cannot determine SOC peripheral base address". Install the drop-in from apt (it
replaces `python3-rpi.gpio`), then create a virtual environment that can see it: Raspberry Pi
OS blocks `pip install` outside one.

```bash
sudo apt install python3-rpi-lgpio
python3 -m venv --system-site-packages ~/.venvs/p4n4-hw
~/.venvs/p4n4-hw/bin/pip install "paho-mqtt>=2"
~/.venvs/p4n4-hw/bin/python scripts/rpi5/p4n4_health_monitor.py
```

On a workstation, [p4n4-emu](https://github.com/raisga/p4n4-emu) runs the scripts without
hardware: `p4n4-emu run --gpio-mqtt localhost scripts/rpi5/p4n4_button_handler.py` swaps in
an emulated Pi 5's GPIO, and `emu/gpio/27/set` presses the button.

### Configuration

The daemon, the health monitor and the button handler's health report read these environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `P4N4_HOST` | `localhost` | Host the services run on |
| `P4N4_PORTS` | the stacks' defaults | Changed host ports, e.g. `grafana=3001,ollama=11435` |
| `P4N4_SERVICES` | all | Services to check, e.g. `mosquitto,influxdb,node-red,grafana` |
| `P4N4_CRITICAL_SERVICES` | `mosquitto,influxdb` | Services whose failure raises the critical alert |
| `P4N4_API_URL` | `http://$P4N4_HOST:8000` | p4n4-api, whose `/ready` is checked first; `off` for TCP probes only |

Labels are the ones in the health report. A label that isn't, or a bad port, stops the script
with a message. Leave out the optional services this node doesn't run (Letta, n8n, the
runner…) with `P4N4_SERVICES`, or the monitor counts them as down.

---

### `p4n4_hwd.py` (hardware daemon)

One process owns the LED and the button, checks the services every 10 seconds (as the health
monitor does, but in a thread of its own, so a slow check never stalls the LED), shows MQTT
traffic, and publishes the node's status.

The LED plays one pattern at a time, the most important one first:

| Priority | What | Pattern |
|---|---|---|
| 1 | Button feedback | As the button handler's; three long blinks count down a shutdown |
| 2 | Critical service down | Rapid 6-pulse alert burst; MQTT traffic isn't shown |
| 3 | MQTT traffic | A pulse per message (bursts for alerts), between the health patterns |
| 4 | Service(s) down | One slow blink per failing service |
| 5 | All up | Double heartbeat pulse every 4 s |

The LED stays dark until the first check is in.

| Press | Action |
|---|---|
| Single | Health report in the log, and a check right away |
| Double | `docker restart` each p4n4 container, in start order |
| Hold 3 s | Shutdown after a 3 s countdown; press again during it to cancel |

It publishes, with `<node>` being `P4N4_NODE_ID` (default: the hostname):

| Topic | Payload | |
|---|---|---|
| `status/<node>/online` | `{"online": true}` | Retained. The last will, and a clean stop, set `false` |
| `status/<node>/health` | `{"state": "ok" \| "degraded" \| "critical", "down": [...], "services": {...}, "ts": ...}` | Retained, when it changes |
| `sensors/<node>/button` | `{"value": 1, "press": "single" \| "double" \| "long"}` | Per press. Node-RED stores it in InfluxDB like any reading (`sensor=button`) |

It reads the [configuration](#configuration) variables, `P4N4_NODE_ID`, and `MQTT_USER` /
`MQTT_PASSWORD` for a broker that needs a login. The broker is the `mosquitto` service's host
and port.

**Install it as a service** (as the user it should run as; the script uses sudo itself):

```bash
scripts/rpi5/install-hwd.sh --shutdown
journalctl -u p4n4-hwd -f
```

It installs rpi-lgpio, creates `~/.venvs/p4n4-hw` with paho-mqtt, adds the user to the `gpio`
and `docker` groups, and starts `p4n4-hwd.service`, running from this checkout. Settings go in
`/etc/p4n4/hwd.env` (root-only; created from `systemd/hwd.env.example`, kept on a re-run).
`--shutdown` adds the passwordless-sudo rule for `shutdown` that the long press needs. Re-run
it after moving the checkout.

---

### `p4n4_boot_sim.py`

Simulates the p4n4 platform boot sequence. Each phase is reflected by a distinct LED blink pattern, ending with the LED held solid once the platform is fully ready.

| Phase | Pattern |
|---|---|
| Power-on self-test | Rapid flicker (12×, 80 ms) |
| Bootloader | Fast blink (6×, 150 ms) |
| Kernel load | Medium blink (5×, 300 ms) |
| System services | 1 blink per service (500 ms) |
| Network bridge | 3× burst of 4 pulses (250 ms) |
| IoT stack (MING) | 1 blink per service (600 ms) |
| GenAI stack | 1 blink per service (600 ms) |
| Edge inference (AI stack, `ei-runner`) | 1 blink per service (600 ms) |
| Boot complete | Triple pulse → LED solid on |

```bash
python3 scripts/rpi5/p4n4_boot_sim.py
```

---

### `p4n4_shutdown_sim.py`

Simulates a graceful platform shutdown in reverse boot order (API → edge inference → GenAI → IoT → network bridge → kernel → power-off). The LED starts solid and fades out as the last phase completes.

| Phase | Pattern |
|---|---|
| Stop API / stacks | 1 blink per service (600 ms) |
| Teardown network bridge | 3× burst of 4 pulses (250 ms) |
| Stop system services | 1 blink per service (600 ms) |
| Kernel shutdown | Medium blink (3×, then 2×, 300 ms) |
| Power-off | Fade-out (5 pulses, lengthening off-time) |

```bash
python3 scripts/rpi5/p4n4_shutdown_sim.py
```

---

### `p4n4_health_monitor.py`

Checks the p4n4 platform services every 10 seconds and reflects aggregate health on the LED. A status table is also printed to stdout on each sweep.

When p4n4-api answers, its `GET /ready` decides for InfluxDB, Ollama, Letta and the edge
runner: it tells a working InfluxDB from one whose port is merely open, and the report shows
its reason for a failed check. Every other service, and all of them when the API doesn't
answer, gets a TCP probe. The MQTT broker always does, because `/ready`'s `mqtt` check is the
API's own connection, which also fails on the API's settings.

| State | LED pattern |
|---|---|
| All services up | Double heartbeat pulse every 4 s |
| Non-critical service(s) down | Slow blink — one blink per failing service (350 ms) |
| Critical service down (`mosquitto` or `influxdb`) | Rapid 6-pulse alert burst (120 ms) |

The broker and InfluxDB are critical because every other service depends on them. Set
`P4N4_CRITICAL_SERVICES` (comma-separated labels from the report, e.g.
`mosquitto,influxdb,node-red`) to choose others.

```
[p4n4] Health report — 2025-01-15 14:32:00
  Service                    Port  Status
  ------------------------  ------  ------
  mosquitto                  1883  UP
  influxdb                   8086  DOWN [critical]  (InfluxDB is starting)
  ...
  p4n4-dashboard             8088  UP
```

```bash
python3 scripts/rpi5/p4n4_health_monitor.py
```

---

### `p4n4_button_handler.py`

Listens for press events on GPIO 27 and dispatches one of three actions based on press type:

| Press type | Action | LED feedback |
|---|---|---|
| Single press | Print live health report (TCP probe) | 1 short pulse |
| Double press | `docker restart` each p4n4 container, in start order (`p4n4-mqtt`, `p4n4-influxdb`, … `p4n4-api`, `p4n4-dashboard`) | 3-pulse burst |
| Long press (3 s) | Graceful system shutdown (`sudo -n shutdown -h now`) | Fade-out |

A restart or shutdown that fails ends with a rapid 6-pulse burst, and the log says why.
Containers that aren't on this host (a stack that isn't installed) are skipped.

The user running the script needs access to Docker (the `docker` group) for restarts, and
passwordless sudo for `shutdown`. On an account without it, a narrow sudoers rule is enough:

```bash
echo "$USER ALL=(root) NOPASSWD: /usr/sbin/shutdown" | sudo tee /etc/sudoers.d/p4n4-shutdown
sudo chmod 0440 /etc/sudoers.d/p4n4-shutdown
```

```bash
python3 scripts/rpi5/p4n4_button_handler.py
```

---

### `p4n4_mqtt_indicator.py`

Subscribes to the topics the platform publishes on (`sensors/#`, `inference/#`, `devices/#`, `alerts/#`) and pulses the LED for each arriving message. Alerts (`alerts/<device-id>/critical`, `alerts/escalated`) trigger a faster burst instead of a single pulse. Falls back to a slow idle heartbeat when no traffic is present.

| Event | LED pattern |
|---|---|
| Normal message | Single pulse (50 ms on/off) |
| Alert message | 5-pulse burst (80 ms on / 50 ms off) |
| Idle (no traffic for 8 s) | Single heartbeat pulse |

Default broker: `localhost:1883`. Override with `--host` / `--port`. When the broker requires a login, set `MQTT_USER` and `MQTT_PASSWORD` in the environment (or pass `--username` / `--password`, though other users can see options in the process list).

```bash
MQTT_USER=indicator MQTT_PASSWORD=... \
  ~/.venvs/p4n4-hw/bin/python scripts/rpi5/p4n4_mqtt_indicator.py [--host HOST] [--port PORT]
```

---

## Development

The tests run on any machine: `tests/conftest.py` puts a fake `RPi.GPIO` in place before the
scripts are imported. With [uv](https://docs.astral.sh/uv/):

```bash
uv run pytest
uv run ruff check .
```

CI runs both on Python 3.11 (Raspberry Pi OS bookworm), 3.12 and 3.13.

---

## License

MIT - see [LICENSE](LICENSE).
