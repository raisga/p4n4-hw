import json
import threading
import time
import types

import pytest

import p4n4_common as common
import p4n4_hwd as hwd

# --- Node id ---


def test_node_id_defaults_to_the_hostname(monkeypatch):
    monkeypatch.setattr(hwd.socket, "gethostname", lambda: "pi-greenhouse")
    assert hwd.load_node_id({}) == "pi-greenhouse"
    assert hwd.load_node_id({"P4N4_NODE_ID": " pi-lab "}) == "pi-lab"


@pytest.mark.parametrize("node", ["pi/lab", "pi+", "#"])
def test_node_id_must_be_one_topic_level(node):
    with pytest.raises(SystemExit, match="P4N4_NODE_ID"):
        hwd.load_node_id({"P4N4_NODE_ID": node})


# --- LED arbiter ---


def test_led_is_dark_until_the_first_check():
    led = hwd.Led()
    assert led.take(0.0) == (None, None)


def test_led_heartbeat_waits_its_pause():
    led = hwd.Led()
    led.set_health(0, False)
    assert led.take(0.0) == (hwd.HEARTBEAT, hwd.HEARTBEAT_PAUSE)
    led._due = 10.0  # what run() sets after playing it
    assert led.take(7.0) == (None, 3.0)


def test_led_warns_once_per_service_down():
    led = hwd.Led()
    led.set_health(2, False)
    pattern, rest = led.take(0.0)
    assert len(pattern) == 2 and rest == hwd.WARN_INTERVAL


def test_led_new_health_shows_at_once():
    led = hwd.Led()
    led.set_health(0, False)
    led._due = 10.0
    led.set_health(1, True)
    assert led.take(5.0) == (hwd.ALERT, hwd.ALERT_PAUSE)


def test_led_activity_plays_in_the_heartbeat_pause():
    led = hwd.Led()
    led.set_health(0, False)
    led._due = 10.0
    led.activity(alert=False)
    led.activity(alert=False)  # coalesced
    assert led.take(5.0) == (hwd.PULSE, None)
    assert led.take(5.0) == (None, 5.0)


def test_led_alert_traffic_wins_over_pulses():
    led = hwd.Led()
    led.activity(alert=True)
    led.activity(alert=False)
    assert led.take(0.0) == (hwd.BURST, None)


def test_led_critical_drops_activity():
    led = hwd.Led()
    led.set_health(1, True)
    led.activity(alert=True)
    assert led.take(0.0) == (hwd.ALERT, hwd.ALERT_PAUSE)
    led._due = 10.0
    assert led.take(1.0) == (None, 9.0)


def test_led_feedback_first_and_in_order():
    led = hwd.Led()
    led.set_health(1, True)
    led.activity(alert=False)
    led.feedback(hwd.RESTART)
    led.feedback(hwd.FAILURE)
    assert led.take(0.0) == (hwd.RESTART, None)
    assert led.take(0.0) == (hwd.FAILURE, None)
    assert led.take(0.0) == (hwd.ALERT, hwd.ALERT_PAUSE)


def test_led_run_plays_and_stops(gpio):
    led = hwd.Led()
    led.feedback(((0.001, 0.001),) * 2)
    stop = threading.Event()
    thread = threading.Thread(target=led.run, args=(stop,))
    thread.start()
    deadline = time.monotonic() + 2
    while len(gpio.writes) < 4 and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    thread.join(2)
    assert not thread.is_alive()
    assert gpio.writes[:4] == [(17, 1), (17, 0)] * 2
    assert gpio.writes[-1] == (17, 0)


# --- Daemon ---


class FakeClient:
    def __init__(self):
        self.published = []  # (topic, payload dict, retain)
        self.subscribed = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, json.loads(payload), retain))
        return types.SimpleNamespace(wait_for_publish=lambda timeout=None: None)

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def topics(self):
        return [topic for topic, _, _ in self.published]


@pytest.fixture
def daemon(monkeypatch):
    monkeypatch.setattr(hwd, "TICK", 0.05)
    return hwd.Daemon(FakeClient(), hwd.Led(), "pi-lab", services=[], api_url=None)


def _results(monkeypatch, *rows):
    """check_services returns these rows: (label, up, detail)."""
    results = [(label, 1, up, label == "influxdb", detail) for label, up, detail in rows]
    n_down = sum(not up for _, up, _ in rows)
    critical = any(not up and label == "influxdb" for label, up, _ in rows)
    monkeypatch.setattr(hwd, "check_services", lambda *a: (results, n_down, critical))


def test_health_published_on_change_only(daemon, monkeypatch, capsys):
    _results(monkeypatch, ("mosquitto", True, None), ("influxdb", False, "starting"))
    daemon.check_health()
    daemon.check_health()
    assert daemon.client.topics() == ["status/pi-lab/health"]
    topic, payload, retain = daemon.client.published[0]
    assert retain
    assert payload["state"] == "critical"
    assert payload["down"] == ["influxdb"]
    assert payload["services"] == {
        "mosquitto": {"up": True},
        "influxdb": {"up": False, "detail": "starting"},
    }
    assert payload["ts"].endswith("Z")
    assert capsys.readouterr().out.count("Health report") == 1  # reported on change only
    assert daemon.led.take(0.0) == (hwd.ALERT, hwd.ALERT_PAUSE)

    _results(monkeypatch, ("mosquitto", True, None), ("influxdb", True, None))
    daemon.check_health()
    assert daemon.client.published[-1][1]["state"] == "ok"


def test_single_press_publishes_and_reports(daemon, monkeypatch, capsys):
    _results(monkeypatch, ("mosquitto", True, None))
    daemon.check_health()
    capsys.readouterr()
    daemon.on_single()
    assert daemon.client.published[-1] == (
        "sensors/pi-lab/button", {"value": 1, "press": "single"}, False
    )
    assert daemon.led.take(0.0) == (hwd.SINGLE, None)
    assert daemon._check_now.is_set()
    daemon.check_health()
    assert "Health report" in capsys.readouterr().out  # unchanged, but asked for


def test_double_press_restarts(daemon, monkeypatch):
    monkeypatch.setattr(hwd, "restart_containers", lambda: ["p4n4-n8n"])
    daemon.on_double()
    assert daemon.client.published[-1][1] == {"value": 1, "press": "double"}
    assert daemon.led.take(0.0) == (hwd.RESTART, None)
    assert daemon.led.take(0.0) == (hwd.FAILURE, None)


def test_long_press_counts_down_and_shuts_down(daemon, monkeypatch):
    calls = []
    monkeypatch.setattr(hwd, "request_shutdown", lambda: calls.append(True))
    daemon.on_long()
    assert calls == [True]
    patterns = [daemon.led.take(0.0)[0] for _ in range(4)]
    assert patterns == [hwd.COUNTDOWN] * 3 + [hwd.FADE]


def test_long_press_reports_a_failed_shutdown(daemon, monkeypatch, capsys):
    monkeypatch.setattr(hwd, "request_shutdown", lambda: "sudo: a password is required")
    daemon.on_long()
    assert "Shutdown failed: sudo: a password is required" in capsys.readouterr().out
    assert [daemon.led.take(0.0)[0] for _ in range(5)][-1] == hwd.FAILURE


def test_press_during_countdown_cancels(daemon, monkeypatch, gpio):
    calls = []
    monkeypatch.setattr(hwd, "request_shutdown", lambda: calls.append(True))
    monkeypatch.setattr(hwd, "TICK", 1.0)
    pressed = []
    monkeypatch.setattr(daemon.buttons, "on_press", lambda: pressed.append("press"))
    monkeypatch.setattr(daemon.buttons, "on_release", lambda: pressed.append("release"))
    thread = threading.Thread(target=daemon.on_long)
    thread.start()
    assert _wait(daemon._countdown.is_set)
    gpio.levels[hwd.BUTTON_PIN] = gpio.LOW
    daemon.on_edge(hwd.BUTTON_PIN)
    gpio.levels[hwd.BUTTON_PIN] = gpio.HIGH
    daemon.on_edge(hwd.BUTTON_PIN)
    thread.join(2)
    assert calls == []
    assert pressed == []  # the cancelling press isn't a press of its own
    daemon.on_edge(hwd.BUTTON_PIN)  # next release goes to the handler again
    assert pressed == ["release"]
    assert [daemon.led.take(0.0)[0] for _ in range(2)] == [hwd.COUNTDOWN, hwd.SINGLE]


def _wait(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def test_connect_publishes_online_and_the_last_health(daemon, monkeypatch):
    _results(monkeypatch, ("mosquitto", True, None))
    daemon.check_health()
    daemon.client.published.clear()
    ok = types.SimpleNamespace(is_failure=False)
    daemon.on_connect(daemon.client, "localhost:1883", None, ok, None)
    assert daemon.client.published[0] == ("status/pi-lab/online", {"online": True}, True)
    assert daemon.client.published[1][0] == "status/pi-lab/health"
    assert daemon.client.subscribed == [topic for topic, _ in hwd.TOPICS]


def test_refused_connection_publishes_nothing(daemon, capsys):
    refused = types.SimpleNamespace(is_failure=True, __str__=lambda self: "Not authorized")
    daemon.on_connect(daemon.client, "localhost:1883", None, refused, None)
    assert daemon.client.published == []
    assert "MQTT refused" in capsys.readouterr().out


def test_messages_light_the_led(daemon):
    daemon.on_message(None, None, types.SimpleNamespace(topic="alerts/esp32-01/critical"))
    assert daemon.led.take(0.0) == (hwd.BURST, None)


def test_go_offline(daemon):
    daemon.go_offline()
    assert daemon.client.published == [("status/pi-lab/online", {"online": False}, True)]


def test_disconnect_logged_unless_stopping(daemon, capsys):
    daemon.on_disconnect(None, "localhost:1883", None, "Unspecified error", None)
    assert "reconnecting" in capsys.readouterr().out
    daemon.go_offline()
    daemon.on_disconnect(None, "localhost:1883", None, "Normal disconnection", None)
    assert "reconnecting" not in capsys.readouterr().out


def test_make_client_sets_the_will_and_login(monkeypatch):
    calls = {}

    class Client:
        def __init__(self, api, client_id, userdata):
            calls["init"] = (api, client_id, userdata)

        def username_pw_set(self, user, password):
            calls["login"] = (user, password)

        def will_set(self, topic, payload, qos, retain):
            calls["will"] = (topic, json.loads(payload), qos, retain)

    monkeypatch.setattr(hwd.mqtt, "Client", Client)
    hwd.make_client("pi-lab", "localhost", 1883, {"MQTT_USER": "hwd", "MQTT_PASSWORD": "pw"})
    assert calls["init"][1:] == ("p4n4-hwd-pi-lab", "localhost:1883")
    assert calls["login"] == ("hwd", "pw")
    assert calls["will"] == ("status/pi-lab/online", {"online": False}, 1, True)


def test_health_state():
    assert common.health_state(0, False) == "ok"
    assert common.health_state(2, False) == "degraded"
    assert common.health_state(1, True) == "critical"
