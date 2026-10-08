"""Synthetic privacy-boundary tests; no private records or model downloads."""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from privacy_filter.engine import (
    GLiNER2Recognizer,
    LABEL_MAP,
    PrivacyFilter,
    PrivacyFilterError,
    SUPPORTED_LABELS,
    _local_model_assets,
    merge_findings,
)
from presidio_analyzer import RecognizerResult
from presidio_anonymizer import AnonymizerEngine


class FakeProcessor:
    def __init__(self, overhead=30):
        self.overhead = overhead
        self.lengths = []

    def tokenizer(self, text, **kwargs):
        assert kwargs["truncation"] is False
        return {"offset_mapping": [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]}

    def collate_fn_inference(self, batch, **kwargs):
        assert kwargs["error_policy"] == "raise"
        assert kwargs["max_len"] is None
        text, schema = batch[0]
        length = self.overhead + len(schema["entities"]) + len(text.split())
        self.lengths.append(length)
        return SimpleNamespace(input_ids=SimpleNamespace(shape=(1, length)))


class FakeSchema:
    def entities(self, labels):
        self.labels = labels
        return self

    def build(self):
        return {"entities": self.labels}


class FakeModel:
    def __init__(self, values=(), overhead=30):
        self.values = values
        self.processor = FakeProcessor(overhead)
        self.calls = []
        self.custom_result = None
        self.error = None

    def create_schema(self):
        return FakeSchema()

    def extract_entities(self, text, labels, **kwargs):
        self.calls.append(text)
        assert kwargs["include_confidence"] and kwargs["include_spans"]
        assert kwargs["max_len"] is None
        if self.error:
            raise self.error
        if self.custom_result is not None:
            return self.custom_result
        return {"entities": {"full_name": [
            {"text": match.group(), "start": match.start(), "end": match.end(), "confidence": 0.9}
            for value in self.values for match in re.finditer(re.escape(value), text)
        ]}} if "full_name" in labels else {"entities": {}}

    def to(self, device):
        assert device == "cpu"
        return self

    def eval(self):
        return self


def filter_with_results(results):
    instance = PrivacyFilter.__new__(PrivacyFilter)
    instance.threshold = 0.35
    instance.analyzer = SimpleNamespace(analyze=lambda **kwargs: results)
    instance.anonymizer = AnonymizerEngine()
    return instance


def result(label, start, end, score=0.9, source="Synthetic"):
    return RecognizerResult(label, start, end, score, recognition_metadata={"recognizer_name": source})


def fake_assets(directory, **encoder_changes):
    root = Path(directory)
    (root / "encoder_config").mkdir()
    (root / "config.json").write_text(json.dumps({"architecture": "span"}))
    encoder = {"model_type": "deberta-v2", "max_position_embeddings": 512, **encoder_changes}
    (root / "encoder_config/config.json").write_text(json.dumps(encoder))
    (root / "tokenizer_config.json").write_text(json.dumps({"tokenizer_class": "DebertaV2Tokenizer"}))
    (root / "tokenizer.json").write_text("{}")
    (root / "model.safetensors").write_bytes(b"synthetic-test-placeholder")
    return root


class RedactionTests(unittest.TestCase):
    def test_overlapping_wider_low_score_span_is_not_lost(self):
        text = "Leah Stone: the report is ready."
        output = filter_with_results([
            result("PERSON", 0, 4, 0.95), result("PERSON", 0, 10, 0.4),
        ]).redact(text)
        self.assertEqual(output["redacted_text"], "[PERSON]: the report is ready.")
        self.assertEqual(output["entity_count"], 1)
        self.assertEqual(output["findings"][0]["end"], 10)

    def test_cross_type_overlap_redacts_entire_union(self):
        output = filter_with_results([
            result("PERSON", 0, 2), result("EMAIL_ADDRESS", 0, 14),
        ]).redact("jo@example.org is the contact.")
        self.assertEqual(output["redacted_text"], "[SENSITIVE_DATA] is the contact.")

    def test_repeated_values_use_each_actual_offset(self):
        text = "Leah Stone met Leah Stone. The report is ready."
        starts = [m.start() for m in re.finditer("Leah Stone", text)]
        output = filter_with_results([result("PERSON", start, start + 10) for start in starts]).redact(text)
        self.assertEqual(output["redacted_text"], "[PERSON] met [PERSON]. The report is ready.")
        self.assertEqual(output["counts"], {"PERSON": 2})
        self.assertEqual([f["start"] for f in output["findings"]], starts)
        self.assertTrue(all(set(f) == {"entity_type", "start", "end", "score", "source"} for f in output["findings"]))

    def test_unicode_offsets_are_python_characters(self):
        text = "🧠 Zoë Martin sent the report."
        start = text.index("Zoë")
        output = filter_with_results([result("PERSON", start, start + 10)]).redact(text)
        self.assertEqual(output["redacted_text"], "🧠 [PERSON] sent the report.")
        self.assertEqual(output["findings"][0]["start"], 2)

    def test_chained_and_touching_overlaps_union(self):
        rows = [{"entity_type": "PERSON", "start": start, "end": end, "score": 0.8, "source": "Synthetic"}
                for start, end in [(7, 12), (0, 4), (3, 8), (12, 14)]]
        self.assertEqual([(f["start"], f["end"]) for f in merge_findings(rows, 20)], [(0, 14)])

    def test_benign_and_whitespace_text_is_preserved(self):
        self.assertEqual(filter_with_results([]).redact("The report is ready.")["redacted_text"], "The report is ready.")
        self.assertEqual(filter_with_results([]).redact(" \n\t")["redacted_text"], " \n\t")

    def test_invalid_detector_offsets_fail_closed(self):
        with self.assertRaises(PrivacyFilterError):
            filter_with_results([result("PERSON", 0, 999)]).redact("Leah Stone")

    def test_backend_failure_does_not_echo_submitted_value(self):
        engine = filter_with_results([])
        def broken(**kwargs):
            raise RuntimeError("Leah Stone backend exception")
        engine.analyzer = SimpleNamespace(analyze=broken)
        with self.assertRaises(PrivacyFilterError) as caught:
            engine.redact("Leah Stone")
        self.assertNotIn("Leah Stone", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_input_limit_rejects_instead_of_truncating(self):
        with self.assertRaises(PrivacyFilterError):
            filter_with_results([]).redact("x" * 100_001)


class RecognizerTests(unittest.TestCase):
    def test_all_42_modelcard_labels_are_present(self):
        self.assertEqual(len(SUPPORTED_LABELS), 42)
        self.assertEqual(set(SUPPORTED_LABELS), set(LABEL_MAP))

    def test_long_document_name_crosses_initial_chunk_boundary(self):
        text = " ".join(["neutral"] * 7 + ["Leah", "Stone"] + ["neutral"] * 20 + ["Leah", "Stone"])
        model = FakeModel(["Leah Stone"])
        recognizer = GLiNER2Recognizer(model, labels=["full_name"], chunk_tokens=8, overlap_tokens=4)
        found = recognizer.analyze(text, ["PERSON"])
        merged = merge_findings([
            {"entity_type": f.entity_type, "start": f.start, "end": f.end, "score": f.score, "source": "Synthetic"}
            for f in found
        ], len(text))
        expected = [(m.start(), m.end()) for m in re.finditer("Leah Stone", text)]
        self.assertEqual([(f["start"], f["end"]) for f in merged], expected)
        self.assertGreater(len(model.calls), 1)

    def test_full_schema_overhead_forces_smaller_chunks_without_losing_tail(self):
        text = " ".join(["neutral"] * 30 + ["Leah", "Stone"])
        model = FakeModel(["Leah Stone"], overhead=509)
        recognizer = GLiNER2Recognizer(model, labels=["full_name"], chunk_tokens=12, overlap_tokens=4)
        found = recognizer.analyze(text, ["PERSON"])
        self.assertTrue(any(f.start == text.index("Leah Stone") and f.end == len(text) for f in found))
        self.assertTrue(all(len(call.split()) + 510 <= 512 for call in model.calls))
        self.assertTrue(any(length > 512 for length in model.processor.lengths))

    def test_impossible_single_token_budget_prevents_inference(self):
        model = FakeModel(overhead=512)
        recognizer = GLiNER2Recognizer(model, labels=["full_name"], chunk_tokens=8, overlap_tokens=4)
        with self.assertRaises(PrivacyFilterError):
            recognizer.analyze("identifier", ["PERSON"])
        self.assertEqual(model.calls, [])

    def test_bad_model_span_and_missing_confidence_fail_closed(self):
        for span in [{"start": -1, "end": 4, "confidence": 0.8},
                     {"start": 0, "end": 4},
                     {"start": 0, "end": 4, "confidence": float("nan")},
                     {"start": True, "end": 4, "confidence": 0.8},
                     {"start": 0, "end": 4, "confidence": 0.8, "text": "Wrong"}]:
            with self.subTest(span=span):
                model = FakeModel()
                model.custom_result = {"entities": {"full_name": [span]}}
                recognizer = GLiNER2Recognizer(model, labels=["full_name"])
                with self.assertRaises(PrivacyFilterError):
                    recognizer.analyze("Leah Stone", ["PERSON"])

    def test_recognizer_failure_is_sanitized(self):
        model = FakeModel()
        model.error = RuntimeError("Leah Stone secret")
        with self.assertRaises(PrivacyFilterError) as caught:
            GLiNER2Recognizer(model, labels=["full_name"]).analyze("Leah Stone", ["PERSON"])
        self.assertNotIn("Leah", str(caught.exception))


class LocalAssetTests(unittest.TestCase):
    def test_missing_local_model_rejected(self):
        with self.assertRaises(PrivacyFilterError):
            _local_model_assets("/nonexistent-synthetic-test-model")

    def test_safetensors_and_builtin_config_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fake_assets(directory)
            self.assertEqual(_local_model_assets(root)[1], 512)
            (root / "model.safetensors").unlink()
            with self.assertRaises(PrivacyFilterError):
                _local_model_assets(root)

    def test_remote_code_map_and_pickle_artifacts_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fake_assets(directory, auto_map={"AutoModel": "custom.Model"})
            with self.assertRaises(PrivacyFilterError):
                _local_model_assets(root)
        with tempfile.TemporaryDirectory() as directory:
            root = fake_assets(directory)
            (root / "pytorch_model.bin").write_bytes(b"synthetic")
            with self.assertRaises(PrivacyFilterError):
                _local_model_assets(root)

    def test_real_presidio_default_rules_and_australian_phone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fake_assets(directory)
            with patch("gliner2.GLiNER2.from_pretrained", return_value=FakeModel()):
                engine = PrivacyFilter(root)
            output = engine.redact("Please call 0412 345 678 or write synthetic.person@example.com. The report is ready.")
            self.assertNotIn("0412 345 678", output["redacted_text"])
            self.assertNotIn("synthetic.person@example.com", output["redacted_text"])
            self.assertIn("The report is ready.", output["redacted_text"])
            self.assertGreaterEqual(output["entity_count"], 2)


if __name__ == "__main__":
    unittest.main()
