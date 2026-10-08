#!/usr/bin/env python3
"""Start only this skill's local app; all model work stays in its own environment."""

from __future__ import annotations

import argparse
import subprocess
import sys
from _common import app_directory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Start the local privacy filter.")
    parser.add_argument("--app-dir", help="Optional app folder; defaults to this skill's assets/app.")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535 or not 0 < args.timeout <= 1800:
        parser.error("Choose a port from 1024 to 65535 and a startup timeout from 1 to 1800 seconds.")
    app_dir = app_directory(args.app_dir)
    python = app_dir / ".venv" / "bin" / "python"
    launch = app_dir / "launch.py"
    if not python.is_file() or not launch.is_file():
        print("Complete this skill's local setup first by opening Setup.command or running assets/app/setup.sh.", file=sys.stderr)
        return 1
    command = [str(python), str(launch), "--port", str(args.port), "--timeout", str(args.timeout)]
    if args.headless:
        command.append("--headless")
    try:
        return subprocess.call(command, cwd=str(app_dir))
    except KeyboardInterrupt:
        return 0
    except OSError:
        print("The local app environment could not be started. Rerun setup in its final folder.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
