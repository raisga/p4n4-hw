import pytest

import p4n4_common as common

ALL_LABELS = [label for label, _ in common.SERVICE_PORTS]


# --- Configuration ---

def test_load_services_defaults():
    services = common.load_services({})
    assert [s[0] for s in services] == ALL_LABELS
    assert {s[1] for s in services} == {"localhost"}
    assert {s[0] for s in services if s[3]} == {"mosquitto", "influxdb"}
    assert ("p4n4-dashboard", "localhost", 8088, False) in services


def test_load_services_host_and_ports():
    services = common.load_services(
        {"P4N4_HOST": "pi.local", "P4N4_PORTS": "grafana=3001, ollama = 11435"}
    )
    by_label = {s[0]: s for s in services}
    assert by_label["grafana"][1:3] == ("pi.local", 3001)
    assert by_label["ollama"][2] == 11435
    assert by_label["mosquitto"][2] == 1883


def test_load_services_selection_keeps_catalogue_order():
    services = common.load_services({"P4N4_SERVICES": "grafana,mosquitto"})
    assert [s[0] for s in services] == ["mosquitto", "grafana"]


def test_load_services_critical_override():
    services = common.load_services({"P4N4_CRITICAL_SERVICES": "node-red"})
    assert [s[0] for s in services if s[3]] == ["node-red"]


@pytest.mark.parametrize(
    "entry", ["grafana", "grafana=", "grafana=abc", "grafna=3000", "grafana=0", "grafana=70000"]
)
def test_load_services_rejects_bad_ports(entry):
    with pytest.raises(SystemExit, match="P4N4_PORTS"):
        common.load_services({"P4N4_PORTS": entry})


@pytest.mark.parametrize("var", ["P4N4_SERVICES", "P4N4_CRITICAL_SERVICES"])
def test_load_services_rejects_unknown_labels(var):
    with pytest.raises(SystemExit, match=f"{var}: unknown service mosquito"):
        common.load_services({var: "mosquito"})


def test_load_api_url():
    assert common.load_api_url({}) == "http://localhost:8000"
    assert common.load_api_url({"P4N4_HOST": "pi.local", "P4N4_PORTS": "p4n4-api=9000"}) == (
        "http://pi.local:9000"
    )
    assert common.load_api_url({"P4N4_API_URL": "https://api.lan/"}) == "https://api.lan"
    assert common.load_api_url({"P4N4_API_URL": "OFF"}) is None


def test_docker_services_are_unique_and_start_with_the_broker():
    assert len(set(common.DOCKER_SERVICES)) == len(common.DOCKER_SERVICES)
    assert common.DOCKER_SERVICES[:2] == ["p4n4-mqtt", "p4n4-influxdb"]


# --- GPIO helpers ---

def test_setup_gpio(gpio):
    common.setup_gpio()
    assert gpio.mode == gpio.BCM
    assert gpio.writes == [(common.LED_PIN, gpio.LOW)]


def test_setup_gpio_explains_the_pi5(gpio):
    gpio.setup_error = RuntimeError("Cannot determine SOC peripheral base address")
    with pytest.raises(SystemExit, match="python3-rpi-lgpio"):
        common.setup_gpio()


def test_blink(gpio, sleeps):
    common.blink(2, 0.1, 0.2)
    assert gpio.writes == [(17, 1), (17, 0)] * 2
    assert sleeps == [0.1, 0.2] * 2


def test_blink_off_time_defaults_to_on_time(gpio, sleeps):
    common.blink(1, 0.3)
    assert sleeps == [0.3, 0.3]


def test_fade_out_lengthens_off_time(gpio, sleeps):
    common.fade_out(3, on_time=0.1, factor=1.0)
    assert sleeps == pytest.approx([0.1, 0.1, 0.1, 0.2, 0.1, 0.3])


def test_led_toggle(gpio):
    common.led_toggle()
    common.led_toggle()
    assert gpio.writes == [(17, 1), (17, 0)]


# --- Health probe ---

def test_probe(open_port, closed_port):
    assert common.probe("127.0.0.1", open_port)
    assert not common.probe("127.0.0.1", closed_port)


def test_fetch_ready_returns_checks(api_server):
    url = api_server(200, {"status": "ready", "checks": {"influxdb": {"ok": True}}})
    assert common.fetch_ready(url) == {"influxdb": {"ok": True}}


def test_fetch_ready_reads_the_503_body(api_server):
    checks = {"influxdb": {"ok": False, "detail": "starting"}}
    url = api_server(503, {"status": "unavailable", "checks": checks})
    assert common.fetch_ready(url) == checks


@pytest.mark.parametrize(
    ("status", "body"), [(404, {"error": {"code": "not_found"}}), (200, b"<html>"), (200, [])]
)
def test_fetch_ready_ignores_other_answers(api_server, status, body):
    assert common.fetch_ready(api_server(status, body)) is None


def test_fetch_ready_unreachable(closed_port):
    assert common.fetch_ready(f"http://127.0.0.1:{closed_port}", timeout=1) is None


def test_check_services_tcp_only(open_port, closed_port):
    services = [
        ("mosquitto", "127.0.0.1", open_port, True),
        ("grafana", "127.0.0.1", closed_port, False),
    ]
    results, n_down, critical_down = common.check_services(services, api_url=None)
    assert results == [
        ("mosquitto", open_port, True, True, None),
        ("grafana", closed_port, False, False, None),
    ]
    assert (n_down, critical_down) == (1, False)


def test_check_services_prefers_the_api(api_server, open_port, closed_port):
    url = api_server(503, {
        "status": "unavailable",
        "checks": {
            "influxdb": {"ok": False, "detail": "InfluxDB is starting"},
            "ollama": {"ok": True, "required": False},
            "mqtt": {"ok": False, "detail": "not started", "required": False},
        },
    })
    services = [
        ("mosquitto", "127.0.0.1", open_port, True),   # mqtt check ignored: TCP decides
        ("influxdb", "127.0.0.1", open_port, True),    # port open, but not ready
        ("ollama", "127.0.0.1", closed_port, False),   # host port closed, API reaches it
        ("grafana", "127.0.0.1", closed_port, False),  # no API check: TCP
        ("p4n4-api", "127.0.0.1", closed_port, False), # it answered
    ]
    results, n_down, critical_down = common.check_services(services, api_url=url)
    assert [(r[0], r[2], r[4]) for r in results] == [
        ("mosquitto", True, None),
        ("influxdb", False, "InfluxDB is starting"),
        ("ollama", True, None),
        ("grafana", False, None),
        ("p4n4-api", True, None),
    ]
    assert (n_down, critical_down) == (2, True)


def test_check_services_falls_back_when_the_api_is_down(closed_port, open_port):
    services = [
        ("influxdb", "127.0.0.1", open_port, True),
        ("p4n4-api", "127.0.0.1", closed_port, False),
    ]
    results, n_down, critical_down = common.check_services(
        services, api_url=f"http://127.0.0.1:{closed_port}"
    )
    assert [(r[0], r[2]) for r in results] == [("influxdb", True), ("p4n4-api", False)]
    assert (n_down, critical_down) == (1, False)


def test_print_report(capsys):
    common.print_report([
        ("mosquitto", 1883, True, True, None),
        ("influxdb", 8086, False, True, "InfluxDB is starting"),
        ("grafana", 3000, False, False, None),
    ])
    rows = [" ".join(line.split()) for line in capsys.readouterr().out.splitlines()]
    assert "mosquitto 1883 UP" in rows
    assert "influxdb 8086 DOWN [critical] (InfluxDB is starting)" in rows
    assert "grafana 3000 DOWN" in rows
