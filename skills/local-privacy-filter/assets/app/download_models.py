"""Setup-only public downloads pinned by commit and SHA-256 for every asset.

Importing this module performs no download, environment change or file write.
--verify-only is read-only. Runtime inference never calls this downloader.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
MODEL_ID = "fastino/gliner2-privacy-filter-PII-multi"
MODEL_REVISION = "1cb4166094dc58fa8d836429f060d6c95f62b495"
# Verified public artifacts at this exact revision; no remote Python/pickle files.
MODEL_ASSETS = {
    "README.md": (9076, "e932bd007f5b386ecf88f28058c6a96ef001c4fc8ba8175f10671db2539f51a1"),
    "config.json": (252, "164f17362bcf9d114067d3465e7374bfdd79ce6b605acb745de5a49dabb9595c"),
    "encoder_config/config.json": (895, "f27dd63cc43a248d2566f0b6ad7a115db353676ce0561dcbca45bac766464c1a"),
    "model.safetensors": (1228421964, "0280f6f39f6012da50b6640bad438d9b7e763a1b0102094115d1b710c4dd79b6"),
    "tokenizer.json": (16020604, "f6df10ec83bea993035b2dd7c39345a3d4fcf23421c2adb6cb4ffc1e6d1bc4b5"),
    "tokenizer_config.json": (711, "233beed1f1095cccfc7907cde31a8d90a0c6aa4fdfaf6493f8e55fd162e81ae6"),
}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_valid(path: Path, expected: tuple[int, str]) -> bool:
    try:
        return path.is_file() and path.stat().st_size == expected[0] and _digest(path) == expected[1]
    except OSError:
        return False


def verify_model_assets(local: Path) -> bool:
    local = Path(local)
    if not local.is_dir():
        return False
    try:
        if any(path.is_file() and path.suffix.lower() in {".py", ".bin", ".pt", ".pth", ".pkl"} for path in local.rglob("*")):
            return False
        return all(_asset_valid(local / name, expected) for name, expected in MODEL_ASSETS.items())
    except OSError:
        return False


def download() -> None:
    local = ROOT / "models" / "gliner2-pii"
    if local.is_symlink() or (ROOT / "models").is_symlink():
        raise RuntimeError("Model setup requires this app's own model folder.")
    # Public setup downloads never use a saved HF token or a remote implementation.
    os.environ.update({"HF_HOME": str(ROOT / ".setup-cache" / "huggingface"),
                       "HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "0",
                       "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                       "HF_HUB_DISABLE_XET": "1"})
    from huggingface_hub import hf_hub_download

    for name, expected in MODEL_ASSETS.items():
        target = local / name
        if _asset_valid(target, expected):
            continue
        hf_hub_download(repo_id=MODEL_ID, filename=name, revision=MODEL_REVISION,
                        local_dir=str(local), token=False, force_download=target.exists())
        if not _asset_valid(target, expected):
            raise RuntimeError("The pinned public model failed checksum verification.")
    if not verify_model_assets(local):
        raise RuntimeError("The local model folder contains unsupported artifacts.")
    provenance = {
        "model_id": MODEL_ID, "revision": MODEL_REVISION,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source": f"https://huggingface.co/{MODEL_ID}/tree/{MODEL_REVISION}",
        "runtime": "Local CPU; offline loading; no remote model implementation",
        "downloaded_files": [{"path": name, "bytes": expected[0], "sha256": expected[1],
                              "pinned_sha256_verified": True} for name, expected in MODEL_ASSETS.items()],
    }
    temporary = ROOT / "models" / ".provenance.tmp"
    temporary.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ROOT / "models" / "provenance.json")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Download or verify the pinned public privacy model.")
    parser.add_argument("--verify-only", action="store_true", help="Read-only SHA-256 verification; no network.")
    args = parser.parse_args(argv)
    if args.verify_only:
        valid = verify_model_assets(ROOT / "models" / "gliner2-pii")
        print(json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION, "verified": valid, "read_only": True}))
        return 0 if valid else 1
    try:
        download()
    except Exception:
        print("The public model download did not finish or failed verification. Existing files were kept; rerun setup to resume.", file=sys.stderr)
        return 1
    print(json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION, "verified": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
