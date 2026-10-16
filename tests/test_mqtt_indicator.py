import types

import pytest

import p4n4_mqtt_indicator as indicator


@pytest.mark.parametrize(
    ("topic", "alert"),
    [
        ("alerts/esp32-01/critical", True),
        ("alerts/escalated", True),
        ("sensors/esp32-01/temperature", False),
        ("inference/cam-door/result", False),
        ("devices/esp32-01/status", False),
        ("alertsx/esp32-01", False),
    ],
)
def test_alert_topics(topic, alert):
    assert indicator.is_alert_topic(topic) is alert


def _message(topic, payload):
    return types.SimpleNamespace(topic=topic, payload=payload)


def test_on_message_queues_led_feedback(monkeypatch, capsys):
    monkeypatch.setattr(indicator, "_pending_alert", False)
    monkeypatch.setattr(indicator, "_pending_pulse", False)
    indicator.on_message(None, None, _message("alerts/x/critical", b"{}"))
    assert indicator._pending_alert and not indicator._pending_pulse
    indicator.on_message(None, None, _message("sensors/x/t", b"21.5"))
    assert indicator._pending_pulse
    out = capsys.readouterr().out
    assert "[ALERT] alerts/x/critical  (2B)" in out
    assert "[MSG] sensors/x/t  (4B)" in out
