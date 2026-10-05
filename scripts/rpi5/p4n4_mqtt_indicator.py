#!/usr/bin/env python3
# Reflects live MQTT traffic on the p4n4 platform via the GPIO LED on pin 17.
# A short pulse fires for each arriving message; alert topics trigger a rapid burst.
# Requires: paho-mqtt 2.0 or later  (pip install "paho-mqtt>=2")

import argparse
import os
import sys
import threading
import time
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
from p4n4_common import setup_gpio, led_off, blink, log

if not hasattr(mqtt, "CallbackAPIVersion"):
    sys.exit('[p4n4] Needs paho-mqtt 2.0 or later: pip install "paho-mqtt>=2"')

BROKER_HOST = "localhost"
BROKER_PORT = 1883
KEEPALIVE   = 60

# Topics the indicator subscribes to: the ones the platform publishes on.
# Each entry: (topic_filter, alert); alert=True fires a rapid burst instead of
# a single pulse.
TOPICS = [
    ("sensors/#",   False),   # readings: sensors/<device-id>/<measurement>
    ("inference/#", False),   # edge results: inference/<device-id>/result
    ("devices/#",   False),   # devices/<device-id>/register and /status
    ("alerts/#",    True),    # alerts/<device-id>/critical, alerts/escalated
]

# LED timing (seconds)
PULSE_ON      = 0.05
PULSE_OFF     = 0.05
ALERT_ON      = 0.08
ALERT_OFF     = 0.05
ALERT_BURSTS  = 5
IDLE_HEARTBEAT_INTERVAL = 8.0


def pulse():
    blink(1, PULSE_ON, PULSE_OFF)


def alert_burst():
    blink(ALERT_BURSTS, ALERT_ON, ALERT_OFF)


# --- Shared state ---

_lock            = threading.Lock()
_pending_alert   = False
_pending_pulse   = False
_last_message_ts = 0.0


def _mark_message(alert: bool):
    global _pending_alert, _pending_pulse, _last_message_ts
    with _lock:
        if alert:
            _pending_alert = True
        else:
            _pending_pulse = True
        _last_message_ts = time.monotonic()


def _is_alert_topic(topic: str) -> bool:
    return any(alert and mqtt.topic_matches_sub(f, topic) for f, alert in TOPICS)


# --- MQTT callbacks (paho's VERSION2 API; userdata is the broker's "host:port") ---

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        log(f"MQTT refused: {reason_code} ({userdata})")
        return
    log(f"MQTT connected ({userdata})")
    for topic, _ in TOPICS:
        client.subscribe(topic)
        log(f"  subscribed → {topic}")


def on_disconnect(client, userdata, flags, reason_code, properties):
    log(f"MQTT disconnected ({reason_code}), reconnecting...")


def on_message(client, userdata, msg):
    alert = _is_alert_topic(msg.topic)
    _mark_message(alert)
    log(f"[{'ALERT' if alert else 'MSG'}] {msg.topic}  ({len(msg.payload)}B)")


# --- LED loop (runs in main thread) ---

def led_loop(stop_event: threading.Event):
    global _pending_alert, _pending_pulse
    last_heartbeat = time.monotonic()

    while not stop_event.is_set():
        with _lock:
            do_alert = _pending_alert
            do_pulse = _pending_pulse
            _pending_alert = False
            _pending_pulse = False

        if do_alert:
            alert_burst()
        elif do_pulse:
            pulse()
        else:
            now = time.monotonic()
            if now - last_heartbeat >= IDLE_HEARTBEAT_INTERVAL:
                pulse()
                last_heartbeat = now
            else:
                time.sleep(0.01)


# --- Entry point ---

def parse_args():
    p = argparse.ArgumentParser(description="p4n4 MQTT LED activity indicator")
    p.add_argument("--host", default=BROKER_HOST, help="MQTT broker host")
    p.add_argument("--port", type=int, default=BROKER_PORT, help="MQTT broker port")
    p.add_argument(
        "--username",
        default=os.environ.get("MQTT_USER", ""),
        help="MQTT username (default: $MQTT_USER)",
    )
    p.add_argument(
        "--password",
        default=os.environ.get("MQTT_PASSWORD", ""),
        help="MQTT password (default: $MQTT_PASSWORD; prefer it over the option, "
        "which other users can see in the process list)",
    )
    return p.parse_args()


def main():
    args = parse_args()
    setup_gpio()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="p4n4-mqtt-indicator",
        userdata=f"{args.host}:{args.port}",
    )
    if args.username:
        client.username_pw_set(args.username, args.password or None)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    log(f"Connecting to {args.host}:{args.port}...")
    # connect_async: the network loop keeps retrying, so the indicator can start
    # before the broker does (at boot)
    client.connect_async(args.host, args.port, keepalive=KEEPALIVE)
    client.loop_start()

    stop_event = threading.Event()
    log("MQTT indicator running. Ctrl+C to stop.")
    try:
        led_loop(stop_event)
    except KeyboardInterrupt:
        print("\n[p4n4] Stopping.")
    finally:
        stop_event.set()
        client.loop_stop()
        client.disconnect()
        led_off()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
