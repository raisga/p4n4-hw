#!/usr/bin/env python3
# Simulates the p4n4 platform boot-up sequence on a Raspberry Pi 5.
# Phases mirror a real p4n4 node: hardware init → system services → Docker → MING → GenAI → Edge AI → ready.

import time
import RPi.GPIO as GPIO
from p4n4_common import setup_gpio, led_on, led_off, blink, burst, log

# Phase timing constants (seconds)
PHASE_POST_INTERVAL       = 0.08
PHASE_BOOTLOADER_INTERVAL = 0.15
PHASE_KERNEL_INTERVAL     = 0.3
PHASE_SERVICE_INTERVAL    = 0.5
PHASE_STACK_INTERVAL      = 0.6
PHASE_NETWORK_INTERVAL    = 0.25
PHASE_READY_PULSES        = 3


# --- Boot phases ---

def phase_power_on():
    log("Power-on self-test...")
    blink(12, PHASE_POST_INTERVAL)


def phase_bootloader():
    log("Bootloader initializing...")
    blink(6, PHASE_BOOTLOADER_INTERVAL)


def phase_kernel_load():
    log("Loading kernel...")
    blink(5, PHASE_KERNEL_INTERVAL)
    log("Mounting root filesystem...")
    blink(3, PHASE_KERNEL_INTERVAL)


def phase_system_services():
    for service in ["syslog", "udev", "i2c", "spi", "gpio-daemon", "docker"]:
        log(f"Starting: {service}")
        blink(1, PHASE_SERVICE_INTERVAL)
        time.sleep(0.1)


def phase_network_bridge():
    log("Configuring p4n4-net bridge (172.20.0.0/16)...")
    for _ in range(3):
        burst(4, PHASE_NETWORK_INTERVAL, 0.1)
        time.sleep(0.3)
    log("p4n4-net ready.")


def phase_iot_stack():
    log("Starting IoT stack (MING)...")
    for service in ["mosquitto   :1883", "influxdb    :8086", "node-red    :1880", "grafana     :3000"]:
        log(f"  {service}")
        blink(1, PHASE_STACK_INTERVAL)
        time.sleep(0.1)


def phase_ai_stack():
    log("Starting GenAI stack...")
    for service in ["ollama      :11434", "letta       :8283", "n8n         :5678"]:
        log(f"  {service}")
        blink(1, PHASE_STACK_INTERVAL)
        time.sleep(0.1)


def phase_edge_stack():
    log("Starting Edge AI stack...")
    log("  edge-impulse-runner :8080")
    blink(1, PHASE_STACK_INTERVAL)
    time.sleep(0.1)


def phase_api_ready():
    log("Starting p4n4-api :8000...")
    blink(1, PHASE_STACK_INTERVAL)


def phase_boot_complete():
    log("All services healthy. Platform ready.")
    burst(PHASE_READY_PULSES, 0.1, 0.1)
    time.sleep(0.2)
    led_on()


# --- Entry point ---

def main():
    setup_gpio()
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

        log("Press Ctrl+C to shut down.")
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[p4n4] Shutdown signal received.")
    finally:
        led_off()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
