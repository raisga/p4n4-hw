"""Test setup: a fake RPi.GPIO, so the scripts import and run without a Raspberry Pi.

It's installed when pytest loads this file, before any test module imports a script.
p4n4-emu's gpio_stub is the faithful stand-in for running the scripts by hand; this
fake only records what the scripts do.
"""

import http.server
import json
import socket
import sys
import threading
import time
import types

import pytest


class FakeGPIO(types.ModuleType):
    BCM, BOARD = 11, 10
    OUT, IN = 0, 1
    HIGH, LOW = 1, 0
    PUD_OFF, PUD_DOWN, PUD_UP = 20, 21, 22
    RISING, FALLING, BOTH = 31, 32, 33

    def __init__(self):
        super().__init__("RPi.GPIO", "Fake RPi.GPIO for the p4n4-hw tests")
        self.reset()

    def reset(self):
        self.mode = None
        self.levels = {}     # channel → level
        self.writes = []     # (channel, level) for every output() call
        self.callbacks = {}  # channel → add_event_detect callback
        self.setup_error = None

    def setmode(self, mode):
        self.mode = mode

    def setwarnings(self, flag):
        pass

    def setup(self, channel, direction, pull_up_down=PUD_OFF, initial=None):
        if self.setup_error is not None:
            raise self.setup_error
        if direction == self.IN:
            self.levels[channel] = self.HIGH if pull_up_down == self.PUD_UP else self.LOW
        else:
            self.levels[channel] = self.LOW if initial is None else initial

    def output(self, channel, state):
        level = self.HIGH if state else self.LOW
        self.levels[channel] = level
        self.writes.append((channel, level))

    def input(self, channel):
        return self.levels.get(channel, self.LOW)

    def add_event_detect(self, channel, edge, callback=None, bouncetime=None):
        self.callbacks[channel] = callback

    def cleanup(self, channel=None):
        pass


_gpio = FakeGPIO()
_rpi = types.ModuleType("RPi")
_rpi.__path__ = []  # a package, so `import RPi.GPIO` finds the fake in sys.modules
_rpi.GPIO = _gpio
sys.modules["RPi"] = _rpi
sys.modules["RPi.GPIO"] = _gpio


@pytest.fixture
def gpio():
    """The fake RPi.GPIO, cleared."""
    _gpio.reset()
    yield _gpio
    _gpio.reset()


@pytest.fixture
def sleeps(monkeypatch):
    """time.sleep returns at once; the list holds every requested delay."""
    delays = []
    monkeypatch.setattr(time, "sleep", delays.append)
    return delays


@pytest.fixture
def open_port():
    """A port on 127.0.0.1 that accepts connections."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        yield server.getsockname()[1]


@pytest.fixture
def closed_port():
    """A port on 127.0.0.1 that refuses connections."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
    return port


@pytest.fixture
def api_server():
    """Starts a stand-in for p4n4-api: serve(status, body) → its base URL. body is
    JSON-encoded unless it's bytes; every path answers the same."""
    servers = []

    def serve(status, body):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()
