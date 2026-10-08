"""Portable paths and loopback-only checks; standard library only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

SERVICE_ID = "local-privacy-filter-v1"
FEATURE_REVISION = "documents-v1"
DEFAULT_APP_DIR = Path(__file__).resolve().parent.parent / "assets" / "app"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def app_directory(value: str | None = None) -> Path:
    return Path(value).expanduser().resolve() if value else DEFAULT_APP_DIR.resolve()


def workspace_id(app_dir: Path) -> str:
    return hashlib.sha256(str(app_dir.resolve()).encode("utf-8")).hexdigest()[:24]


def read_health(port: int, timeout: float = 3) -> dict | None:
    if not 1024 <= port <= 65535:
        return None
    try:
        with OPENER.open(f"http://127.0.0.1:{port}/health", timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = response.read(8193)
        if len(payload) > 8192:
            return None
        result = json.loads(payload)
        return result if isinstance(result, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def matches_health(payload: dict | None, app_dir: Path) -> bool:
    return bool(payload and payload.get("service") == SERVICE_ID
                and payload.get("workspace_id") == workspace_id(app_dir)
                and payload.get("feature_revision") == FEATURE_REVISION
                and payload.get("ready") is True and payload.get("offline") is True
                and set(payload.get("supported_file_extensions", [])) == {"csv", "xlsx", "docx", "pdf"})
