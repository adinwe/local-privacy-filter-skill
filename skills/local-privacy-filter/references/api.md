# Local API

Use the endpoints only on the selected `127.0.0.1` port. The default is `8787`. The server uses host/origin controls and no permissive CORS. Browser calls originate from the app; local non-browser clients can omit `Origin`.

Avoid proxies when contacting loopback. Never print raw input, output document bytes or base64 payloads in tool output. API failures produce no result; clients must not replace failure with the original file or forward anything downstream automatically.

## Readiness

`GET /health` must report:

- `service: "local-privacy-filter-v1"` and the expected `workspace_id` for this app copy.
- `ready: true`, `offline: true` and `feature_revision: "documents-v1"`.
- `supported_file_extensions`, file/text limits and `ocr_available`.

Prefer `scripts/check.py` to validate identity and readiness. A port accepting connections alone does not identify the intended service. `ocr_available: false` still allows text-based documents; scanned PDFs fail without a copy.

## Pasted text

`POST /redact`, `Content-Type: application/json`:

```json
{"text":"Please email Alex at alex@example.com."}
```

Up to **100,000 Unicode characters** per request. Success fields are `redacted_text`, `entity_count`, category `counts` and generic `warnings`. There are no original-text or original-offset fields in the public response.

The example is fictional. Do not use real confidential text in shell command arguments, tool-visible snippets or a smoke test.

## File copy

`POST /redact-file` accepts the binary body directly, up to **20 MiB**:

```text
Content-Type: application/octet-stream
X-File-Extension: csv
```

Allowed extension values are `csv`, `xlsx`, `docx` and `pdf`; a leading dot is accepted. Do not send a source filename. Multipart upload is not the endpoint's format.

Successful JSON fields:

| Field | Meaning |
| --- | --- |
| `content_base64` | Standard base64 encoding of the reconstructed filtered copy |
| `media_type`, `extension` | Generated file type |
| `filename` | Fixed name such as `redacted.docx` |
| `entity_count` | Replacement count |
| `units` | Number of processed text parts |
| `warnings` | Converter/review notes; not original document content |

Only decode and save after a valid successful response. The server returns no original or partial file field. Text and files share one detection worker; HTTP 429 means busy. Other failures return a safe `error` message.

## Local file client example

Use this pattern in a local script when the user asks Codex or a local Claude Code session to create a filtered file directly. Run it with the app's Python after verifying the service. Replace the fictional paths with authorized local paths; never print or attach the input bytes.

```python
import base64
import json
from pathlib import Path
import urllib.request

source = Path("example.docx")
output_dir = Path("filtered-output")
extension = source.suffix.lower().lstrip(".")
allowed = {"csv", "xlsx", "docx", "pdf"}
if extension not in allowed or not 0 < source.stat().st_size <= 20 * 1024 * 1024:
    raise SystemExit("Choose a supported file within the size limit.")

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
request = urllib.request.Request(
    "http://127.0.0.1:8787/redact-file",
    data=source.read_bytes(),
    headers={
        "Content-Type": "application/octet-stream",
        "X-File-Extension": extension,
    },
    method="POST",
)
try:
    with opener.open(request, timeout=600) as response:
        result = json.loads(response.read(29 * 1024 * 1024))
    out_extension = result["extension"]
    if out_extension not in allowed:
        raise ValueError("Invalid output type")
    filtered = base64.b64decode(result["content_base64"], validate=True)
    if not 0 < len(filtered) <= 20 * 1024 * 1024:
        raise ValueError("Invalid output size")
except Exception:
    raise SystemExit("Filtering failed. No copy was written.") from None

output_dir.mkdir(parents=True, exist_ok=True)
target = output_dir / ("redacted." + out_extension)
# Exclusive creation protects an existing reviewed copy from replacement.
with target.open("xb") as destination:
    destination.write(filtered)
print("Filtered copy created for review:", target)
for warning in result.get("warnings", []):
    print("Review note:", warning)
```

If the target exists, choose another output folder or a user-approved filename. Verify the created file before reporting completion. Open it for human review; a replacement count is not proof of anonymization. Configure Jev/Laya forwarding only when explicitly requested, and preserve this stop-on-failure behavior across tool arguments and retrieved context as well as visible text.
