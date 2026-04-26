#!/usr/bin/env python3
# Physical button interface for the p4n4 platform on GPIO pin 27 (BCM).
# Single press  → print a live health report (TCP probe all services).
# Double press  → restart non-critical Docker services via `docker restart`.
# Long press    → initiate a graceful system shutdown (requires sudo).
#
# LED on pin 17 gives feedback: pulse = action triggered, burst = restart, fade = shutdown.

import RPi.GPIO as GPIO
import socket
import subprocess
import time
import threading

BUTTON_PIN = 27   # BCM — pulled up internally; button connects pin to GND
LED_PIN    = 17   # BCM

DEBOUNCE_MS       = 50     # milliseconds
DOUBLE_PRESS_GAP  = 0.4    # max seconds between two presses to count as double
LONG_PRESS_SECS   = 3.0    # seconds held to trigger shutdown

PROBE_TIMEOUT = 1.0

SERVICES = [
    ("mosquitto",           "localhost", 1883,  False),
    ("influxdb",            "localhost", 8086,  False),
    ("node-red",            "localhost", 1880,  False),
    ("grafana",             "localhost", 3000,  False),
    ("ollama",              "localhost", 11434, False),
    ("letta",               "localhost", 8283,  False),
    ("n8n",                 "localhost", 5678,  False),
    ("edge-impulse-runner", "localhost", 8080,  False),
    ("p4n4-api",            "localhost", 8000,  True),
]

DOCKER_SERVICES = [
    "mosquitto", "influxdb", "node-red", "grafana",
    "ollama", "letta", "n8n", "edge-impulse-runner",
]


# --- GPIO helpers ---

def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(LED_PIN, GPIO.OUT)
    GPIO.output(LED_PIN, GPIO.LOW)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def led_on():
    GPIO.output(LED_PIN, GPIO.HIGH)


def led_off():
    GPIO.output(LED_PIN, GPIO.LOW)


def blink(count, on_time, off_time):
    for _ in range(count):
        led_on()
        time.sleep(on_time)
        led_off()
        time.sleep(off_time)


def feedback_single():
    blink(1, 0.1, 0.0)


def feedback_restart():
    blink(3, 0.08, 0.08)


def feedback_shutdown():
    on_time = 0.1
    for i in range(6):
        led_on()
        time.sleep(on_time)
        led_off()
        time.sleep(on_time * (i + 1) * 0.7)


# --- Actions ---

def probe(host, port):
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def action_health_report():
    print("\n[p4n4] === Health Report ===")
    print(f"  {'Service':<24} {'Port':>6}  Status")
    print(f"  {'-'*24}  {'-'*6}  {'-'*6}")
    for label, host, port, critical in SERVICES:
        up = probe(host, port)
        flag = " [critical]" if (not up and critical) else ""
        status = "UP  " if up else "DOWN"
        print(f"  {label:<24} {port:>6}  {status}{flag}")
    print()
    feedback_single()


def action_restart_services():
    print("\n[p4n4] Restarting non-critical Docker services...")
    feedback_restart()
    for name in DOCKER_SERVICES:
        print(f"[p4n4]   docker restart {name}")
        try:
            subprocess.run(
                ["docker", "restart", name],
                timeout=30,
                capture_output=True,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"[p4n4]   warning: {e}")
    print("[p4n4] Restart complete.")


def action_shutdown():
    print("\n[p4n4] Long press detected — shutting down in 3 seconds. Press Ctrl+C to abort.")
    try:
        for i in range(3, 0, -1):
            print(f"[p4n4]   {i}...")
            time.sleep(1)
    except KeyboardInterrupt:
        print("[p4n4] Shutdown aborted.")
        return
    print("[p4n4] Initiating shutdown.")
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
        self._press_time   = 0.0
        self._last_release = 0.0
        self._press_count  = 0
        self._timer        = None
        self._lock         = threading.Lock()

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
                t = threading.Thread(target=action_shutdown, daemon=True)
                t.start()
                return

            self._last_release = time.monotonic()
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
    setup()
    GPIO.add_event_detect(
        BUTTON_PIN,
        GPIO.BOTH,
        callback=_gpio_callback,
        bouncetime=DEBOUNCE_MS,
    )

    print("[p4n4] Button handler active on GPIO 27.")
    print("[p4n4]   Single press  → health report")
    print("[p4n4]   Double press  → restart Docker services")
    print(f"[p4n4]   Hold {LONG_PRESS_SECS:.0f}s        → graceful shutdown")
    print("[p4n4] Press Ctrl+C to exit.")

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
