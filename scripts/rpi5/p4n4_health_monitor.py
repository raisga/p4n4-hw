#!/usr/bin/env python3
# Monitors p4n4 platform service health by probing TCP ports and reflects
# the overall status on the GPIO LED: heartbeat = all healthy,
# warn blink = degraded, rapid alert = critical service down.

import time
import RPi.GPIO as GPIO
from p4n4_common import (
    LED_PIN, SERVICES,
    setup_gpio, led_off, blink,
    check_services, print_report, log,
)

CHECK_INTERVAL  = 10.0  # seconds between full health sweeps

# LED timing constants (seconds)
HEARTBEAT_ON    = 0.08
HEARTBEAT_OFF   = 0.12
HEARTBEAT_PAUSE = 4.0
WARN_INTERVAL   = 0.35
ALERT_INTERVAL  = 0.12
ALERT_PAUSE     = 0.6


def heartbeat():
    blink(2, HEARTBEAT_ON, HEARTBEAT_OFF)
    time.sleep(HEARTBEAT_PAUSE)


def warn_blink(count):
    blink(count, WARN_INTERVAL)
    time.sleep(WARN_INTERVAL)


def alert_blink():
    blink(6, ALERT_INTERVAL)
    time.sleep(ALERT_PAUSE)


# --- Entry point ---

def main():
    setup_gpio()
    log("Health monitor started. Ctrl+C to stop.")
    log(f"Checking {len(SERVICES)} services every {CHECK_INTERVAL}s on GPIO {LED_PIN}.")

    last_check = 0.0
    results, n_down, critical_down = [], 0, False

    try:
        while True:
            now = time.monotonic()
            if now - last_check >= CHECK_INTERVAL:
                results, n_down, critical_down = check_services()
                print_report(results)
                last_check = time.monotonic()

            if critical_down:
                alert_blink()
            elif n_down > 0:
                warn_blink(n_down)
            else:
                heartbeat()

    except KeyboardInterrupt:
        print("\n[p4n4] Monitor stopped.")
    finally:
        led_off()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
