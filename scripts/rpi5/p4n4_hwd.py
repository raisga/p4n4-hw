#!/usr/bin/env python3
# p4n4 hardware daemon: one process owns the status LED (GPIO 17) and the button (GPIO 27),
# checks service health, shows MQTT traffic, and publishes the node's status. Run it
# instead of the single-purpose scripts, which drive the same pins.
#
# LED, highest priority first: button feedback → critical alert → MQTT activity →
# degraded warning → heartbeat. The health patterns are the health monitor's, the
# activity pulses the MQTT indicator's.
#
# Button: single press → health report, double → restart the p4n4 containers, hold 3 s →
# shut down after a 3 s countdown (three long blinks) that another press cancels.
#
# MQTT (the spec's topic conventions; <node> is P4N4_NODE_ID, by default the hostname):
#   status/<node>/online   retained {"online": true|false}; the last will sets false
#   status/<node>/health   retained {"state": "ok"|"degraded"|"critical", ...}, on change
#   sensors/<node>/button  {"value": 1, "press": "single"|"double"|"long"} per press
#
# Configuration: p4n4_common's variables (P4N4_HOST, P4N4_PORTS, P4N4_SERVICES, …),
# P4N4_NODE_ID, and MQTT_USER / MQTT_PASSWORD for a broker that requires a login.

import json
import os
import signal
import socket
import threading
import time
from collections import deque
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO

from p4n4_button_handler import BUTTON_PIN, DEBOUNCE_MS, LONG_PRESS_SECS, ButtonHandler
from p4n4_common import (
    API_URL,
    LED_PIN,
    SERVICES,
    check_services,
    health_state,
    led_off,
    led_on,
    load_broker,
    log,
    print_report,
    request_shutdown,
    restart_containers,
    setup_gpio,
)
from p4n4_health_monitor import (
    ALERT_INTERVAL,
    ALERT_PAUSE,
    CHECK_INTERVAL,
    HEARTBEAT_OFF,
    HEARTBEAT_ON,
    HEARTBEAT_PAUSE,
    WARN_INTERVAL,
)
from p4n4_mqtt_indicator import (
    ALERT_BURSTS,
    ALERT_OFF,
    ALERT_ON,
    KEEPALIVE,
    PULSE_OFF,
    PULSE_ON,
    TOPICS,
    is_alert_topic,
)

SHUTDOWN_DELAY = 3     # countdown ticks before the long press powers off
TICK           = 1.0   # seconds per countdown tick

# LED patterns: (on, off) seconds per blink
HEARTBEAT = ((HEARTBEAT_ON, HEARTBEAT_OFF),) * 2
ALERT     = ((ALERT_INTERVAL, ALERT_INTERVAL),) * 6
PULSE     = ((PULSE_ON, PULSE_OFF),)
BURST     = ((ALERT_ON, ALERT_OFF),) * ALERT_BURSTS
SINGLE    = ((0.1, 0.3),)
RESTART   = ((0.08, 0.08),) * 3 + ((0.0, 0.3),)
FAILURE   = ((0.12, 0.12),) * 6 + ((0.0, 0.3),)
COUNTDOWN = ((0.5, 0.0),)
FADE      = tuple((0.1, 0.1 * (i + 1) * 0.7) for i in range(6))


def warn(n_down: int) -> tuple:
    return ((WARN_INTERVAL, WARN_INTERVAL),) * n_down


def load_node_id(env=os.environ) -> str:
    """P4N4_NODE_ID, or the hostname: one topic level, so no '/', '+' or '#'."""
    node = env.get("P4N4_NODE_ID", "").strip() or socket.gethostname()
    if not node or any(c in node for c in "/+#"):
        raise SystemExit(f"[p4n4] P4N4_NODE_ID: {node!r} can't be an MQTT topic level")
    return node


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- LED arbiter ---

class Led:
    """Owns the status LED and plays one pattern at a time, the most important one waiting.

    Button feedback plays in order, ahead of everything. The health pattern (alert,
    warning or heartbeat) repeats, with its pause, once the first check is in; MQTT
    activity plays in its pauses, except during a critical alert, which drops it.
    """

    def __init__(self):
        self._cond     = threading.Condition()
        self._feedback = deque()
        self._health   = None   # (n_down, critical_down) once checked
        self._activity = None   # "alert" or "pulse": traffic since the last pulse
        self._due      = 0.0    # when the health pattern plays again (monotonic)

    def feedback(self, pattern: tuple) -> None:
        with self._cond:
            self._feedback.append(pattern)
            self._cond.notify()

    def set_health(self, n_down: int, critical_down: bool) -> None:
        with self._cond:
            if self._health != (n_down, critical_down):
                self._health = (n_down, critical_down)
                self._due = 0.0  # show a new state at once
                self._cond.notify()

    def activity(self, alert: bool) -> None:
        with self._cond:
            self._activity = "alert" if alert or self._activity == "alert" else "pulse"
            self._cond.notify()

    def take(self, now: float) -> tuple:
        """What to play next: (pattern, rest), where rest is the health pattern's pause
        and None for the others; or (None, timeout) when nothing is due yet, timeout
        being None for "until something changes"."""
        with self._cond:
            if self._feedback:
                return self._feedback.popleft(), None
            critical = self._health is not None and self._health[1]
            if critical:
                self._activity = None
            if self._activity:
                pattern = BURST if self._activity == "alert" else PULSE
                self._activity = None
                return pattern, None
            if self._health is None:
                return None, None
            if now < self._due:
                return None, self._due - now
            n_down, _ = self._health
            if critical:
                return ALERT, ALERT_PAUSE
            if n_down:
                return warn(n_down), WARN_INTERVAL
            return HEARTBEAT, HEARTBEAT_PAUSE

    def run(self, stop: threading.Event) -> None:
        """Plays patterns until stop is set (checked at least every half second)."""
        while not stop.is_set():
            pattern, rest = self.take(time.monotonic())
            if pattern is None:
                with self._cond:
                    self._cond.wait(0.5 if rest is None else min(rest, 0.5))
                continue
            for on, off in pattern:
                if on:
                    led_on()
                    time.sleep(on)
                led_off()
                time.sleep(off)
            if rest is not None:
                with self._cond:
                    self._due = time.monotonic() + rest
        led_off()


# --- Daemon ---

class Daemon:
    """Health checks, button actions and MQTT status around one Led and one MQTT client."""

    def __init__(self, client, led: Led, node: str, services=SERVICES, api_url=API_URL):
        self.client   = client
        self.led      = led
        self.node     = node
        self.services = services
        self.api_url  = api_url
        self.buttons  = ButtonHandler(self.on_single, self.on_double, self.on_long)
        self._lock           = threading.Lock()
        self._health_payload = None   # last published status/<node>/health body
        self._results        = None   # last check's results, to report changes
        self._check_now      = threading.Event()
        self._report_next    = False
        self._restarting     = threading.Lock()
        self._shutting_down  = threading.Lock()
        self._cancel         = threading.Event()
        self._countdown      = threading.Event()
        self._swallow        = False  # the release of a press that cancelled a shutdown
        self._stopping       = False

    # --- Topics ---

    @property
    def online_topic(self) -> str:
        return f"status/{self.node}/online"

    @property
    def health_topic(self) -> str:
        return f"status/{self.node}/health"

    @property
    def button_topic(self) -> str:
        return f"sensors/{self.node}/button"

    # --- Health ---

    def check_health(self) -> None:
        results, n_down, critical_down = check_services(self.services, self.api_url)
        self.led.set_health(n_down, critical_down)
        with self._lock:
            report = self._report_next or results != self._results
            self._report_next = False
            self._results = results
        if report:  # on change, and on a single press: not every sweep into the journal
            print_report(results)
        payload = {
            "state": health_state(n_down, critical_down),
            "down": [label for label, _, up, _, _ in results if not up],
            "services": {
                label: {"up": up, **({"detail": detail} if detail else {})}
                for label, _, up, _, detail in results
            },
        }
        with self._lock:
            changed = payload != self._health_payload
            self._health_payload = payload
        if changed:
            self.publish(self.health_topic, {**payload, "ts": utc_now()}, retain=True)

    def health_loop(self, stop: threading.Event) -> None:
        """Checks at once, then every CHECK_INTERVAL seconds or when a press asks."""
        while not stop.is_set():
            try:
                self.check_health()
            except Exception as exc:  # keep the daemon (and its LED) alive
                log(f"Health check failed: {exc!r}")
            self._check_now.wait(CHECK_INTERVAL)
            self._check_now.clear()

    # --- Button ---

    def on_edge(self, channel) -> None:
        """GPIO callback for both edges of the button."""
        if GPIO.input(BUTTON_PIN) == GPIO.LOW:  # pressed: the button pulls the pin to GND
            if self._countdown.is_set():
                self._cancel.set()
                self._swallow = True
                return
            self.buttons.on_press()
        elif self._swallow:
            self._swallow = False
        else:
            self.buttons.on_release()

    def on_single(self) -> None:
        self.publish_press("single")
        self.led.feedback(SINGLE)
        with self._lock:
            self._report_next = True
        self._check_now.set()

    def on_double(self) -> None:
        self.publish_press("double")
        if not self._restarting.acquire(blocking=False):
            log("Already restarting the p4n4 containers.")
            return
        try:
            log("Restarting p4n4 containers...")
            self.led.feedback(RESTART)
            failed = restart_containers()
            if failed:
                log(f"Restart failed for: {', '.join(failed)}")
                self.led.feedback(FAILURE)
            else:
                log("Restart complete.")
        finally:
            self._restarting.release()
        self._check_now.set()

    def on_long(self) -> None:
        self.publish_press("long")
        if not self._shutting_down.acquire(blocking=False):
            return
        try:
            self._cancel.clear()
            self._countdown.set()
            log(f"Long press: shutting down in {SHUTDOWN_DELAY * TICK:.0f} s. "
                "Press the button to cancel.")
            for _ in range(SHUTDOWN_DELAY):
                self.led.feedback(COUNTDOWN)
                if self._cancel.wait(TICK):
                    log("Shutdown cancelled.")
                    self.led.feedback(SINGLE)
                    return
            self._countdown.clear()
            log("Shutting down.")
            self.led.feedback(FADE)
            error = request_shutdown()
            if error:
                log(f"Shutdown failed: {error}")
                log("  This user needs passwordless sudo for shutdown (see README).")
                self.led.feedback(FAILURE)
        finally:
            self._countdown.clear()
            self._shutting_down.release()

    # --- MQTT ---

    def publish(self, topic: str, payload: dict, retain: bool = False) -> None:
        self.client.publish(topic, json.dumps(payload), qos=1, retain=retain)

    def publish_press(self, press: str) -> None:
        log(f"Button: {press} press")
        self.publish(self.button_topic, {"value": 1, "press": press})

    def on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            log(f"MQTT refused: {reason_code} ({userdata})")
            return
        log(f"MQTT connected ({userdata}) as node {self.node!r}")
        self.publish(self.online_topic, {"online": True}, retain=True)
        with self._lock:
            payload = self._health_payload
        if payload is not None:  # anything published while disconnected may be lost
            self.publish(self.health_topic, {**payload, "ts": utc_now()}, retain=True)
        for topic, _ in TOPICS:
            client.subscribe(topic)

    def on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        if not self._stopping:
            log(f"MQTT disconnected ({reason_code}), reconnecting...")

    def on_message(self, client, userdata, msg) -> None:
        self.led.activity(is_alert_topic(msg.topic))

    def go_offline(self) -> None:
        """Publish online=false before a clean disconnect, which doesn't send the will."""
        self._stopping = True
        info = self.client.publish(
            self.online_topic, json.dumps({"online": False}), qos=1, retain=True
        )
        try:
            info.wait_for_publish(timeout=2)
        except (RuntimeError, ValueError):  # not connected: the will covers it
            pass


def make_client(node: str, host: str, port: int, env=os.environ) -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"p4n4-hwd-{node}",
        userdata=f"{host}:{port}",
    )
    user = env.get("MQTT_USER", "")
    if user:
        client.username_pw_set(user, env.get("MQTT_PASSWORD") or None)
    client.will_set(f"status/{node}/online", json.dumps({"online": False}), qos=1, retain=True)
    return client


# --- Entry point ---

def main():
    node = load_node_id()
    host, port = load_broker()
    setup_gpio()
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    led = Led()
    client = make_client(node, host, port)
    daemon = Daemon(client, led, node)
    client.on_connect    = daemon.on_connect
    client.on_disconnect = daemon.on_disconnect
    client.on_message    = daemon.on_message
    GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH, callback=daemon.on_edge, bouncetime=DEBOUNCE_MS)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda signum, frame: stop.set())  # systemctl stop

    log(f"p4n4-hwd for node {node!r}: LED on GPIO {LED_PIN}, button on GPIO {BUTTON_PIN}.")
    log(f"  Health: {len(SERVICES)} services every {CHECK_INTERVAL:.0f} s"
        + (f", p4n4-api's {API_URL}/ready first." if API_URL else ", TCP probes only."))
    log(f"  MQTT: {host}:{port}, publishing status/{node}/online, status/{node}/health "
        f"and sensors/{node}/button.")
    log(f"  Button: press → health report, double press → restart containers, "
        f"hold {LONG_PRESS_SECS:.0f} s → shutdown.")

    # connect_async: the network loop keeps retrying, so the daemon can start before the
    # broker does (at boot)
    client.connect_async(host, port, keepalive=KEEPALIVE)
    client.loop_start()
    threading.Thread(target=daemon.health_loop, args=(stop,), daemon=True).start()
    try:
        led.run(stop)
    except KeyboardInterrupt:
        print()
    finally:
        log("p4n4-hwd stopping.")
        stop.set()
        daemon.go_offline()
        client.loop_stop()
        client.disconnect()
        led_off()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
