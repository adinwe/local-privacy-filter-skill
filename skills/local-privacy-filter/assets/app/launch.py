#!/usr/bin/env python3
"""Start the app with its own Python; open the browser only after model readiness."""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

APP_ROOT = Path(__file__).resolve().parent
PYTHON = APP_ROOT / ".venv" / "bin" / "python"
SERVICE_ID = "local-privacy-filter-v1"
FEATURE_REVISION = "documents-v1"
WORKSPACE_ID = hashlib.sha256(str(APP_ROOT).encode("utf-8")).hexdigest()[:24]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def health(port: int):
    try:
        with OPENER.open(f"http://127.0.0.1:{port}/health", timeout=0.8) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read(8192))
            if isinstance(payload, dict):
                return payload
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return None


def matches(payload):
    return bool(
        payload
        and payload.get("service") == SERVICE_ID
        and payload.get("workspace_id") == WORKSPACE_ID
        and payload.get("ready") is True
        and payload.get("offline") is True
        and payload.get("feature_revision") == FEATURE_REVISION
    )


def port_is_free(port: int):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                return False
            raise


def show_ready(url: str, headless: bool, reused: bool = False):
    suffix = " (existing local service)" if reused else ""
    print(f"Ready at {url}{suffix}", flush=True)
    if not headless:
        try:
            if not webbrowser.open(url, new=2):
                print("Open the local address above in your browser.", flush=True)
        except Exception:
            print("Open the local address above in your browser.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Open the local privacy filter.")
    parser.add_argument("--headless", action="store_true", help="Run without opening a browser.")
    parser.add_argument("--port", type=int, default=8787, help="Local port (default: 8787).")
    parser.add_argument("--timeout", type=float, default=180, help="Model startup timeout in seconds.")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535.")
    if args.timeout <= 0:
        parser.error("The startup timeout must be positive.")
    url = f"http://127.0.0.1:{args.port}/"
    existing = health(args.port)
    if matches(existing):
        show_ready(url, args.headless, reused=True)
        return 0
    if (
        existing
        and existing.get("service") == SERVICE_ID
        and existing.get("workspace_id") == WORKSPACE_ID
    ):
        print(
            "An earlier version of this filter is running. Stop its Terminal "
            "window with Control+C, then open Privacy Filter.command again.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    try:
        available = port_is_free(args.port)
    except PermissionError:
        print(
            "Permission to open a local network socket was denied. "
            "Allow local network access and try again.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    except OSError:
        print("The local network port could not be checked. No service was started.", file=sys.stderr, flush=True)
        return 1
    if not available:
        print(
            "This local port is already in use by another service. "
            "Close that service or launch with a different --port.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    if not PYTHON.is_file():
        print("The app's Python environment is missing. Open Setup.command or run this skill's assets/app/setup.sh first.", file=sys.stderr)
        return 1
    if not (APP_ROOT / "models" / "gliner2-pii").is_dir():
        print("The local privacy model is missing. Rerun this skill's local setup to resume the verified model download.", file=sys.stderr)
        return 1

    # Reserve this launch while models load, before Uvicorn starts listening.
    # The empty lock file contains no input, result, process or session data.
    try:
        runtime_dir = APP_ROOT / ".runtime"
        runtime_dir.mkdir(mode=0o700, exist_ok=True)
        lock_fd = os.open(runtime_dir / f"launch-{args.port}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lock_fd)
            print("Another launch of this filter is still starting. Wait for its window to become ready.", file=sys.stderr, flush=True)
            return 1
    except OSError:
        print("The local filter could not reserve its startup. Check this app folder's permissions.", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    for name in (
        "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE",
        "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK",
    ):
        environment[name] = "1"
    environment["TOKENIZERS_PARALLELISM"] = "false"
    child = None

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    try:
        print("Loading the local privacy models…", flush=True)
        # Output stays in the terminal; no log files or request access logs.
        child = subprocess.Popen(
            [str(PYTHON), "-m", "privacy_filter.server", "--port", str(args.port)],
            cwd=str(APP_ROOT), env=environment,
        )
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            if child.poll() is not None:
                print("The local filter could not start. Check the installed models and environment.", file=sys.stderr, flush=True)
                return 1
            if matches(health(args.port)):
                show_ready(url, args.headless)
                print("Keep this window open. Press Control+C to stop the filter.", flush=True)
                return child.wait()
            time.sleep(0.25)
        print("The local models did not become ready in time. No browser was opened.", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("Stopping the local filter…", flush=True)
        return 0
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
