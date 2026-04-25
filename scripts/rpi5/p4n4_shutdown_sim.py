#!/usr/bin/env python3
# Simulates the p4n4 platform graceful-shutdown sequence on a Raspberry Pi 5 using an LED on GPIO pin 17.
# Phases are the reverse of boot: API → Edge AI → GenAI → IoT → network bridge → kernel → power-off.

import RPi.GPIO as GPIO
import time

LED_PIN = 17  # BCM pin number

# Phase timing constants (seconds)
PHASE_STOP_INTERVAL    = 0.6   # slow blink per service being stopped
PHASE_NETWORK_INTERVAL = 0.25  # quick burst during bridge teardown
PHASE_KERNEL_INTERVAL  = 0.3   # medium blink during kernel shutdown
PHASE_POWEROFF_PULSES  = 5     # final fade-out pulses before LED goes dark


# --- GPIO helpers ---

def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(LED_PIN, GPIO.OUT)
    GPIO.output(LED_PIN, GPIO.HIGH)  # LED on at start — platform is still running


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


def burst(pulses, on_time, off_time):
    for _ in range(pulses):
        led_on()
        time.sleep(on_time)
        led_off()
        time.sleep(off_time)


def fade_out(pulses):
    """Simulate a fade by gradually lengthening the off-time between pulses."""
    on_time = 0.1
    for i in range(pulses):
        led_on()
        time.sleep(on_time)
        led_off()
        time.sleep(on_time * (i + 1) * 0.8)


# --- Shutdown phases ---

def phase_stop_api():
    """p4n4 REST API gateway — first to stop, stops accepting new requests."""
    print("[p4n4] Stopping p4n4-api :8000...")
    blink(count=1, interval=PHASE_STOP_INTERVAL)


def phase_stop_edge_stack():
    """Edge AI stack — Edge Impulse runner."""
    print("[p4n4] Stopping Edge AI stack...")
    services = [
        "edge-impulse-runner :8080",
    ]
    for service in services:
        print(f"[p4n4]   {service}")
        blink(count=1, interval=PHASE_STOP_INTERVAL)
        time.sleep(0.1)


def phase_stop_ai_stack():
    """GenAI stack — n8n, Letta, Ollama (reverse start order)."""
    print("[p4n4] Stopping GenAI stack...")
    services = [
        "n8n         :5678",
        "letta       :8283",
        "ollama      :11434",
    ]
    for service in services:
        print(f"[p4n4]   {service}")
        blink(count=1, interval=PHASE_STOP_INTERVAL)
        time.sleep(0.1)


def phase_stop_iot_stack():
    """MING stack — Grafana, Node-RED, InfluxDB, Mosquitto (reverse start order)."""
    print("[p4n4] Stopping IoT stack (MING)...")
    services = [
        "grafana     :3000",
        "node-red    :1880",
        "influxdb    :8086",
        "mosquitto   :1883",
    ]
    for service in services:
        print(f"[p4n4]   {service}")
        blink(count=1, interval=PHASE_STOP_INTERVAL)
        time.sleep(0.1)


def phase_teardown_network_bridge():
    """Remove the p4n4-net Docker bridge."""
    print("[p4n4] Tearing down p4n4-net bridge...")
    for _ in range(3):
        burst(pulses=4, on_time=PHASE_NETWORK_INTERVAL, off_time=0.1)
        time.sleep(0.3)
    print("[p4n4] p4n4-net removed.")


def phase_stop_system_services():
    """Docker and low-level system services."""
    services = [
        "docker",
        "gpio-daemon",
        "spi",
        "i2c",
        "udev",
        "syslog",
    ]
    for service in services:
        print(f"[p4n4] Stopping: {service}")
        blink(count=1, interval=PHASE_STOP_INTERVAL)
        time.sleep(0.1)


def phase_kernel_shutdown():
    """Kernel unmounting filesystems and releasing resources."""
    print("[p4n4] Unmounting filesystems...")
    blink(count=3, interval=PHASE_KERNEL_INTERVAL)
    print("[p4n4] Syncing storage...")
    blink(count=2, interval=PHASE_KERNEL_INTERVAL)


def phase_power_off():
    """All services stopped — LED fades out to signal power-off."""
    print("[p4n4] Platform halted. Powering off.")
    fade_out(PHASE_POWEROFF_PULSES)
    led_off()


# --- Entry point ---

def main():
    setup()
    print("[p4n4] Graceful shutdown initiated. Ctrl+C to abort.")
    try:
        phase_stop_api()
        phase_stop_edge_stack()
        phase_stop_ai_stack()
        phase_stop_iot_stack()
        phase_teardown_network_bridge()
        phase_stop_system_services()
        phase_kernel_shutdown()
        phase_power_off()
        print("[p4n4] Shutdown complete.")

    except KeyboardInterrupt:
        print("\n[p4n4] Shutdown aborted.")
    finally:
        led_off()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
