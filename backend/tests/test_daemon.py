import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import daemon
from app.main import create_app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def home(tmp_path: Path, monkeypatch):
    """A private data folder and port, and no developer .env: the app runs from an empty folder."""
    port = free_port()
    monkeypatch.setattr(daemon, "BACKEND", tmp_path)
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens there
    monkeypatch.setenv("PORT", str(port))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTO_TITLES", "false")
    yield daemon.where()
    daemon.stop(force=True, quiet=True)  # never leave a server behind


def test_where_reads_the_same_settings_as_the_app(home, tmp_path, monkeypatch):
    assert home.port == int(os.environ["PORT"]) and home.data_dir == tmp_path / "data"
    assert home.url == f"http://127.0.0.1:{home.port}/"
    monkeypatch.setenv("DATA_DIR", "relative-data")
    assert daemon.where().data_dir == tmp_path / "relative-data"  # relative to the backend folder


def test_start_status_stop_cycle(home, capsys):
    assert daemon.start(wait_s=60) == 0
    info = daemon.probe(home.port)
    assert info is not None and info["status"] == "degraded"  # LiteLLM is not reachable here
    assert daemon.read_pid(home.pid_file) is not None
    assert home.out_log.exists() and "starting" in home.err_log.read_text()
    capsys.readouterr()

    assert daemon.status() == 0
    shown = capsys.readouterr().out
    assert f"process {info['pid']}" in shown and "NOT reachable" in shown

    assert daemon.start(wait_s=60) == 0  # already running: nothing new is started
    assert "Already running" in capsys.readouterr().out
    assert daemon.probe(home.port)["pid"] == info["pid"]

    assert daemon.stop() == 0
    assert daemon.probe(home.port) is None
    assert not home.pid_file.exists()
    assert daemon.status() == 1
    capsys.readouterr()
    assert daemon.stop() == 0 and "not running" in capsys.readouterr().out


def test_restart_gives_a_new_process(home):
    assert daemon.start(wait_s=60) == 0
    first = daemon.probe(home.port)["pid"]
    assert daemon.start(restart=True, wait_s=60) == 0
    assert daemon.probe(home.port)["pid"] != first


def test_a_crash_at_startup_is_reported_with_the_log(home, monkeypatch, capsys):
    monkeypatch.delenv("LITELLM_API_KEY")  # the app refuses to start without its key
    assert daemon.start(wait_s=60) == 1
    err = capsys.readouterr().err
    assert "stopped right after starting" in err and "LITELLM_API_KEY" in err
    assert not home.pid_file.exists()


def test_a_busy_port_is_reported_and_left_alone(home, capsys):
    with socket.socket() as other:
        other.bind(("127.0.0.1", home.port))
        other.listen()
        assert daemon.start(wait_s=5) == 1
    assert "used by another program" in capsys.readouterr().err
    assert not home.pid_file.exists()


def test_stop_does_not_touch_a_process_that_is_not_known_to_be_the_app(home, capsys):
    # A Python process that is not answering as the app (a stand-in for a stuck app, or for an
    # unrelated program that now has the process id the file remembers).
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        home.data_dir.mkdir(parents=True)
        home.pid_file.write_text(str(sleeper.pid))
        assert daemon.stop() == 1
        assert "It was not touched" in capsys.readouterr().err
        assert sleeper.poll() is None and home.pid_file.exists()

        assert daemon.stop(force=True) == 0  # only now, on request, and because it is Python
        sleeper.wait(timeout=20)
        assert not home.pid_file.exists()
    finally:
        sleeper.kill()


def test_stop_cleans_up_a_pid_file_left_by_a_process_that_is_gone(home, capsys):
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    home.data_dir.mkdir(parents=True)
    home.pid_file.write_text(str(gone.pid))
    assert daemon.stop() == 0
    assert not home.pid_file.exists()
    assert "not running" in capsys.readouterr().out


def serve(payload: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_probe_only_accepts_this_apps_health_answer():
    app_like = serve(json.dumps({"pid": 1, "litellm": {}, "status": "ok"}).encode())
    other = serve(b'{"hello": 1}')
    not_json = serve(b"<html>")
    try:
        assert daemon.probe(app_like.server_port)["pid"] == 1
        assert daemon.probe(other.server_port) is None
        assert daemon.probe(not_json.server_port) is None
        assert daemon.probe(free_port(), timeout=0.5) is None  # nothing there
    finally:
        for server in (app_like, other, not_json):
            server.shutdown()


def test_logs_are_moved_aside_when_big_and_tailed(tmp_path: Path):
    log = tmp_path / "app.err.log"
    log.write_text("x" * 50)
    daemon.rotate(log, limit=10)
    assert not log.exists() and (tmp_path / "app.err.log.1").read_text() == "x" * 50
    log.write_text("small")
    daemon.rotate(log, limit=10)
    assert log.read_text() == "small"
    log.write_text("\n".join(f"line {i}" for i in range(100)))
    assert daemon.tail(log, 3) == "line 97\nline 98\nline 99"
    assert daemon.tail(tmp_path / "missing.log") == ""


def test_the_python_check_used_before_ending_a_stuck_process():
    assert daemon.is_python("python.exe") and daemon.is_python("python3.12")
    assert daemon.is_python("pythonw.exe")
    assert not daemon.is_python("chrome.exe") and not daemon.is_python(None)


def test_the_health_answer_names_the_process(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["pid"] == os.getpid()
