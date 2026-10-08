"""Loopback-only browser/API service. Request text is never persisted or logged."""

from __future__ import annotations

import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets

# These are enforced before importing any model libraries. Installation and model
# downloads are a separate, explicit setup step.
for _name in (
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "HF_DATASETS_OFFLINE",
    "HF_HUB_DISABLE_TELEMETRY",
    "DO_NOT_TRACK",
):
    os.environ[_name] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .engine import PrivacyFilter
from .documents import (
    DocumentError,
    MAX_DOCUMENT_CHARS,
    MAX_FILE_BYTES,
    SAFE_ERROR_MESSAGES,
    SUPPORTED_EXTENSIONS,
    filter_document,
    ocr_available,
)

APP_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = APP_ROOT / "models" / "gliner2-pii"
SERVICE_ID = "local-privacy-filter-v1"
WORKSPACE_ID = hashlib.sha256(str(APP_ROOT).encode("utf-8")).hexdigest()[:24]
MAX_TEXT_CHARS = 100_000
MAX_BODY_BYTES = 1_250_000
FEATURE_REVISION = "documents-v1"
FILE_MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ready = False
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="privacy-filter")
    app.state.worker = worker
    app.state.inference_lock = asyncio.Lock()
    try:
        loop = asyncio.get_running_loop()
        # Health only becomes ready after both local models finish loading.
        app.state.filter = await loop.run_in_executor(
            worker, lambda: PrivacyFilter(model_path=str(MODEL_PATH))
        )
        app.state.ready = True
        yield
    except Exception:
        # Startup failures have no submitted text. Keep model/library errors out
        # of the browser response and the launcher's normal output.
        raise RuntimeError("The local privacy models could not be loaded.") from None
    finally:
        app.state.ready = False
        worker.shutdown(wait=True, cancel_futures=True)
        app.state.filter = None


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"], www_redirect=False
)


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, _exception: RequestValidationError):
    # FastAPI's default validation response can echo the submitted input.
    return _error("This request could not be read.", 400)


@app.middleware("http")
async def protect_local_requests(request: Request, call_next):
    # An arbitrary website may not submit text to the local service. CLI clients
    # without an Origin header are supported; browser requests must be same-origin.
    origin = request.headers.get("origin")
    expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
    if origin is not None and origin != expected_origin:
        response = _error("This request is not allowed.", 403)
    elif request.headers.get("sec-fetch-site") == "cross-site":
        response = _error("This request is not allowed.", 403)
    else:
        response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/")
async def home():
    nonce = secrets.token_urlsafe(24)
    source = (APP_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    response = HTMLResponse(source.replace("{{NONCE}}", nonce))
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    return response


@app.get("/health")
async def health():
    ready = bool(getattr(app.state, "ready", False))
    return JSONResponse(
        {
            "service": SERVICE_ID,
            "workspace_id": WORKSPACE_ID,
            "ready": ready,
            "offline": True,
            "language": "en",
            "max_text_characters": MAX_TEXT_CHARS,
            "feature_revision": FEATURE_REVISION,
            "supported_file_extensions": sorted(SUPPORTED_EXTENSIONS),
            "max_file_bytes": MAX_FILE_BYTES,
            "max_document_characters": MAX_DOCUMENT_CHARS,
            "ocr_available": ocr_available(),
        },
        status_code=200 if ready else 503,
    )


@app.post("/redact")
async def redact(request: Request):
    if not getattr(app.state, "ready", False):
        return _error("The local filter is not ready. Please try again later.", 503)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if content_type.lower() != "application/json":
        return _error("Send a JSON request containing a text field.", 415)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return _error("The text is too long for one request.", 413)
        except ValueError:
            return _error("This request could not be read.", 400)

    body = bytearray()
    try:
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                return _error("The text is too long for one request.", 413)
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        return _error("This request could not be read.", 400)
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        return _error("Send a JSON request containing a text field.", 400)
    text = payload["text"]
    if len(text) > MAX_TEXT_CHARS:
        return _error("Use at most 100,000 characters per request.", 413)
    if not text.strip():
        return _error("Paste some text first.", 400)
    if app.state.inference_lock.locked():
        return _error("The local filter is busy. Please try again shortly.", 429)

    try:
        async with app.state.inference_lock:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                app.state.worker, app.state.filter.redact, text
            )
        # Only redacted text and non-text metadata cross the API boundary.
        redacted_text = result["redacted_text"]
        counts = result["counts"]
        if not isinstance(redacted_text, str) or not isinstance(counts, dict):
            raise ValueError("Invalid engine result")
        return JSONResponse(
            {
                "redacted_text": redacted_text,
                "entity_count": int(result.get("entity_count", 0)),
                "counts": counts,
                "warnings": result.get("warnings", []),
            }
        )
    except Exception:
        # Do not return inputs, partial output, exception strings or tracebacks.
        return _error("Redaction failed. No result is available. Please try again.", 503)
    finally:
        body.clear()
        payload = None
        text = None


@app.post("/redact-file")
async def redact_file(request: Request):
    if not getattr(app.state, "ready", False):
        return _error("The local filter is not ready. Please try again later.", 503)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if content_type.lower() != "application/octet-stream":
        return _error("Send the file as application/octet-stream.", 415)
    # The original filename is deliberately never requested or returned.
    extension = request.headers.get("x-file-extension", "").strip().lower().lstrip(".")
    if extension not in SUPPORTED_EXTENSIONS:
        return _error("Choose a CSV, Excel (.xlsx), Word (.docx) or PDF file.", 400)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_FILE_BYTES:
                return _error("Use a file of at most 20 MiB.", 413)
        except ValueError:
            return _error("This file request could not be read.", 400)
    if app.state.inference_lock.locked():
        return _error("The local filter is busy. Please try again shortly.", 429)

    body = bytearray()
    result = None
    try:
        # Reserve the same worker used for pasted text while receiving and
        # processing a file, so concurrent uploads do not accumulate in memory.
        async with app.state.inference_lock:
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_FILE_BYTES:
                    return _error("Use a file of at most 20 MiB.", 413)
                body.extend(chunk)
            if not body:
                return _error("Choose a non-empty file.", 400)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                app.state.worker,
                lambda: filter_document(bytes(body), extension, app.state.filter.redact),
            )
        output_extension = result.extension.lower().lstrip(".")
        if (
            output_extension not in FILE_MEDIA_TYPES
            or not isinstance(result.content, bytes)
            or not result.content
            or len(result.content) > MAX_FILE_BYTES
            or not isinstance(result.entity_count, int)
            or result.entity_count < 0
            or not isinstance(result.units, int)
            or result.units < 0
            or not isinstance(result.warnings, list)
            or not all(isinstance(item, str) for item in result.warnings)
        ):
            raise ValueError("Invalid document result")
        return JSONResponse(
            {
                "content_base64": base64.b64encode(result.content).decode("ascii"),
                "media_type": FILE_MEDIA_TYPES[output_extension],
                "extension": output_extension,
                "filename": f"redacted.{output_extension}",
                "entity_count": result.entity_count,
                "warnings": result.warnings,
                "units": result.units,
            }
        )
    except DocumentError as error:
        message = str(error)
        if message not in SAFE_ERROR_MESSAGES:
            message = "This file could not be filtered. No result is available."
        status = error.status if error.status in {400, 413, 422, 503} else 400
        return _error(message, status)
    except Exception:
        return _error("File filtering failed. No result is available. Please try again.", 503)
    finally:
        body.clear()
        result = None


def main():
    parser = argparse.ArgumentParser(description="Run the local privacy filter.")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535.")
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
