#!/usr/bin/env python3
"""Shared GPIO helpers, service catalogue, and health utilities for p4n4 scripts.

GPIO goes through the RPi.GPIO API. On a Raspberry Pi 5 that has to be the
rpi-lgpio drop-in (`sudo apt install python3-rpi-lgpio`): the original RPi.GPIO
can't drive the Pi 5's GPIO, which moved to the RP1 chip. On a workstation,
p4n4-emu's gpio_stub provides the same API.

Health settings come from the environment (see load_services and load_api_url):
P4N4_HOST, P4N4_PORTS, P4N4_SERVICES, P4N4_CRITICAL_SERVICES and P4N4_API_URL.
"""

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime

import RPi.GPIO as GPIO

# --- Constants ---

LED_PIN       = 17    # BCM
PROBE_TIMEOUT = 1.0   # TCP connect timeout (seconds)
API_TIMEOUT   = 5.0   # /ready waits on the services it checks (up to 3 s for the runner)

DEFAULT_HOST = "localhost"

# (label, default host port) of every service the health check knows, in report order.
# system1 and telegraf publish no host port, so only DOCKER_SERVICES lists them.
SERVICE_PORTS = [
    ("mosquitto",           1883),
    ("influxdb",            8086),
    ("node-red",            1880),
    ("grafana",             3000),
    ("ollama",              11434),
    ("letta",               8283),
    ("n8n",                 5678),
    ("edge-impulse-runner", 8080),
    ("p4n4-api",            8000),
    ("p4n4-dashboard",      8088),
]

# Services the platform can't work without: the MQTT broker and InfluxDB, which
# the others depend on. A comma-separated P4N4_CRITICAL_SERVICES overrides them.
DEFAULT_CRITICAL = "mosquitto,influxdb"

# p4n4-api's /ready check name → service label. MQTT isn't mapped: that check is the
# API's own broker connection, which also fails on the API's credentials or settings,
# so the TCP probe decides for mosquitto.
API_CHECKS = {
    "influxdb":    "influxdb",
    "ollama":      "ollama",
    "letta":       "letta",
    "edge_runner": "edge-impulse-runner",
}

# The stacks' container names (their compose files' container_name), in start order
# (iot, ai, api, dashboard), so a restart brings the broker and InfluxDB back first
DOCKER_SERVICES = [
    "p4n4-mqtt", "p4n4-influxdb", "p4n4-node-red", "p4n4-grafana", "p4n4-telegraf",
    "p4n4-ollama", "p4n4-letta", "p4n4-n8n", "p4n4-system1", "p4n4-ei-runner",
    "p4n4-api", "p4n4-dashboard",
]


# --- Configuration ---

def _env_list(env, name: str, default: str = "") -> list:
    return [item.strip() for item in env.get(name, default).split(",") if item.strip()]


def _host(env) -> str:
    return env.get("P4N4_HOST", "").strip() or DEFAULT_HOST


def _ports(env) -> dict:
    """SERVICE_PORTS with P4N4_PORTS ("grafana=3001,ollama=11435") applied."""
    ports = dict(SERVICE_PORTS)
    for item in _env_list(env, "P4N4_PORTS"):
        label, _, port = (part.strip() for part in item.partition("="))
        try:
            number = int(port)
        except ValueError:
            number = 0
        if label not in ports or not 0 < number < 65536:
            raise SystemExit(
                f"[p4n4] P4N4_PORTS: bad entry {item!r}. Expected label=port, with a label "
                f"from: {', '.join(ports)}"
            )
        ports[label] = number
    return ports


def load_services(env=os.environ) -> list:
    """The services to probe, as (label, host, port, critical).

    P4N4_HOST is the host they're on (default localhost), P4N4_PORTS changes ports,
    P4N4_SERVICES limits the probe to some labels (default: all of them) and
    P4N4_CRITICAL_SERVICES chooses the critical ones (default: mosquitto, influxdb).
    """
    host = _host(env)
    ports = _ports(env)
    selected = _env_list(env, "P4N4_SERVICES") or list(ports)
    critical = _env_list(env, "P4N4_CRITICAL_SERVICES", DEFAULT_CRITICAL)
    for var, names in (("P4N4_SERVICES", selected), ("P4N4_CRITICAL_SERVICES", critical)):
        unknown = [name for name in names if name not in ports]
        if unknown:
            raise SystemExit(
                f"[p4n4] {var}: unknown service {', '.join(unknown)}. "
                f"Choose from: {', '.join(ports)}"
            )
    return [
        (label, host, port, label in critical)
        for label, port in ports.items()
        if label in selected
    ]


def load_broker(env=os.environ) -> tuple:
    """The MQTT broker's (host, port): the mosquitto service's, after P4N4_HOST and
    P4N4_PORTS."""
    return _host(env), _ports(env)["mosquitto"]


def load_api_url(env=os.environ) -> str | None:
    """p4n4-api's base URL, whose /ready the health check prefers to TCP probes.

    P4N4_API_URL sets it, or turns it off with "off"; by default it's the p4n4-api
    service's host and port.
    """
    url = env.get("P4N4_API_URL", "").strip()
    if url.lower() == "off":
        return None
    if url:
        return url.rstrip("/")
    return f"http://{_host(env)}:{_ports(env)['p4n4-api']}"


SERVICES = load_services()
API_URL = load_api_url()


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


def blink(count: int, on_time: float, off_time: float | None = None) -> None:
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


def fetch_ready(api_url: str, timeout: float = API_TIMEOUT) -> dict | None:
    """p4n4-api's readiness checks ({name: {"ok": …, "detail": …}}), or None when
    the API doesn't answer /ready."""
    try:
        with urllib.request.urlopen(f"{api_url}/ready", timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        with exc:
            if exc.code != 503:  # 503 carries the same body, with a failed check
                return None
            body = exc.read()
    except (OSError, ValueError):  # URLError and timeouts are OSErrors; ValueError: bad URL
        return None
    try:
        checks = json.loads(body)["checks"]
    except (ValueError, KeyError, TypeError):
        return None
    return checks if isinstance(checks, dict) else None


def check_services(services: list = SERVICES, api_url: str | None = API_URL) -> tuple:
    """Probe services and return (results, n_down, critical_down).

    Each result is (label, port, up, critical, detail). A service p4n4-api's /ready
    checks takes the API's verdict, which tells a working InfluxDB from one whose port
    is merely open; the others, and all of them when the API doesn't answer, get a TCP
    probe. detail is the API's reason for a failed check, else None.
    """
    verdicts = {}
    checks = fetch_ready(api_url) if api_url else None
    if checks is not None:
        verdicts = {
            API_CHECKS[name]: check
            for name, check in checks.items()
            if name in API_CHECKS and isinstance(check, dict)
        }
        verdicts["p4n4-api"] = {"ok": True}

    results = []
    n_down = 0
    critical_down = False
    for label, host, port, critical in services:
        verdict = verdicts.get(label)
        if verdict is None:
            up, detail = probe(host, port), None
        else:
            up = verdict.get("ok") is True
            detail = None if up else verdict.get("detail")
        results.append((label, port, up, critical, detail))
        if not up:
            n_down += 1
            if critical:
                critical_down = True
    return results, n_down, critical_down


def health_state(n_down: int, critical_down: bool) -> str:
    """check_services' verdict in one word: "ok", "degraded" or "critical"."""
    if critical_down:
        return "critical"
    return "degraded" if n_down else "ok"


def print_report(results: list) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[p4n4] Health report — {ts}")
    print(f"  {'Service':<24} {'Port':>6}  Status")
    print(f"  {'-'*24}  {'-'*6}  {'-'*6}")
    for label, port, up, critical, detail in results:
        flag = " [critical]" if (not up and critical) else ""
        status = "UP  " if up else "DOWN"
        reason = f"  ({detail})" if detail else ""
        print(f"  {label:<24} {port:>6}  {status}{flag}{reason}")
    print()


# --- Platform actions ---

def restart_containers() -> list:
    """`docker restart` each of DOCKER_SERVICES, in order, and return the ones that
    failed. Containers that aren't on this host (a stack that isn't installed) are skipped."""
    failed = []
    for name in DOCKER_SERVICES:
        try:
            result = subprocess.run(
                ["docker", "restart", name], timeout=60, capture_output=True, text=True
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            log(f"  {name}: {e}")
            failed.append(name)
            continue
        if result.returncode == 0:
            log(f"  {name}: restarted")
        elif "No such container" in result.stderr:
            log(f"  {name}: not on this host, skipped")
        else:
            log(f"  {name}: failed — {result.stderr.strip()}")
            failed.append(name)
    return failed


def request_shutdown() -> str | None:
    """Power the system off with `sudo -n shutdown -h now`. Returns None, or why it failed
    (the user needs passwordless sudo for shutdown; see README)."""
    # -n: fail instead of waiting for a password nobody can type
    result = subprocess.run(
        ["sudo", "-n", "shutdown", "-h", "now"], capture_output=True, text=True
    )
    if result.returncode == 0:
        return None
    return result.stderr.strip() or f"exit code {result.returncode}"
