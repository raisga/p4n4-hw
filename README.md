# p4n4-hw

Hardware designs and scripts for a **p4n4** platform based development board, built around the Raspberry Pi 5.

## Repository Structure

```
hw/
├── dev-board/               # KiCad project: main dev board (schematic + PCB)
├── prototypes/
│   └── leds-indicator/      # KiCad project: LED indicator prototype board
└── scripts/
    └── rpi5/
        ├── p4n4_common.py         # Shared GPIO helpers, service catalogue, health utilities
        ├── p4n4_boot_sim.py       # Boot sequence simulator
        ├── p4n4_shutdown_sim.py   # Graceful shutdown simulator
        ├── p4n4_health_monitor.py # Service health monitor (TCP probe + GPIO LED)
        ├── p4n4_button_handler.py # Physical button interface (single / double / long press)
        └── p4n4_mqtt_indicator.py # MQTT traffic activity indicator
```

## Hardware

All PCB designs use [KiCad](https://www.kicad.org/) (v8+).

| Design | Location | Description |
|---|---|---|
| Dev Board | `dev-board/` | Main development board schematic and PCB layout |
| LEDs Indicator | `prototypes/leds-indicator/` | Prototype indicator board for status LEDs |

## Scripts

All scripts run on a **Raspberry Pi 5** and share a common GPIO pin assignment:

| Pin | Role |
|---|---|
| GPIO 17 (BCM) | Status LED (all scripts) |
| GPIO 27 (BCM) | Push button (`p4n4_button_handler.py` only) |

Shared logic (GPIO setup, LED helpers, service catalogue, TCP probe) lives in `p4n4_common.py` and is imported by every script.

**Requirements:** `RPi.GPIO`, and `paho-mqtt` for the MQTT indicator only.

```bash
pip install RPi.GPIO paho-mqtt
```

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
| Edge AI stack | 1 blink per service (600 ms) |
| Boot complete | Triple pulse → LED solid on |

```bash
python3 scripts/rpi5/p4n4_boot_sim.py
```

---

### `p4n4_shutdown_sim.py`

Simulates a graceful platform shutdown in reverse boot order (API → Edge AI → GenAI → IoT → network bridge → kernel → power-off). The LED starts solid and fades out as the last phase completes.

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

Probes all p4n4 platform services via TCP every 10 seconds and reflects aggregate health on the LED. A status table is also printed to stdout on each sweep.

| State | LED pattern |
|---|---|
| All services up | Double heartbeat pulse every 4 s |
| Non-critical service(s) down | Slow blink — one blink per failing service (350 ms) |
| Critical service down (`p4n4-api`) | Rapid 6-pulse alert burst (120 ms) |

```
[p4n4] Health report — 2025-01-15 14:32:00
  Service                    Port  Status
  ------------------------  ------  ------
  mosquitto                  1883  UP
  influxdb                   8086  UP
  ...
  p4n4-api                   8000  DOWN [critical]
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
| Double press | `docker restart` all non-critical services | 3-pulse burst |
| Long press (3 s) | Graceful system shutdown (`sudo shutdown -h now`) | Fade-out |

```bash
python3 scripts/rpi5/p4n4_button_handler.py
```

---

### `p4n4_mqtt_indicator.py`

Subscribes to key MQTT topics and pulses the LED for each arriving message. Alert topics (`alert/#`, `error/#`) trigger a faster burst instead of a single pulse. Falls back to a slow idle heartbeat when no traffic is present.

| Event | LED pattern |
|---|---|
| Normal message | Single pulse (50 ms on/off) |
| Alert / error message | 5-pulse burst (80 ms on / 50 ms off) |
| Idle (no traffic for 8 s) | Single heartbeat pulse |

Default broker: `localhost:1883`. Override with `--host` / `--port`.

```bash
pip install paho-mqtt
python3 scripts/rpi5/p4n4_mqtt_indicator.py [--host HOST] [--port PORT]
```

---

## License

MIT - see [LICENSE](LICENSE).
