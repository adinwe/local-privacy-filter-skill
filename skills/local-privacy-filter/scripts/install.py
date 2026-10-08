#!/usr/bin/env python3
"""Idempotent, app-local setup. Downloads only public dependencies/model assets.

Run setup.sh for automatic uv-managed Python selection. --check-only performs
read-only inspection and does not create an environment, cache or model files.
"""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True  # --check-only must not create import caches.

import argparse
import fcntl
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from _common import app_directory

MIN_FREE_BYTES = 6 * 1024 ** 3
UV_INSTALLATION_URL = "https://docs.astral.sh/uv/getting-started/installation/"


class SetupError(Exception):
    pass


def platform_supported() -> bool:
    version = platform.mac_ver()[0].split(".")
    return bool(platform.system() == "Darwin" and platform.machine() == "arm64"
                and version and version[0].isdigit() and int(version[0]) >= 14)


def setup_environment(app_dir: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_INDEX", "UV_INDEX_URL",
                 "UV_EXTRA_INDEX_URL", "UV_DEFAULT_INDEX", "UV_FIND_LINKS", "UV_CONFIG_FILE",
                 "UV_PROJECT", "UV_WORKING_DIR", "UV_INSECURE_HOST"):
        environment.pop(name, None)
    environment.update({"UV_CACHE_DIR": str(app_dir / ".setup-cache"),
                        "UV_PYTHON_INSTALL_DIR": str(app_dir / ".python"),
                        "UV_NO_CONFIG": "1", "UV_KEYRING_PROVIDER": "disabled",
                        "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "0",
                        "TRANSFORMERS_OFFLINE": "0", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
                        "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_XET": "1"})
    return environment


def run_step(command: list[str], app_dir: Path, timeout: int = 1800) -> None:
    try:
        subprocess.run(command, cwd=str(app_dir), env=setup_environment(app_dir), check=True, timeout=timeout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise SetupError("A setup download or installation did not finish. Existing files were kept; rerun setup to resume.") from None


def clean_success_cache(app_dir: Path, uv: str | None) -> None:
    cache = app_dir / ".setup-cache"
    if not uv or not cache.is_dir() or cache.is_symlink():
        return
    try:
        subprocess.run([uv, "cache", "clean", "--no-config", "--cache-dir", str(cache)],
                       cwd=str(app_dir), env=setup_environment(app_dir),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        print("The app is ready; its temporary setup cache was kept because cache cleanup did not finish.")


def locked_versions(app_dir: Path) -> dict[str, str]:
    requirements = (app_dir / "requirements.lock.txt").read_text(encoding="utf-8")
    versions = {}
    for line in requirements.splitlines():
        match = re.fullmatch(r"([a-zA-Z0-9_.-]+)==([^\s]+)", line.strip())
        if match:
            versions[match[1]] = match[2]
    spacy_match = re.search(r"en_core_web_sm-([0-9.]+)-py3-none-any.whl", requirements)
    if spacy_match:
        versions["en-core-web-sm"] = spacy_match[1]
    if not versions or "gliner2" not in versions or "en-core-web-sm" not in versions:
        raise SetupError("The packaged dependency list is incomplete. Download a fresh skill package.")
    return versions


def environment_status(app_dir: Path) -> dict:
    python = app_dir / ".venv" / "bin" / "python"
    if not python.is_file():
        return {"exists": False, "python_compatible": False, "dependencies_ready": False}
    versions = locked_versions(app_dir)
    code = (
        "import importlib.metadata as m,json,sys; expected=json.loads(sys.argv[1]); "
        "installed={d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions()}; "
        "missing=[n for n,v in expected.items() if installed.get(n.lower().replace('_','-'))!=v]; "
        "print(json.dumps({'version':list(sys.version_info[:2]),'missing':missing}))"
    )
    try:
        response = subprocess.run([str(python), "-I", "-B", "-c", code, json.dumps(versions)],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  timeout=20, check=True)
        payload = json.loads(response.stdout)
        compatible = payload.get("version") == [3, 12]
        return {"exists": True, "python_compatible": compatible,
                "dependencies_ready": compatible and payload.get("missing") == []}
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return {"exists": True, "python_compatible": False, "dependencies_ready": False}


def model_status(app_dir: Path) -> bool:
    spec = importlib.util.spec_from_file_location("privacy_filter_model_setup", app_dir / "download_models.py")
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return bool(module.verify_model_assets(app_dir / "models" / "gliner2-pii"))
    except Exception:
        return False


def ocr_status() -> bool:
    paths = []
    for name in ("pdftoppm", "tesseract"):
        candidate = Path("/opt/homebrew/bin") / name
        found = str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else shutil.which(name)
        if not found:
            return False
        paths.append(found)
    try:
        output = subprocess.run([paths[1], "--list-langs"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=10, check=True).stdout.decode("utf-8")
        return "eng" in output.splitlines()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False


def inspect_installation(app_dir: Path) -> dict:
    if not app_dir.is_dir() or any(not (app_dir / name).is_file() for name in ("requirements.lock.txt", "download_models.py", "launch.py")):
        raise SetupError("The packaged app folder is missing or incomplete. Download a fresh skill package.")
    status = environment_status(app_dir)
    status.update({"platform_supported": platform_supported(), "model_ready": model_status(app_dir),
                   "ocr_available": ocr_status(), "free_bytes": shutil.disk_usage(app_dir).free})
    status["ready"] = status["platform_supported"] and status["dependencies_ready"] and status["model_ready"]
    return status


def install(app_dir: Path, with_ocr: bool = False) -> dict:
    status = inspect_installation(app_dir)
    if not status["platform_supported"]:
        raise SetupError("This package requires an Apple Silicon Mac running macOS 14 or newer.")
    if status["ready"] and (not with_ocr or status["ocr_available"]):
        return status
    if status["free_bytes"] < MIN_FREE_BYTES:
        raise SetupError("Setup needs at least 6 GiB free disk space for about 2 GiB of installed files plus downloads and cache. Existing installations were kept.")
    if any((app_dir / name).is_symlink() for name in (".venv", ".python", ".setup-cache", "models")) or (app_dir / "models" / "gliner2-pii").is_symlink():
        raise SetupError("An app installation folder points elsewhere. Use a fresh skill folder; setup will not change that installation.")
    if status["exists"] and not status["python_compatible"]:
        raise SetupError("The existing app environment is not usable Python 3.12. Preserve it and set up a fresh skill folder.")
    if not status["exists"] and (app_dir / ".venv").exists():
        raise SetupError("An unfinished environment folder already exists. Preserve it and set up a fresh skill folder.")
    uv = shutil.which("uv")
    if (not status["dependencies_ready"] or not status["exists"]) and not uv:
        raise SetupError(f"Install uv first, then rerun setup. With existing Homebrew: brew install uv. Official instructions: {UV_INSTALLATION_URL}")
    brew = shutil.which("brew") if with_ocr and not status["ocr_available"] else None
    if with_ocr and not status["ocr_available"] and not brew:
        raise SetupError("Optional OCR setup needs an existing Homebrew installation. Text PDFs and Office files work without OCR.")
    lock_fd = os.open(app_dir / ".setup.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError("Another setup is running in this app folder. Wait for it to finish.") from None
        if not status["exists"]:
            print("Preparing this app's local Python 3.12…", flush=True)
            run_step([uv, "venv", "--no-project", "--no-config", "--managed-python", "--python", "3.12", str(app_dir / ".venv")], app_dir)
        python = app_dir / ".venv" / "bin" / "python"
        if not status["dependencies_ready"]:
            print("Installing pinned public dependencies…", flush=True)
            run_step([uv, "pip", "install", "--no-config", "--no-build", "--link-mode", "copy", "--default-index", "https://pypi.org/simple", "--keyring-provider", "disabled", "--python", str(python), "-r", str(app_dir / "requirements.lock.txt")], app_dir)
        if not status["model_ready"]:
            print("Downloading and verifying the pinned public privacy model…", flush=True)
            run_step([str(python), "-B", str(app_dir / "download_models.py")], app_dir)
        if with_ocr and not status["ocr_available"]:
            print("Installing optional local PDF OCR tools with existing Homebrew…", flush=True)
            run_step([brew, "install", "poppler", "tesseract"], app_dir)
        final = inspect_installation(app_dir)
        if not final["ready"]:
            raise SetupError("Setup finished incompletely. Existing files were kept; rerun setup to resume.")
        if with_ocr and not final["ocr_available"]:
            raise SetupError("The optional OCR tools need English language data. Text PDFs and Office files are ready; check the Tesseract installation.")
        clean_success_cache(app_dir, uv)
        return final
    finally:
        os.close(lock_fd)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Set up the local privacy filter in this skill's app folder.")
    parser.add_argument("--app-dir", help="Optional app folder; defaults to this skill's assets/app.")
    parser.add_argument("--check-only", action="store_true", help="Read-only inspection; no downloads or installation.")
    parser.add_argument("--with-ocr", action="store_true", help="Install optional Poppler/Tesseract using existing Homebrew.")
    args = parser.parse_args(argv)
    try:
        app_dir = app_directory(args.app_dir)
        result = inspect_installation(app_dir) if args.check_only else install(app_dir, args.with_ocr)
    except SetupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("This app folder could not be checked. Review its location and permissions.", file=sys.stderr)
        return 1
    summary = {"ready": result["ready"], "platform_supported": result["platform_supported"],
               "python_ready": result["python_compatible"], "dependencies_ready": result["dependencies_ready"],
               "model_ready": result["model_ready"], "ocr_available": result["ocr_available"],
               "free_gib": round(result["free_bytes"] / 1024 ** 3, 1), "read_only": args.check_only}
    print(json.dumps(summary), flush=True)
    if not args.check_only and result["ready"]:
        print("Setup complete. Open Privacy Filter.command to start the local app.")
        if not result["ocr_available"]:
            print("Scanned PDFs need optional local OCR. Other supported documents are ready; rerun with --with-ocr when wanted.")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
