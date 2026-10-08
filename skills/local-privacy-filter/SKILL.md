---
name: local-privacy-filter
description: "Set up and use the local English privacy filter on macOS Apple Silicon to redact text, spreadsheets, Word documents and PDFs before human review."
---

# Local Privacy Filter

Use the bundled local app to prepare reviewed copies of English text or CSV, XLSX, DOCX and PDF files. Detection combines GLiNER2 and Presidio; scanned PDFs can use local Poppler/Tesseract OCR. It does not need a separate chat model.

## Agent compatibility

Use this skill in a local Codex or Claude Code session on the supported Mac. Codex uses `$local-privacy-filter`; Claude Code uses `/local-privacy-filter`. The shared scripts resolve their bundled app relative to this installed skill. `agents/openai.yaml` supplies Codex UI metadata only.

Do not try to install this Mac runtime in a Claude chat, Cowork or cloud execution environment. Those users can run the standalone local browser app themselves and share only a reviewed filtered copy. This skill does not intercept every agent message or file read automatically.

## Setup and opening

Resolve all paths from this skill's installed directory. The app is in `assets/app`; helper scripts default to that app directory. Keep the installed skill in its final location before building its environment.

- Check existing setup without downloads: `sh assets/app/setup.sh --check-only`.
- For setup requested or needed by the filtering task: `sh assets/app/setup.sh`. It uses `uv` to obtain managed Python 3.12, install pinned dependencies and download the pinned public model. Read [installation.md](references/installation.md) for prerequisites, optional OCR setup, moved environments and startup failures.
- After setup, open the app with `assets/app/.venv/bin/python scripts/start.py`. The launcher opens the browser only after model readiness. `--headless` and `--port` are available when needed.
- Verify a running service with `assets/app/.venv/bin/python scripts/check.py`; `--smoke` additionally submits a fixed fictional example.

This package targets Apple Silicon on macOS 14+. Do not substitute dependency versions or claim support for another platform without testing it.

## Filtering workflow

Use the browser app for pasted text or a user-selected file. For a user-requested local file transformation without the browser, read [api.md](references/api.md); handle input bytes locally and save only the returned filtered copy.

Keep confidential source contents out of chat, agent messages and tool output. Do not print document text or base64 payloads to inspect them. User-provided local paths and metadata are enough to route a file through the local API.

The original stays unchanged. Copies simplify formatting and omit non-text content. Read [formats.md](references/formats.md) when handling files, unsupported formats, OCR or limits. Do not silently truncate a document to fit the limits.

Report the created copy's path and material converter warnings. A browser download request is not proof that a file was saved; verify the local result before reporting completion. Keep the result marked for human review: automated detection and OCR can miss identifying details, and indirect context can still identify someone.

## Boundaries

- Keep runtime model loading offline and the service bound to `127.0.0.1`; retain its host/origin checks. Use setup to obtain missing public assets, rather than a cloud fallback for input.
- On unavailable service, inference failure or invalid output, stop and return no filtered result. Never substitute the original input or a partial copy.
- No automatic forwarding to Jev, Laya, email or cloud services. A request to filter a file authorizes preparing that local copy, not publishing or sending it.
- English is the supported detection language. Do not describe output as guaranteed anonymous or claim clinical accuracy from the included synthetic tests.
