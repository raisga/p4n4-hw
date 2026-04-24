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
        ├── p4n4_boot_sim.py      # Boot sequence simulator (RPi5, GPIO LED)
        └── p4n4_health_monitor.py # Service health monitor (TCP probe + GPIO LED)
```

## Hardware

All PCB designs use [KiCad](https://www.kicad.org/) (v8+).

| Design | Location | Description |
|---|---|---|
| Dev Board | `dev-board/` | Main development board schematic and PCB layout |
| LEDs Indicator | `prototypes/leds-indicator/` | Prototype indicator board for status LEDs |

## Scripts

### `scripts/rpi5/p4n4_boot_sim.py`

Simulates the p4n4 platform boot sequence on a Raspberry Pi 5 using an LED on GPIO pin 17 (BCM). Each boot phase is reflected by a distinct blink pattern:

| Phase | Pattern |
|---|---|
| Power-on self-test | Rapid flicker (12×, 80 ms) |
| Bootloader | Fast blink (6×, 150 ms) |
| Kernel load | Medium blink (5×, 300 ms) |
| System services | 1 blink per service (500 ms) |
| Network bridge | 3× burst of 4 pulses |
| IoT stack (MING) | 1 blink per service (600 ms) |
| GenAI stack | 1 blink per service (600 ms) |
| Edge AI stack | 1 blink per service (600 ms) |
| Boot complete | Triple pulse → LED solid on |

**Requirements:** Raspberry Pi 5, `RPi.GPIO`, LED on GPIO 17.

```bash
pip install RPi.GPIO
python3 scripts/rpi5/p4n4_boot_sim.py
```

### `scripts/rpi5/p4n4_health_monitor.py`

Probes all p4n4 platform services via TCP every 10 seconds and reflects the aggregate health on the same GPIO 17 LED:

| State | LED pattern |
|---|---|
| All services up | Double heartbeat pulse every 4 s |
| Non-critical service(s) down | Slow blink — one blink per failing service |
| Critical service down (`p4n4-api`) | Rapid 6-pulse alert burst |

A status table is printed to stdout on each sweep:

```
[p4n4] Health report — 2025-01-15 14:32:00
  Service                    Port  Status
  ------------------------  ------  ------
  mosquitto                  1883  UP
  influxdb                   8086  UP
  ...
  p4n4-api                   8000  DOWN [critical]
```

**Requirements:** Raspberry Pi 5, `RPi.GPIO`, all p4n4 stack services running locally.

```bash
pip install RPi.GPIO
python3 scripts/rpi5/p4n4_health_monitor.py
```

## License

MIT - see [LICENSE](LICENSE).
