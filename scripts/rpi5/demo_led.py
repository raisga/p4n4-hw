#!/usr/bin/env python3
# Demo script to blink an LED on a Raspberry Pi 5 using GPIO pin 17.

import RPi.GPIO as GPIO
import time

LED_PIN = 17        # BCM pin number
BLINK_COUNT = 10    # number of blink cycles
BLINK_INTERVAL = 0.5  # seconds between on/off transitions


def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(LED_PIN, GPIO.OUT)


def led_on():
    GPIO.output(LED_PIN, GPIO.HIGH)


def led_off():
    GPIO.output(LED_PIN, GPIO.LOW)


def led_toggle():
    # Read current state and flip it
    GPIO.output(LED_PIN, not GPIO.input(LED_PIN))


def blink(count=BLINK_COUNT, interval=BLINK_INTERVAL):
    for i in range(count):
        print(f"Blink {i + 1}/{count} — ON")
        led_on()
        time.sleep(interval)
        print(f"Blink {i + 1}/{count} — OFF")
        led_off()
        time.sleep(interval)


def main():
    setup()
    try:
        blink()
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        # Ensure LED is off and GPIO is released on exit
        led_off()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
