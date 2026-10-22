"""Run the app in the background, without a terminal window.

    python -m app.daemon start [--restart]   start it (does nothing if it is already running)
    python -m app.daemon stop [--force]
    python -m app.daemon status
    python -m app.daemon open                start it if needed, then open the browser
    python -m app.daemon logs [-n 40]

The app is started as a separate process with no console. Its output goes to
``<data dir>/logs/app.out.log`` and ``app.err.log`` (the logging goes to the second one); each is
moved aside to ``.1`` at the next start once it is over 5 MB. The process id is kept in
``<data dir>/app.pid``.

Stopping is careful, because a process id left in a file can later belong to an unrelated program
(after a restart of the computer, for example). The app reports its own process id on
``/api/health``; that answer is trusted. Without an answer, a process is only ended on request
(``--force``), and only when it is a Python process.
"""

import argparse
import csv
import io
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings

BACKEND = Path(__file__).resolve().parents[1]
IS_WINDOWS = sys.platform == "win32"
LOG_LIMIT = 5 * 1024 * 1024


@dataclass(frozen=True)
class Where:
    port: int
    data_dir: Path

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def pid_file(self) -> Path:
        return self.data_dir / "app.pid"

    @property
    def logs(self) -> Path:
        return self.data_dir / "logs"

    @property
    def out_log(self) -> Path:
        return self.logs / "app.out.log"

    @property
    def err_log(self) -> Path:
        return self.logs / "app.err.log"


def where() -> Where:
    """Port and data folder, from the same settings the app uses (the key is not needed here)."""
    try:
        settings = Settings(_env_file=BACKEND / ".env", litellm_api_key="unused")  # type: ignore[call-arg]
        port, data_dir = settings.port, settings.data_dir
    except ValidationError:
        port, data_dir = 8000, Path("data")
    return Where(port, data_dir if data_dir.is_absolute() else BACKEND / data_dir)


# -- looking at the running app ------------------------------------------------------------------


def probe(port: int, timeout: float = 2.0) -> dict | None:
    """The app's /api/health answer, or None. Never goes through a web proxy."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
            data = json.load(response)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "pid" in data and "litellm" in data else None


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def image_name(pid: int) -> str | None:
    """Name of the program running as ``pid`` (lower case), or None when there is none."""
    if IS_WINDOWS:
        result = subprocess.run(  # noqa: S603
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        rows = list(csv.reader(io.StringIO(result.stdout)))
        if rows and len(rows[0]) >= 2 and rows[0][1].strip() == str(pid):
            return rows[0][0].lower()
        return None
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip().lower()
    except OSError:
        return None


def is_python(name: str | None) -> bool:
    return bool(name) and name.startswith(("python", "pythonw"))  # type: ignore[union-attr]


def kill(pid: int) -> None:
    """End a process and the processes it started."""
    if IS_WINDOWS:
        subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S607
            capture_output=True,
            check=False,
            timeout=30,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and image_name(pid) is not None:
        time.sleep(0.1)
    if image_name(pid) is not None:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# -- logs ----------------------------------------------------------------------------------------


def rotate(path: Path, limit: int = LOG_LIMIT) -> None:
    """Move a log that grew past ``limit`` aside (one old copy is kept)."""
    try:
        if path.stat().st_size > limit:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass


def tail(path: Path, lines: int = 20) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


# -- commands ------------------------------------------------------------------------------------


def start(restart: bool = False, wait_s: float = 45.0, quiet: bool = False) -> int:
    where_ = where()

    def say(text: str) -> None:
        if not quiet:
            print(text)

    if restart:
        stop(quiet=True)
    info = probe(where_.port)
    if info is not None:
        say(f"Already running (process {info['pid']}): {where_.url}")
        return 0
    if port_in_use(where_.port):
        print(
            f"Port {where_.port} is used by another program, so the app cannot start. "
            "Close that program or set PORT in backend\\.env.",
            file=sys.stderr,
        )
        return 1

    where_.logs.mkdir(parents=True, exist_ok=True)
    rotate(where_.out_log)
    rotate(where_.err_log)
    flags: dict = {}
    if IS_WINDOWS:
        flags["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        flags["start_new_session"] = True
    with where_.out_log.open("ab") as out, where_.err_log.open("ab") as err:
        err.write(f"\n--- starting {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode())
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "app"],
            cwd=BACKEND,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            close_fds=True,
            **flags,
        )
    where_.pid_file.write_text(str(process.pid), encoding="ascii")

    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            print(
                f"The app stopped right after starting (exit code {process.returncode}):",
                file=sys.stderr,
            )
            print(tail(where_.err_log, 15), file=sys.stderr)
            where_.pid_file.unlink(missing_ok=True)
            return 1
        info = probe(where_.port)
        if info is not None:
            say(f"Started (process {info['pid']}): {where_.url}")
            if info["status"] != "ok":
                say("Note: LiteLLM is not reachable or the model is not available yet; see Status.")
            return 0
        time.sleep(0.3)
    print(f"The app did not answer within {wait_s:.0f} s. Last log lines:", file=sys.stderr)
    print(tail(where_.err_log, 15), file=sys.stderr)
    return 1


def stop(force: bool = False, quiet: bool = False) -> int:
    where_ = where()

    def say(text: str) -> None:
        if not quiet:
            print(text)

    info = probe(where_.port)
    recorded = read_pid(where_.pid_file)
    if info is not None:
        kill(int(info["pid"]))  # the app named itself, so this is certain
    elif recorded is not None and image_name(recorded) is not None:
        if not (force and is_python(image_name(recorded))):
            print(
                f"The app is not answering, but process {recorded} ({image_name(recorded)}) "
                "exists. It was not touched. If it is the app and it is stuck, run stop with "
                "--force (only a Python process is ended).",
                file=sys.stderr,
            )
            return 1
        kill(recorded)
    else:
        where_.pid_file.unlink(missing_ok=True)
        say("The app is not running.")
        return 0

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and probe(where_.port, timeout=1.0) is not None:
        time.sleep(0.2)
    if probe(where_.port, timeout=1.0) is not None:
        print("The app is still answering after the stop request.", file=sys.stderr)
        return 1
    where_.pid_file.unlink(missing_ok=True)
    say("Stopped.")
    return 0


def status() -> int:
    where_ = where()
    info = probe(where_.port)
    if info is None:
        recorded = read_pid(where_.pid_file)
        if recorded is not None and image_name(recorded) is not None:
            print(
                f"Not answering on port {where_.port}, but process {recorded} exists "
                "(it may still be starting)."
            )
        else:
            print("Not running.")
        return 1
    litellm = info["litellm"]
    print(f"Running (process {info['pid']}), version {info['version']}: {where_.url}")
    print(
        f"LiteLLM: {'reachable' if litellm['reachable'] else 'NOT reachable'}"
        f" ({litellm['base_url']}); chat model available: {info['chat_model']['available']}"
    )
    print(f"Logs: {where_.logs}")
    return 0


def open_browser() -> int:
    code = start()
    if code == 0:
        webbrowser.open(where().url)
    return code


def logs(lines: int) -> int:
    where_ = where()
    text = tail(where_.err_log, lines)
    print(text if text else f"No log yet in {where_.logs}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.daemon", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_start = sub.add_parser("start", help="start the app in the background")
    p_start.add_argument("--restart", action="store_true", help="stop it first if it is running")
    p_start.add_argument(
        "--quiet", action="store_true", help="print nothing unless something is wrong"
    )
    p_stop = sub.add_parser("stop", help="stop the app")
    p_stop.add_argument("--force", action="store_true", help="also end a stuck Python process")
    sub.add_parser("status", help="is it running?")
    sub.add_parser("open", help="start it if needed and open the browser")
    p_logs = sub.add_parser("logs", help="show the end of the log")
    p_logs.add_argument("-n", type=int, default=40)
    args = parser.parse_args(argv)
    if args.command == "start":
        return start(restart=args.restart, quiet=args.quiet)
    if args.command == "stop":
        return stop(force=args.force)
    if args.command == "status":
        return status()
    if args.command == "open":
        return open_browser()
    return logs(args.n)


if __name__ == "__main__":
    raise SystemExit(main())
