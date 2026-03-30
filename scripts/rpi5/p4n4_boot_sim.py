#!/usr/bin/env python3
# Simulates the p4n4 platform boot-up sequence on a Raspberry Pi 5 using an LED on GPIO pin 17.
# Phases mirror a real p4n4 node: hardware init → system services → Docker → MING → GenAI → Edge AI → ready.

import RPi.GPIO as GPIO
import time

LED_PIN = 17  # BCM pin number

# Phase timing constants (seconds)
PHASE_POST_INTERVAL       = 0.08   # rapid flicker during power-on self-test
PHASE_BOOTLOADER_INTERVAL = 0.15   # fast blink during bootloader
PHASE_KERNEL_INTERVAL     = 0.3    # medium blink during kernel load
PHASE_SERVICE_INTERVAL    = 0.5    # slow blink per system service
PHASE_STACK_INTERVAL      = 0.6    # slower blink per Docker service
PHASE_NETWORK_INTERVAL    = 0.25   # quick burst during network bridge setup
PHASE_READY_PULSES        = 3      # confirmation pulses when fully ready


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


def led_toggle():
    state = GPIO.input(LED_PIN)
    GPIO.output(LED_PIN, not state)


def blink(count, interval):
    for _ in range(count):
        led_on()
        time.sleep(interval)
        led_off()
        time.sleep(interval)


def burst(pulses, on_time, off_time):
    """Short burst of pulses with separate on/off timing."""
    for _ in range(pulses):
        led_on()
        time.sleep(on_time)
        led_off()
        time.sleep(off_time)


# --- Boot phases ---

def phase_power_on():
    """POST — rapid flicker signals hardware is alive."""
    print("[p4n4] Power-on self-test...")
    blink(count=12, interval=PHASE_POST_INTERVAL)


def phase_bootloader():
    """Bootloader — firmware initializing memory and peripherals."""
    print("[p4n4] Bootloader initializing...")
    blink(count=6, interval=PHASE_BOOTLOADER_INTERVAL)


def phase_kernel_load():
    """Kernel load — decompressing image and mounting root filesystem."""
    print("[p4n4] Loading kernel...")
    blink(count=5, interval=PHASE_KERNEL_INTERVAL)
    print("[p4n4] Mounting root filesystem...")
    blink(count=3, interval=PHASE_KERNEL_INTERVAL)


def phase_system_services():
    """Low-level system services required before Docker can start."""
    services = [
        "syslog",
        "udev",
        "i2c",
        "spi",
        "gpio-daemon",
        "docker",
    ]
    for service in services:
        print(f"[p4n4] Starting: {service}")
        blink(count=1, interval=PHASE_SERVICE_INTERVAL)
        time.sleep(0.1)


def phase_network_bridge():
    """Create the p4n4-net Docker bridge shared across all stacks."""
    print("[p4n4] Configuring p4n4-net bridge (172.20.0.0/16)...")
    for _ in range(3):
        burst(pulses=4, on_time=PHASE_NETWORK_INTERVAL, off_time=0.1)
        time.sleep(0.3)
    print("[p4n4] p4n4-net ready.")


def phase_iot_stack():
    """MING stack — Mosquitto, InfluxDB, Node-RED, Grafana."""
    print("[p4n4] Starting IoT stack (MING)...")
    services = [
        "mosquitto   :1883",
        "influxdb    :8086",
        "node-red    :1880",
        "grafana     :3000",
    ]
    for service in services:
        print(f"[p4n4]   {service}")
        blink(count=1, interval=PHASE_STACK_INTERVAL)
        time.sleep(0.1)


def phase_ai_stack():
    """GenAI stack — Ollama, Letta, n8n."""
    print("[p4n4] Starting GenAI stack...")
    services = [
        "ollama      :11434",
        "letta       :8283",
        "n8n         :5678",
    ]
    for service in services:
        print(f"[p4n4]   {service}")
        blink(count=1, interval=PHASE_STACK_INTERVAL)
        time.sleep(0.1)


def phase_edge_stack():
    """Edge AI stack — Edge Impulse runner."""
    print("[p4n4] Starting Edge AI stack...")
    services = [
        "edge-impulse-runner :8080",
    ]
    for service in services:
        print(f"[p4n4]   {service}")
        blink(count=1, interval=PHASE_STACK_INTERVAL)
        time.sleep(0.1)


def phase_api_ready():
    """p4n4 REST API gateway — last service to come up."""
    print("[p4n4] Starting p4n4-api :8000...")
    blink(count=1, interval=PHASE_STACK_INTERVAL)


def phase_boot_complete():
    """All stacks healthy — triple pulse then LED holds solid."""
    print("[p4n4] All services healthy. Platform ready.")
    burst(pulses=PHASE_READY_PULSES, on_time=0.1, off_time=0.1)
    time.sleep(0.2)
    led_on()


# --- Entry point ---

def main():
    setup()
    try:
        phase_power_on()
        phase_bootloader()
        phase_kernel_load()
        phase_system_services()
        phase_network_bridge()
        phase_iot_stack()
        phase_ai_stack()
        phase_edge_stack()
        phase_api_ready()
        phase_boot_complete()

        print("[p4n4] Press Ctrl+C to shut down.")
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[p4n4] Shutdown signal received.")
    finally:
        led_off()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
