#!/usr/bin/env python3
"""Shared GPIO helpers, service catalogue, and health utilities for p4n4 scripts."""

import RPi.GPIO as GPIO
import socket
import time
from datetime import datetime

# --- Constants ---

LED_PIN       = 17    # BCM
PROBE_TIMEOUT = 1.0   # TCP connect timeout (seconds)

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


# --- Logging ---

def log(msg: str) -> None:
    print(f"[p4n4] {msg}")


# --- GPIO helpers ---

def setup_gpio(initial_state=GPIO.LOW) -> None:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(LED_PIN, GPIO.OUT)
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
