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
        └── p4n4_boot_sim.py # Boot sequence simulator (RPi5, GPIO LED)
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

## License

MIT - see [LICENSE](LICENSE).
