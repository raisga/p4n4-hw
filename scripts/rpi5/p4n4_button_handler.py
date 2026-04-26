#!/usr/bin/env python3
# Physical button interface for the p4n4 platform on GPIO pin 27 (BCM).
# Single press  → print a live health report (TCP probe all services).
# Double press  → restart non-critical Docker services via `docker restart`.
# Long press    → initiate a graceful system shutdown (requires sudo).
#
# LED on pin 17 gives feedback: pulse = action triggered, burst = restart, fade = shutdown.

import subprocess
import time
import threading
import RPi.GPIO as GPIO
from p4n4_common import (
    DOCKER_SERVICES,
    setup_gpio, led_off, blink, fade_out,
    check_services, print_report, log,
)

BUTTON_PIN = 27   # BCM — pulled up internally; button connects pin to GND

DEBOUNCE_MS      = 50
DOUBLE_PRESS_GAP = 0.4   # max seconds between two presses to count as double
LONG_PRESS_SECS  = 3.0   # seconds held to trigger shutdown


# --- LED feedback ---

def feedback_single():
    blink(1, 0.1, 0.0)


def feedback_restart():
    blink(3, 0.08, 0.08)


def feedback_shutdown():
    fade_out(6, on_time=0.1, factor=0.7)


# --- Actions ---

def action_health_report():
    results, _, _ = check_services()
    print_report(results)
    feedback_single()


def action_restart_services():
    log("Restarting non-critical Docker services...")
    feedback_restart()
    for name in DOCKER_SERVICES:
        log(f"  docker restart {name}")
        try:
            subprocess.run(["docker", "restart", name], timeout=30, capture_output=True)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            log(f"  warning: {e}")
    log("Restart complete.")


def action_shutdown():
    log("Long press detected — shutting down in 3 seconds. Press Ctrl+C to abort.")
    try:
        for i in range(3, 0, -1):
            log(f"  {i}...")
            time.sleep(1)
    except KeyboardInterrupt:
        log("Shutdown aborted.")
        return
    log("Initiating shutdown.")
    feedback_shutdown()
    time.sleep(0.5)
    subprocess.run(["sudo", "shutdown", "-h", "now"])


# --- Button event state machine ---

class ButtonHandler:
    """
    Tracks press/release edges and classifies them as single, double, or long.
    Runs the resolved action in a daemon thread to keep the GPIO callback fast.
    """

    def __init__(self):
        self._press_time  = 0.0
        self._press_count = 0
        self._timer       = None
        self._lock        = threading.Lock()

    def on_press(self):
        with self._lock:
            self._press_time = time.monotonic()
            self._press_count += 1
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def on_release(self):
        with self._lock:
            held = time.monotonic() - self._press_time
            if held >= LONG_PRESS_SECS:
                self._press_count = 0
                threading.Thread(target=action_shutdown, daemon=True).start()
                return
            self._timer = threading.Timer(DOUBLE_PRESS_GAP, self._resolve)
            self._timer.daemon = True
            self._timer.start()

    def _resolve(self):
        with self._lock:
            count = self._press_count
            self._press_count = 0
        if count == 1:
            threading.Thread(target=action_health_report, daemon=True).start()
        elif count >= 2:
            threading.Thread(target=action_restart_services, daemon=True).start()


_handler = ButtonHandler()


def _gpio_callback(channel):
    if GPIO.input(BUTTON_PIN) == GPIO.LOW:
        _handler.on_press()
    else:
        _handler.on_release()


# --- Entry point ---

def main():
    setup_gpio()
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH, callback=_gpio_callback, bouncetime=DEBOUNCE_MS)

    log("Button handler active on GPIO 27.")
    log("  Single press  → health report")
    log("  Double press  → restart Docker services")
    log(f"  Hold {LONG_PRESS_SECS:.0f}s        → graceful shutdown")
    log("Press Ctrl+C to exit.")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[p4n4] Button handler stopped.")
    finally:
        led_off()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
