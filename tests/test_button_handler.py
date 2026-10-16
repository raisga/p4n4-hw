import subprocess
import threading
import time

import pytest

import p4n4_button_handler as button
import p4n4_common as common


@pytest.fixture
def actions(monkeypatch):
    """Replaces the three actions; returns {name: Event set when it runs}."""
    fired = {name: threading.Event() for name in ("report", "restart", "shutdown")}
    monkeypatch.setattr(button, "action_health_report", fired["report"].set)
    monkeypatch.setattr(button, "action_restart_services", fired["restart"].set)
    monkeypatch.setattr(button, "action_shutdown", fired["shutdown"].set)
    monkeypatch.setattr(button, "DOUBLE_PRESS_GAP", 0.05)
    monkeypatch.setattr(button, "LONG_PRESS_SECS", 0.1)
    return fired


def _only(fired, name):
    assert fired[name].wait(2), f"{name} didn't run"
    time.sleep(0.1)  # past the double-press gap: nothing else may fire
    assert [n for n, event in fired.items() if event.is_set()] == [name]


def test_single_press(actions):
    handler = button.ButtonHandler()
    handler.on_press()
    handler.on_release()
    _only(actions, "report")


def test_double_press(actions):
    handler = button.ButtonHandler()
    for _ in range(2):
        handler.on_press()
        handler.on_release()
    _only(actions, "restart")


def test_callbacks_replace_the_actions(actions):
    ran = threading.Event()
    handler = button.ButtonHandler(on_single=ran.set)
    handler.on_press()
    handler.on_release()
    assert ran.wait(2)
    time.sleep(0.1)
    assert not any(event.is_set() for event in actions.values())


def test_long_press(actions):
    handler = button.ButtonHandler()
    handler.on_press()
    time.sleep(0.15)
    handler.on_release()
    _only(actions, "shutdown")


def test_gpio_callback_reads_the_level(actions, gpio, monkeypatch):
    monkeypatch.setattr(button, "_handler", button.ButtonHandler())  # with the stand-ins
    gpio.levels[button.BUTTON_PIN] = gpio.LOW  # pressed: pulled to GND
    button._gpio_callback(button.BUTTON_PIN)
    gpio.levels[button.BUTTON_PIN] = gpio.HIGH
    button._gpio_callback(button.BUTTON_PIN)
    _only(actions, "report")


def _fake_run(outcomes, calls):
    def run(cmd, **kwargs):
        calls.append(cmd)
        outcome = outcomes.get(cmd[-1], (0, ""))
        if isinstance(outcome, BaseException):
            raise outcome
        returncode, stderr = outcome
        return subprocess.CompletedProcess(cmd, returncode, "", stderr)
    return run


def test_restart_restarts_every_container_in_order(monkeypatch, gpio, sleeps, capsys):
    calls = []
    monkeypatch.setattr(common.subprocess, "run", _fake_run({}, calls))
    button.action_restart_services()
    assert calls == [["docker", "restart", name] for name in common.DOCKER_SERVICES]
    assert "Restart complete." in capsys.readouterr().out


def test_restart_skips_missing_and_reports_failures(monkeypatch, gpio, sleeps, capsys):
    calls = []
    failures = []
    monkeypatch.setattr(common.subprocess, "run", _fake_run({
        "p4n4-letta": (1, "Error response from daemon: No such container: p4n4-letta"),
        "p4n4-n8n": (1, "permission denied"),
        "p4n4-ollama": subprocess.TimeoutExpired(["docker"], 60),
    }, calls))
    monkeypatch.setattr(button, "feedback_failure", lambda: failures.append(True))
    button.action_restart_services()
    out = capsys.readouterr().out
    assert "p4n4-letta: not on this host, skipped" in out
    assert "Restart failed for: p4n4-ollama, p4n4-n8n" in out
    assert failures == [True]


def test_restart_without_docker(monkeypatch, gpio, sleeps, capsys):
    monkeypatch.setattr(common.subprocess, "run", _fake_run(
        dict.fromkeys(common.DOCKER_SERVICES, FileNotFoundError("docker")), []
    ))
    button.action_restart_services()
    assert "Restart failed for: p4n4-mqtt" in capsys.readouterr().out


def test_shutdown_failure_explains_sudo(monkeypatch, gpio, sleeps, capsys):
    calls = []
    failures = []
    monkeypatch.setattr(common.subprocess, "run", _fake_run(
        {"now": (1, "sudo: a password is required")}, calls
    ))
    monkeypatch.setattr(button, "feedback_failure", lambda: failures.append(True))
    button.action_shutdown()
    assert calls == [["sudo", "-n", "shutdown", "-h", "now"]]
    out = capsys.readouterr().out
    assert "Shutdown failed: sudo: a password is required" in out
    assert "passwordless sudo" in out
    assert failures == [True]
