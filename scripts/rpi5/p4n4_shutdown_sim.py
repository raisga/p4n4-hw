#!/usr/bin/env python3
# Simulates the p4n4 platform graceful-shutdown sequence on a Raspberry Pi 5.
# Phases are the reverse of boot: API → Edge AI → GenAI → IoT → network bridge → kernel → power-off.

import time
import RPi.GPIO as GPIO
from p4n4_common import setup_gpio, led_off, blink, burst, fade_out, log

# Phase timing constants (seconds)
PHASE_STOP_INTERVAL    = 0.6
PHASE_NETWORK_INTERVAL = 0.25
PHASE_KERNEL_INTERVAL  = 0.3
PHASE_POWEROFF_PULSES  = 5


# --- Shutdown phases ---

def phase_stop_api():
    log("Stopping p4n4-api :8000...")
    blink(1, PHASE_STOP_INTERVAL)


def phase_stop_edge_stack():
    log("Stopping Edge AI stack...")
    log("  edge-impulse-runner :8080")
    blink(1, PHASE_STOP_INTERVAL)
    time.sleep(0.1)


def phase_stop_ai_stack():
    log("Stopping GenAI stack...")
    for service in ["n8n         :5678", "letta       :8283", "ollama      :11434"]:
        log(f"  {service}")
        blink(1, PHASE_STOP_INTERVAL)
        time.sleep(0.1)


def phase_stop_iot_stack():
    log("Stopping IoT stack (MING)...")
    for service in ["grafana     :3000", "node-red    :1880", "influxdb    :8086", "mosquitto   :1883"]:
        log(f"  {service}")
        blink(1, PHASE_STOP_INTERVAL)
        time.sleep(0.1)


def phase_teardown_network_bridge():
    log("Tearing down p4n4-net bridge...")
    for _ in range(3):
        burst(4, PHASE_NETWORK_INTERVAL, 0.1)
        time.sleep(0.3)
    log("p4n4-net removed.")


def phase_stop_system_services():
    for service in ["docker", "gpio-daemon", "spi", "i2c", "udev", "syslog"]:
        log(f"Stopping: {service}")
        blink(1, PHASE_STOP_INTERVAL)
        time.sleep(0.1)


def phase_kernel_shutdown():
    log("Unmounting filesystems...")
    blink(3, PHASE_KERNEL_INTERVAL)
    log("Syncing storage...")
    blink(2, PHASE_KERNEL_INTERVAL)


def phase_power_off():
    log("Platform halted. Powering off.")
    fade_out(PHASE_POWEROFF_PULSES)
    led_off()


# --- Entry point ---

def main():
    setup_gpio(initial_state=GPIO.HIGH)
    log("Graceful shutdown initiated. Ctrl+C to abort.")
    try:
        phase_stop_api()
        phase_stop_edge_stack()
        phase_stop_ai_stack()
        phase_stop_iot_stack()
        phase_teardown_network_bridge()
        phase_stop_system_services()
        phase_kernel_shutdown()
        phase_power_off()
        log("Shutdown complete.")

    except KeyboardInterrupt:
        print("\n[p4n4] Shutdown aborted.")
    finally:
        led_off()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
