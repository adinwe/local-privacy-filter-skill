# Installation and runtime

## Paths and prerequisites

Commands below run from the skill directory containing `SKILL.md`. Helpers resolve `assets/app` relative to their own location, and accept `--app-dir` for an explicitly chosen app copy. Do not depend on the chat's current directory.

Install the skill, or place a standalone repository copy in its final folder, before setup. Virtual environments contain location-specific interpreter paths. If a configured folder moves and its environment breaks, preserve it, install a fresh source copy in the final location and set up that copy. The installer preserves an incompatible or broken environment rather than replacing it silently.

The pinned environment targets **macOS 14+ on Apple Silicon**. Recommend **16 GB RAM** and **6 GB free for initial setup**. Estimated installed runtime size is **2–3 GB**, excluding optional OCR tools and user files. Other operating systems and Intel Macs need a separately verified dependency set.

`uv` is required to obtain managed Python 3.12. Use the installer's prerequisite message when it is missing; do not substitute an old system Python or install dependencies into it.

## Check or set up

```sh
sh assets/app/setup.sh --check-only
```

Check-only mode reports prerequisites and setup state without installing dependencies or downloading models. First setup:

```sh
sh assets/app/setup.sh
```

The Python helpers `scripts/install.py`, `scripts/start.py` and `scripts/check.py` can also be called with a suitable local interpreter. After setup, prefer `assets/app/.venv/bin/python` so the interpreter is known.

Setup installs the accompanying **83-package dependency lock**, including the English spaCy model. It downloads:

- Model: `fastino/gliner2-privacy-filter-PII-multi`.
- Revision: `1cb4166094dc58fa8d836429f060d6c95f62b495`.
- Local destination: `assets/app/models/gliner2-pii`.

Public downloads occur only during setup. Runtime enforces Hugging Face offline flags, disables telemetry and loads local model files. No user document is needed for setup. Existing healthy managed environments should be reused by the installer; inspect its status output rather than repeatedly reinstalling.

## Optional scanned-PDF OCR

Text-based PDFs and Office/CSV files work without OCR. Scanned PDFs require **Poppler (`pdftoppm`)**, **Tesseract** and its **English recognition data**.

When OCR setup is within the user's requested scope and Homebrew is already installed:

```sh
sh assets/app/setup.sh --with-ocr
```

The flag uses existing Homebrew to obtain the native tools. It does not authorize unrelated package changes. If Homebrew is absent, report the prerequisite and continue with supported text-based files where possible. `GET /health` reports `ocr_available`; lack of OCR must not become an automatic cloud OCR fallback.

## Start, check and stop

```sh
assets/app/.venv/bin/python scripts/start.py
```

The default service is `http://127.0.0.1:8787/`. It loads models before declaring readiness and opens the browser afterward. The launcher verifies app/workspace identity, offline readiness and the document feature revision when considering an existing service. It refuses to reuse another service on the port.

For a local headless run or alternate port:

```sh
assets/app/.venv/bin/python scripts/start.py --headless --port 8790
assets/app/.venv/bin/python scripts/check.py --port 8790 --smoke
```

Run the check in another terminal or tool session while the launcher stays running. The smoke input is fixed fictional text. It checks operation, not detection accuracy on a user's documents. Keep the launcher session open; **Control+C** stops the service. There is no login item or automatic background startup.

An occupied port and a denied local socket are different failures. Preserve that distinction in the launcher's message. Follow the host's actual local-network permission mechanism if access is denied; do not relabel a denied socket as a competing service or expose the server publicly to work around it.

## Tests

```sh
cd assets/app
.venv/bin/python -m unittest discover -s tests -v
```

The included tests cover synthetic detection boundaries, document handling and API isolation. They do not establish clinical performance or guarantee that every identifying detail is removed.
