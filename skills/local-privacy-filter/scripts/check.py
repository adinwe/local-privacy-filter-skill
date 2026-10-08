#!/usr/bin/env python3
"""Check this local service; optional smoke test sends fixed synthetic text only."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from _common import OPENER, app_directory, matches_health, read_health

SYNTHETIC_TEXT = "Contact Alex Example at alex@example.invalid or 0412 345 678. Ordinary prose remains useful."


def smoke_test(port: int) -> bool:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/redact",
        data=json.dumps({"text": SYNTHETIC_TEXT}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with OPENER.open(request, timeout=60) as response:
            if response.status != 200:
                return False
            data = response.read(16385)
        if len(data) > 16384:
            return False
        result = json.loads(data)
        masked = result.get("redacted_text") if isinstance(result, dict) else None
        return bool(isinstance(masked, str) and result.get("entity_count", 0) >= 2
                    and "alex@example.invalid" not in masked and "0412 345 678" not in masked)
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the running local privacy filter.")
    parser.add_argument("--app-dir", help="Optional app folder; defaults to this skill's assets/app.")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--smoke", action="store_true", help="Also mask a fixed synthetic contact example.")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535.")
    app_dir = app_directory(args.app_dir)
    payload = read_health(args.port)
    if not matches_health(payload, app_dir):
        print("This app is not ready on that local port, or the port belongs to a different app folder. Start it first.", file=sys.stderr)
        return 1
    if args.smoke and not smoke_test(args.port):
        print("The synthetic filtering check failed. Review the local installation before using it.", file=sys.stderr)
        return 1
    print(json.dumps({"ready": True, "offline": True, "documents": True,
                      "ocr_available": bool(payload.get("ocr_available")),
                      "synthetic_check": "passed" if args.smoke else "not_requested"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
