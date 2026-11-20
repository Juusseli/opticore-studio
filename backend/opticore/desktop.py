"""The desktop application: one process that serves the engine and the built user interface, opened in an app window.

* The engine (``api/main.py``) serves ``/api/v1`` and, in this mode, the user interface (``frontend/dist``, or the copy
  bundled with the installed program) at ``/``, on ``127.0.0.1`` only.
* The port is fixed (``PORT``), because the browser keeps the project library per origin: another port would open an
  empty library. If another program holds it, the next free one of a few is used and the log says so.
* The window is a browser app window: Microsoft Edge or Chrome in app mode where available, otherwise the default
  browser. The environment variable OPTICORE_BROWSER chooses another browser command, or ``none``.
* The program ends when its last window has been closed. The page sends a heartbeat every 10 s and a goodbye when it
  is closed; the server stops ``BYE_GRACE_S`` after a goodbye without a new heartbeat (a reload sends one), or
  ``SILENCE_S`` after the last heartbeat.
* A second start opens a window on the running instance instead of starting another one.

Run with ``python -m opticore.desktop`` (the user interface must be built: ``npm run build`` in ``frontend``), or as the
packaged program. ``--self-test`` starts the server without a window, checks the user interface, an evaluation and the
process pool, and exits with status 0 on success (used by the package builds).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__

APP_NAME = "OptiCore Studio"
PORT = 47321
PORT_TRIES = 10
HEARTBEAT_S = 10.0
BYE_GRACE_S = 10.0
SILENCE_S = 90.0
FIRST_CONTACT_S = 300.0

log = logging.getLogger("opticore.desktop")


def data_dir() -> Path:
    """Per-user folder for the log and the running-instance record."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "opticore-studio"
    base.mkdir(parents=True, exist_ok=True)
    return base


def ui_dir() -> Path | None:
    """The built user interface: bundled with the packaged program, else OPTICORE_UI_DIR, else frontend/dist."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "ui")
    if os.environ.get("OPTICORE_UI_DIR"):
        candidates.append(Path(os.environ["OPTICORE_UI_DIR"]))
    candidates.append(Path(__file__).resolve().parents[2] / "frontend" / "dist")
    return next((c for c in candidates if (c / "index.html").is_file()), None)


def _url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def _ping(port: int, timeout: float = 1.0) -> bool:
    """Is an OptiCore Studio desktop server answering on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/app/ping", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == APP_NAME
    except Exception:
        return False


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def open_window(url: str) -> None:
    """An app window (Edge or Chrome in app mode) where one is available, otherwise the default browser.

    OPTICORE_BROWSER chooses the browser instead: a command (run with the address), or ``none`` for no window."""
    chosen = os.environ.get("OPTICORE_BROWSER", "").strip()
    if chosen.lower() == "none":
        return
    if chosen:
        try:
            subprocess.Popen([chosen, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError as exc:
            log.warning("OPTICORE_BROWSER %r failed (%s): using the default", chosen, exc)
    candidates: list[str | None] = []
    if sys.platform == "win32":
        for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                candidates.append(str(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
                candidates.append(str(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    else:
        candidates += [shutil.which(n) for n in ("microsoft-edge", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser")]
    for exe in candidates:
        if exe and Path(exe).is_file():
            try:
                subprocess.Popen([exe, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue
    webbrowser.open(url)


class Lifetime:
    """Ends the server when no window has been open for a while (see the module docstring)."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.last_beat: float | None = None
        self.bye_at: float | None = None
        self._lock = threading.Lock()

    def beat(self) -> None:
        with self._lock:
            self.last_beat = time.monotonic()
            self.bye_at = None

    def bye(self) -> None:
        with self._lock:
            self.bye_at = time.monotonic()

    def should_stop(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            if self.bye_at is not None and now - self.bye_at > BYE_GRACE_S:
                return True
            if self.last_beat is None:
                return now - self.started > FIRST_CONTACT_S
            return now - self.last_beat > SILENCE_S


def build_app(ui: Path, lifetime: Lifetime):
    """The engine's FastAPI application with the window lifetime endpoints and the user interface mounted at ``/``."""
    from fastapi.staticfiles import StaticFiles

    from .api.main import app

    if not any(getattr(r, "path", "") == "/api/v1/app/ping" for r in app.routes):

        def ping():
            return {"app": APP_NAME, "version": __version__}

        def heartbeat():
            lifetime.beat()
            return {"ok": True}

        def bye():
            lifetime.bye()
            return {"ok": True}

        app.add_api_route("/api/v1/app/ping", ping, methods=["GET"])
        app.add_api_route("/api/v1/app/heartbeat", heartbeat, methods=["POST"])
        app.add_api_route("/api/v1/app/bye", bye, methods=["POST"])
        # after every API route, so /api/v1 is matched first
        app.mount("/", StaticFiles(directory=str(ui), html=True), name="ui")
    return app


def _setup_logging() -> Path:
    path = data_dir() / "opticore.log"
    try:
        if path.exists() and path.stat().st_size > 5_000_000:
            path.unlink()
    except OSError:
        pass
    stream = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 (kept open for the process lifetime)
    # a windowed program has no console: route print and errors to the log (with a console, errors stay visible there)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=stream, force=True)
    return path


def _serve(app, port: int, lifetime: Lifetime | None):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False))
    if lifetime is not None:

        def watch():
            while not server.should_exit:
                time.sleep(1.0)
                if lifetime.should_stop():
                    log.info("No window open: stopping")
                    server.should_exit = True

        threading.Thread(target=watch, name="lifetime", daemon=True).start()
    return server


def _wait_until_up(port: int, timeout: float = 60.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if _ping(port, 0.5):
            return True
        time.sleep(0.2)
    return False


def self_test(ui: Path) -> int:
    """Start without a window, check the user interface, one evaluation and the process pool, and stop."""
    from . import workers

    port = next(p for p in range(PORT + 100, PORT + 200) if _port_free(p))
    server = _serve(build_app(ui, Lifetime()), port, None)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    ok = _wait_until_up(port)
    checks = {"server": ok}
    if ok:
        with urllib.request.urlopen(_url(port), timeout=10) as r:
            checks["user interface"] = r.status == 200 and b'id="root"' in r.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/samples/achromat", timeout=60) as r:
            project = json.loads(r.read().decode("utf-8"))
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/system/evaluate", data=json.dumps({"system": project["system"]}).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            checks["evaluation"] = r.status == 200 and "surfaces" in json.loads(r.read().decode("utf-8"))
        pool, flag = workers.acquire()
        try:
            checks["process pool"] = pool.submit(os.getpid).result(timeout=120) != os.getpid()
        finally:
            workers.release(flag)
        try:  # the OpenCascade kernel of the CAD import and export, with its native libraries
            from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

            checks["CAD kernel"] = not BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape().IsNull()
        except Exception as exc:  # reported, not raised: the test names what failed
            log.error("CAD kernel: %s", exc)
            checks["CAD kernel"] = False
    server.should_exit = True
    th.join(timeout=30)
    for name, passed in checks.items():
        _say(f"self-test {name}: {'ok' if passed else 'FAILED'}")
    return 0 if all(checks.values()) and len(checks) == 5 else 1


def _say(msg: str) -> None:
    """To the console where there is one (a windowed program has none) and to the log."""
    log.info(msg)
    if sys.__stdout__ is not None:
        print(msg, file=sys.__stdout__, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opticore-studio", description=f"{APP_NAME} {__version__}: optical design and simulation")
    parser.add_argument("--self-test", action="store_true", help="check the program without opening a window, then exit")
    parser.add_argument("--no-window", action="store_true", help="serve without opening a window (open the printed address yourself)")
    args = parser.parse_args(argv)

    log_path = _setup_logging()
    ui = ui_dir()
    if ui is None:
        _say("The user interface is not built: run `npm run build` in frontend/ first.")
        return 2
    if args.self_test:
        return self_test(ui)

    record = data_dir() / "instance.json"
    try:
        running = json.loads(record.read_text(encoding="utf-8")).get("port")
    except (OSError, ValueError):
        running = None
    for p in dict.fromkeys([running, *range(PORT, PORT + PORT_TRIES)]):
        if p and _ping(p):
            log.info("Already running on port %d: opening a window", p)
            if not args.no_window:
                open_window(_url(p))
            return 0
    port = next((p for p in range(PORT, PORT + PORT_TRIES) if _port_free(p)), None)
    if port is None:
        log.error("No free port from %d to %d", PORT, PORT + PORT_TRIES - 1)
        return 1
    if port != PORT:
        log.warning("Port %d is in use by another program: using %d (the project library of this origin is separate)", PORT, port)

    lifetime = Lifetime()
    server = _serve(build_app(ui, lifetime), port, None if args.no_window else lifetime)
    record.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    log.info("%s %s on %s (log %s)", APP_NAME, __version__, _url(port), log_path)
    if args.no_window:
        _say(f"{APP_NAME} is running at {_url(port)} (stop with Ctrl+C)")
    else:

        def open_when_up():
            if _wait_until_up(port):
                open_window(_url(port))

        threading.Thread(target=open_when_up, daemon=True).start()
    try:
        server.run()
    finally:
        try:
            if json.loads(record.read_text(encoding="utf-8")).get("pid") == os.getpid():
                record.unlink()
        except (OSError, ValueError):
            pass
    return 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    sys.exit(main())
