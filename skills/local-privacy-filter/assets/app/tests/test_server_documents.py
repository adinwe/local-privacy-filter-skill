"""API isolation checks with synthetic bytes and stubbed models/converters."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


@dataclass
class StubDocumentResult:
    content: bytes
    media_type: str = "text/csv; charset=utf-8"
    extension: str = "csv"
    entity_count: int = 2
    warnings: list[str] | None = None
    units: int = 2

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = ["Review this filtered copy before sharing."]


class StubDocumentError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class StubPrivacyFilter:
    def __init__(self, model_path):
        self.model_path = model_path

    def redact(self, text):
        return {
            "redacted_text": text.replace("alex@example.com", "[EMAIL_ADDRESS]"),
            "entity_count": 1,
            "counts": {"EMAIL_ADDRESS": 1},
            "warnings": [],
        }


class DocumentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        namespace = "_local_privacy_document_api_tests"
        package = types.ModuleType(namespace)
        package.__path__ = [str(root / "privacy_filter")]
        engine = types.ModuleType(namespace + ".engine")
        engine.PrivacyFilter = StubPrivacyFilter
        documents = types.ModuleType(namespace + ".documents")
        documents.DocumentError = StubDocumentError
        documents.MAX_FILE_BYTES = 20 * 1024 * 1024
        documents.MAX_DOCUMENT_CHARS = 100_000
        documents.SUPPORTED_EXTENSIONS = frozenset({"csv", "xlsx", "docx", "pdf"})
        documents.SAFE_ERROR_MESSAGES = frozenset({"The document has too much text."})
        documents.ocr_available = lambda: True
        documents.filter_document = lambda *_args: None
        spec = importlib.util.spec_from_file_location(
            namespace + ".server", root / "privacy_filter" / "server.py"
        )
        cls.server = importlib.util.module_from_spec(spec)
        # Use a private package namespace so engine tests and real model modules
        # are untouched, even when unittest discovery runs everything together.
        with patch.dict(
            sys.modules,
            {
                namespace: package,
                namespace + ".engine": engine,
                namespace + ".documents": documents,
                namespace + ".server": cls.server,
            },
        ):
            spec.loader.exec_module(cls.server)

    def setUp(self):
        self.convert_patch = patch.object(
            self.server,
            "filter_document",
            return_value=StubDocumentResult(b"name,email\n[PERSON],[EMAIL_ADDRESS]\n"),
        )
        self.convert = self.convert_patch.start()
        self.client = TestClient(self.server.app, base_url="http://127.0.0.1:8787")
        self.client.__enter__()
        self.headers = {
            "Content-Type": "application/octet-stream",
            "X-File-Extension": "csv",
        }

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.convert_patch.stop()

    def upload(self, content=b"name,email\nAlex,alex@example.com\n", headers=None):
        return self.client.post(
            "/redact-file", content=content, headers=headers or self.headers
        )

    def assert_no_result(self, response, status):
        self.assertEqual(response.status_code, status)
        self.assertNotIn("content_base64", response.json())
        self.assertNotIn("synthetic-private-tag", response.text)
        self.assertNotIn("alex@example.com", response.text)
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_success_has_only_filtered_content_and_fixed_filename(self):
        response = self.upload(
            headers={**self.headers, "X-File-Name": "synthetic-private-tag.csv"}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["filename"], "redacted.csv")
        self.assertEqual(payload["extension"], "csv")
        self.assertEqual(payload["media_type"], "text/csv; charset=utf-8")
        filtered = base64.b64decode(payload["content_base64"], validate=True)
        self.assertNotIn(b"alex@example.com", filtered)
        self.assertNotIn("synthetic-private-tag", response.text)
        self.assertNotIn("original_text", payload)
        self.assertNotIn("original_filename", payload)
        self.assertEqual(self.convert.call_args.args[1], "csv")
        self.assertTrue(callable(self.convert.call_args.args[2]))

    def test_health_exposes_current_document_capabilities(self):
        payload = self.client.get("/health").json()
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["feature_revision"], "documents-v1")
        self.assertEqual(payload["supported_file_extensions"], ["csv", "docx", "pdf", "xlsx"])
        self.assertEqual(payload["max_file_bytes"], 20 * 1024 * 1024)
        self.assertEqual(payload["max_document_characters"], 100_000)
        self.assertTrue(payload["ocr_available"])

    def test_leading_dot_and_uppercase_extension_are_normalized(self):
        result = self.upload(headers={**self.headers, "X-File-Extension": ".CSV"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.convert.call_args.args[1], "csv")

    def test_declared_oversize_file_rejected_before_converter(self):
        response = self.upload(
            content=b"synthetic-private-tag",
            headers={**self.headers, "Content-Length": str(self.server.MAX_FILE_BYTES + 1)},
        )
        self.assert_no_result(response, 413)
        self.convert.assert_not_called()

    def test_chunked_body_cannot_bypass_size_boundary(self):
        with patch.object(self.server, "MAX_FILE_BYTES", 32):
            response = self.upload(content=iter([b"a" * 16, b"b" * 17]))
        self.assert_no_result(response, 413)
        self.convert.assert_not_called()

    def test_exact_body_boundary_is_accepted(self):
        self.convert.return_value = StubDocumentResult(b"filtered")
        with patch.object(self.server, "MAX_FILE_BYTES", 32):
            response = self.upload(content=b"a" * 32)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.convert.call_args.args[0]), 32)

    def test_foreign_origin_host_and_fetch_site_are_blocked(self):
        for extra, status in (
            ({"Origin": "https://example.invalid"}, 403),
            ({"Host": "example.invalid"}, 400),
            ({"Sec-Fetch-Site": "cross-site"}, 403),
        ):
            with self.subTest(extra=extra):
                response = self.upload(headers={**self.headers, **extra})
                self.assertEqual(response.status_code, status)
                self.assertNotIn("alex@example.com", response.text)
                self.convert.assert_not_called()

    def test_same_local_origin_can_filter(self):
        response = self.upload(
            headers={**self.headers, "Origin": "http://127.0.0.1:8787"}
        )
        self.assertEqual(response.status_code, 200)

    def test_wrong_content_type_bad_extension_and_empty_file_fail(self):
        for content, extra, status in (
            (b"synthetic-private-tag", {"Content-Type": "multipart/form-data"}, 415),
            (b"synthetic-private-tag", {"X-File-Extension": "synthetic-private-tag.csv"}, 400),
            (b"", {}, 400),
        ):
            with self.subTest(extra=extra):
                response = self.upload(content=content, headers={**self.headers, **extra})
                self.assert_no_result(response, status)
                self.convert.assert_not_called()

    def test_busy_shared_worker_refuses_new_file(self):
        previous = self.server.app.state.inference_lock
        self.server.app.state.inference_lock = types.SimpleNamespace(locked=lambda: True)
        try:
            response = self.upload()
        finally:
            self.server.app.state.inference_lock = previous
        self.assert_no_result(response, 429)
        self.convert.assert_not_called()

    def test_processing_failure_returns_no_partial_or_original(self):
        self.convert.side_effect = RuntimeError("synthetic-private-tag")
        response = self.upload(content=b"synthetic-private-tag")
        self.assert_no_result(response, 503)

    def test_only_allowlisted_document_errors_are_exposed(self):
        self.convert.side_effect = StubDocumentError("The document has too much text.", 413)
        response = self.upload()
        self.assert_no_result(response, 413)
        self.assertEqual(response.json()["error"], "The document has too much text.")
        self.convert.side_effect = StubDocumentError("synthetic-private-tag", 500)
        response = self.upload()
        self.assert_no_result(response, 400)
        self.assertEqual(response.json()["error"], "This file could not be filtered. No result is available.")

    def test_invalid_or_oversize_converter_result_fails_closed(self):
        for result in (
            StubDocumentResult(b"filtered", extension="html"),
            StubDocumentResult(b"filtered", entity_count=-1),
            StubDocumentResult(b"filtered", warnings=[{"private": "synthetic-private-tag"}]),
        ):
            with self.subTest(result_type=type(result).__name__):
                self.convert.return_value = result
                self.assert_no_result(self.upload(), 503)
        self.convert.return_value = StubDocumentResult(b"f" * 33)
        with patch.object(self.server, "MAX_FILE_BYTES", 32):
            self.assert_no_result(self.upload(content=b"test"), 503)


if __name__ == "__main__":
    unittest.main()
