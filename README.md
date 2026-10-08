# Local Privacy Filter

A Codex skill and local browser app for filtering identifying details from **English text, CSV, Excel, Word and PDF files**. Scanned PDFs can use local OCR. You review the filtered copy before sharing it.

The app combines GLiNER2 PII detection and Microsoft Presidio. It runs on your Mac without a separate chat model. This repository contains source code; the first setup downloads the pinned public model and dependencies. Later filtering runs offline.

## Install the Codex skill

1. Download this repository as a ZIP from GitHub and extract it.
2. Double-click **Install Skill.command**. It copies the skill to Codex's skill folder and preserves any previous copy in a backup folder; it does not install the large runtime yet.
3. Open a new Codex chat (restart Codex if needed), then ask:

   > Use $local-privacy-filter to set up and open the local privacy filter on this Mac.

4. Let setup finish, then use the browser window that opens after the models are ready.

You can also ask Codex's skill installer to install the `skills/local-privacy-filter` folder from [this repository](https://github.com/adinwe/local-privacy-filter-skill). Install the skill into its final location **before** setting up its runtime. Moving a configured folder can break its local Python environment. Preserve that folder, install a fresh source copy in its final location, then set it up again.

## Use the browser app directly

If you do not use Codex, keep the extracted repository in a folder where it will stay. Double-click **Setup.command** once, then **Privacy Filter.command** to open the app. Keep the Terminal window open while filtering; **Control+C** stops it. Nothing starts at login.

First setup needs internet access, the `uv` package manager, and room for downloads. The setup message explains any missing prerequisite. Scanned-PDF support also needs Poppler and Tesseract with English recognition data; Codex can set up those optional tools through an existing Homebrew installation when requested.

## What to use it for

- Paste text, click **Redact text**, review the result, then copy it.
- Choose a file, click **Filter file**, then **Download filtered copy** and open it for review.
- Keep confidential input local while preparing a copy to share elsewhere.

The original file stays unchanged. Downloaded copies use fixed names such as `redacted.xlsx`. The app does not forward input or results to Jev, Laya or another service. Changing files or starting another request discards the previous prepared download.

A fictional example to try:

> Please email Alex at alex@example.com about the appointment.

Typical output replaces detected values with placeholders such as `[PERSON]` and `[EMAIL_ADDRESS]`. Detection varies with context. Automated filtering can miss names, indirect identifiers and OCR errors; review is required before sharing. This setup targets English and does not establish accuracy for clinical records or other languages.

## Supported files and limits

| Input | Filtered copy |
| --- | --- |
| CSV | A fresh UTF-8 CSV |
| Excel `.xlsx` | A rebuilt workbook with simplified content |
| Word `.docx` | A rebuilt Word document with simplified content |
| PDF | A rebuilt text PDF, using local OCR for scanned pages when available |

Resave legacy `.xls` and `.doc` files as `.xlsx` and `.docx` first. Copies simplify formatting and omit non-text content; formulas, images, annotations and advanced document features may not survive. Review both the text and structure of a downloaded copy.

- Up to **20 MiB per file** and **100,000 extracted characters per document**.
- PDFs: up to **50 pages**, with up to **20 pages processed by OCR**.
- Pasted text: up to **100,000 characters per request**.
- Encrypted, unsupported, unreadable or over-limit files return no filtered copy.

See [format details](skills/local-privacy-filter/references/formats.md) for the practical scope of each copy.

## Requirements

- **Apple Silicon Mac running macOS 14 or later**. This dependency set currently targets that platform.
- **16 GB RAM recommended**; large documents and OCR take longer.
- Allow **6 GB of free disk space for first setup**. The installed runtime is estimated at **2–3 GB**, with additional temporary download space and optional OCR-tool storage.
- Internet for initial setup; ordinary filtering is local and offline.

Setup uses managed Python **3.12** through `uv`, so it does not depend on macOS's system Python. Python packages and the model revision are pinned. The model and downloaded environments are excluded from GitHub and the source ZIP.

## Local processing and integration

The server listens only on `127.0.0.1`. The app has no external scripts, fonts, analytics or browser storage, and request access logs are disabled. Inputs and prepared outputs are handled in memory; copying uses the system clipboard and an explicit download saves a filtered copy. This does not promise secure memory erasure.

Applications can use the [local API](skills/local-privacy-filter/references/api.md) before sending a request to Jev, Laya or another service. These integrations are not configured automatically. A client must stop on filtering failure and forward only a reviewed result.

## Source and licenses

The original application and skill code use the [MIT license](LICENSE). Installed dependencies, model weights, OCR tools and fonts keep their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

The source package includes the app, pinned dependency list and its test suite. Large model files, environments, caches, local verification records and user documents are not included. [Installation details](skills/local-privacy-filter/references/installation.md) cover checks, startup and recovery after moving the app.
