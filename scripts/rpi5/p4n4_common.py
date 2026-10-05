#!/usr/bin/env python3
"""Shared GPIO helpers, service catalogue, and health utilities for p4n4 scripts.

GPIO goes through the RPi.GPIO API. On a Raspberry Pi 5 that has to be the
rpi-lgpio drop-in (`sudo apt install python3-rpi-lgpio`): the original RPi.GPIO
can't drive the Pi 5's GPIO, which moved to the RP1 chip. On a workstation,
p4n4-emu's gpio_stub provides the same API.
"""

import os
import socket
import time
from datetime import datetime

import RPi.GPIO as GPIO

# --- Constants ---

LED_PIN       = 17    # BCM
PROBE_TIMEOUT = 1.0   # TCP connect timeout (seconds)

# Services the platform can't work without: the MQTT broker and InfluxDB, which
# the others depend on. A comma-separated P4N4_CRITICAL_SERVICES overrides them.
CRITICAL_SERVICES = {
    name.strip()
    for name in os.environ.get("P4N4_CRITICAL_SERVICES", "mosquitto,influxdb").split(",")
    if name.strip()
}

# (label, host, port, critical)
SERVICES = [
    (label, host, port, label in CRITICAL_SERVICES)
    for label, host, port in [
        ("mosquitto",           "localhost", 1883),
        ("influxdb",            "localhost", 8086),
        ("node-red",            "localhost", 1880),
        ("grafana",             "localhost", 3000),
        ("ollama",              "localhost", 11434),
        ("letta",               "localhost", 8283),
        ("n8n",                 "localhost", 5678),
        ("edge-impulse-runner", "localhost", 8080),
        ("p4n4-api",            "localhost", 8000),
    ]
]

# The stacks' container names (their compose files' container_name)
DOCKER_SERVICES = [
    "p4n4-mqtt", "p4n4-influxdb", "p4n4-node-red", "p4n4-grafana",
    "p4n4-ollama", "p4n4-letta", "p4n4-n8n", "p4n4-ei-runner",
]


# --- Logging ---

def log(msg: str) -> None:
    print(f"[p4n4] {msg}")


# --- GPIO helpers ---

def setup_gpio(initial_state=GPIO.LOW) -> None:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(LED_PIN, GPIO.OUT)
    except RuntimeError as exc:
        # The original RPi.GPIO on a Pi 5: "Cannot determine SOC peripheral base address"
        raise SystemExit(
            f"[p4n4] GPIO unavailable: {exc}\n"
            "[p4n4] On a Raspberry Pi 5, install the rpi-lgpio drop-in for RPi.GPIO: "
            "sudo apt install python3-rpi-lgpio"
        ) from exc
    GPIO.output(LED_PIN, initial_state)


def led_on() -> None:
    GPIO.output(LED_PIN, GPIO.HIGH)


def led_off() -> None:
    GPIO.output(LED_PIN, GPIO.LOW)


def led_toggle() -> None:
    GPIO.output(LED_PIN, not GPIO.input(LED_PIN))


def blink(count: int, on_time: float, off_time: float = None) -> None:
    """Blink LED `count` times. off_time defaults to on_time when omitted."""
    if off_time is None:
        off_time = on_time
    for _ in range(count):
        led_on()
        time.sleep(on_time)
        led_off()
        time.sleep(off_time)


def burst(pulses: int, on_time: float, off_time: float) -> None:
    blink(pulses, on_time, off_time)


def fade_out(pulses: int, on_time: float = 0.1, factor: float = 0.8) -> None:
    """Gradually lengthen off-time between pulses to simulate a fade to dark."""
    for i in range(pulses):
        led_on()
        time.sleep(on_time)
        led_off()
        time.sleep(on_time * (i + 1) * factor)


# --- Health probe ---

def probe(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def check_services() -> tuple:
    """Probe all SERVICES and return (results, n_down, critical_down)."""
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


def print_report(results: list) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[p4n4] Health report — {ts}")
    print(f"  {'Service':<24} {'Port':>6}  Status")
    print(f"  {'-'*24}  {'-'*6}  {'-'*6}")
    for label, port, up, critical in results:
        flag = " [critical]" if (not up and critical) else ""
        status = "UP  " if up else "DOWN"
        print(f"  {label:<24} {port:>6}  {status}{flag}")
    print()
