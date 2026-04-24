#!/usr/bin/env python3
# Monitors p4n4 platform service health by probing TCP ports and reflects
# the overall status on the GPIO LED: heartbeat = all healthy,
# warn blink = degraded, rapid alert = critical service down.

import RPi.GPIO as GPIO
import socket
import time
from datetime import datetime

LED_PIN = 17  # BCM

CHECK_INTERVAL  = 10.0  # seconds between full health sweeps
PROBE_TIMEOUT   = 1.0   # TCP connect timeout per service (seconds)

# LED timing constants (seconds)
HEARTBEAT_ON    = 0.08
HEARTBEAT_OFF   = 0.12
HEARTBEAT_PAUSE = 4.0   # gap after each double-pulse when fully healthy
WARN_INTERVAL   = 0.35  # blink interval when one or more non-critical services are down
ALERT_INTERVAL  = 0.12  # rapid blink interval when a critical service is down
ALERT_PAUSE     = 0.6   # pause between alert bursts

# (label, host, port, critical)
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


# --- GPIO helpers ---

def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(LED_PIN, GPIO.OUT)
    GPIO.output(LED_PIN, GPIO.LOW)


def led_on():
    GPIO.output(LED_PIN, GPIO.HIGH)


def led_off():
    GPIO.output(LED_PIN, GPIO.LOW)


def blink(count, interval):
    for _ in range(count):
        led_on()
        time.sleep(interval)
        led_off()
        time.sleep(interval)


def heartbeat():
    """Double-pulse — signals all services healthy."""
    blink(count=2, interval=HEARTBEAT_ON)
    time.sleep(HEARTBEAT_PAUSE)


def warn_blink(count):
    """Slow blink, once per failing service."""
    blink(count=count, interval=WARN_INTERVAL)
    time.sleep(WARN_INTERVAL)


def alert_blink():
    """Rapid burst — signals a critical service is down."""
    blink(count=6, interval=ALERT_INTERVAL)
    time.sleep(ALERT_PAUSE)


# --- Health probe ---

def probe(host, port):
    """Return True if a TCP connection to host:port succeeds within PROBE_TIMEOUT."""
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def check_services():
    """Probe all services and return (results, n_down, critical_down)."""
    results = []
    n_down = 0
    critical_down = False
    for label, host, port, critical in SERVICES:
        up = probe(host, port)
        results.append((label, port, up, critical))
        if not up:
            n_down += 1
            if critical:
                critical_down = True
    return results, n_down, critical_down


# --- Reporting ---

STATUS_UP   = "UP  "
STATUS_DOWN = "DOWN"

def print_report(results):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[p4n4] Health report — {ts}")
    print(f"  {'Service':<24} {'Port':>6}  {'Status'}")
    print(f"  {'-'*24}  {'-'*6}  {'-'*6}")
    for label, port, up, critical in results:
        flag = " [critical]" if (not up and critical) else ""
        print(f"  {label:<24} {port:>6}  {STATUS_UP if up else STATUS_DOWN}{flag}")


# --- Entry point ---

def main():
    setup()
    print("[p4n4] Health monitor started. Ctrl+C to stop.")
    print(f"[p4n4] Checking {len(SERVICES)} services every {CHECK_INTERVAL}s on GPIO {LED_PIN}.")

    last_check = 0.0

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
