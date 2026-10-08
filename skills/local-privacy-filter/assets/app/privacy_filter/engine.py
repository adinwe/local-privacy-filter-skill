"""Offline GLiNER2 + Presidio detection, with original character offsets.

Verified against gliner2 2.0.0 / presidio-analyzer 2.2.364. The upstream
GLiNER2 loader internally enables trust_remote_code for encoder construction.
We restrict its local assets to the built-in DeBERTa-v2 architecture, reject
auto_map and executable model files, and require safetensors. No remote model
implementation is permitted or needed. The loader is never given a Hub ID.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterator, Sequence

# Set before any GLiNER/Transformers import, rather than trusting saved config.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from presidio_analyzer import (  # noqa: E402
    AnalyzerEngine,
    EntityRecognizer,
    Pattern,
    PatternRecognizer,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import SpacyNlpEngine  # noqa: E402
from presidio_analyzer.predefined_recognizers import EmailRecognizer  # noqa: E402
from presidio_anonymizer import AnonymizerEngine  # noqa: E402
from presidio_anonymizer.entities import OperatorConfig  # noqa: E402


LABEL_MAP = {
    "person": "PERSON", "full_name": "PERSON", "first_name": "PERSON",
    "middle_name": "PERSON", "last_name": "PERSON",
    "date_of_birth": "DATE_OF_BIRTH",
    "email": "EMAIL_ADDRESS", "phone_number": "PHONE_NUMBER",
    "address": "LOCATION", "street_address": "LOCATION", "city": "LOCATION",
    "state_or_region": "LOCATION", "postal_code": "LOCATION", "country": "LOCATION",
    "government_id": "GOVERNMENT_ID", "national_id_number": "GOVERNMENT_ID",
    "passport_number": "PASSPORT", "drivers_license_number": "DRIVERS_LICENSE",
    "license_number": "LICENSE_NUMBER", "tax_id": "TAX_ID", "tax_number": "TAX_ID",
    "bank_account": "BANK_ACCOUNT", "account_number": "ACCOUNT_NUMBER",
    "routing_number": "ROUTING_NUMBER", "iban": "IBAN_CODE",
    "payment_card": "CREDIT_CARD", "card_number": "CREDIT_CARD",
    "card_expiry": "CARD_EXPIRY", "card_cvv": "CARD_CVV",
    "username": "USERNAME", "ip_address": "IP_ADDRESS",
    "account_id": "ACCOUNT_ID", "sensitive_account_id": "ACCOUNT_ID",
    "password": "PASSWORD", "secret": "SECRET", "api_key": "API_KEY",
    "access_token": "ACCESS_TOKEN", "recovery_code": "RECOVERY_CODE",
    "sensitive_date": "DATE_TIME", "document_date": "DATE_TIME",
    "expiration_date": "DATE_TIME", "transaction_date": "DATE_TIME",
}
SUPPORTED_LABELS = tuple(LABEL_MAP)
REVIEW_WARNING = (
    "Review the masked text before sharing: automated detection may miss "
    "identifiers or redact harmless text."
)
MAX_INPUT_CHARACTERS = 100_000


class PrivacyFilterError(RuntimeError):
    """Safe failure message: never embeds submitted text or a detector value."""


def _local_model_assets(model_path: str | Path) -> tuple[Path, int]:
    path = Path(model_path).expanduser().resolve()
    if not path.is_dir():
        raise PrivacyFilterError("The local model folder is missing.")
    required = (
        "config.json", "encoder_config/config.json", "model.safetensors",
        "tokenizer.json", "tokenizer_config.json",
    )
    if any(not (path / filename).is_file() for filename in required):
        raise PrivacyFilterError("The local model files are incomplete.")
    if any(p.suffix in {".py", ".bin", ".pt", ".pth", ".pkl"} for p in path.rglob("*")):
        raise PrivacyFilterError("Executable or pickle model artifacts are not permitted.")
    try:
        configs = [json.loads((path / filename).read_text()) for filename in required if filename.endswith("config.json")]
        if any(not isinstance(config, dict) or config.get("auto_map") for config in configs):
            raise PrivacyFilterError("Custom remote model implementations are not permitted.")
        encoder = configs[1]
        if encoder.get("model_type") != "deberta-v2":
            raise PrivacyFilterError("Only the verified built-in DeBERTa-v2 encoder is supported.")
        budget = encoder.get("max_position_embeddings")
        if type(budget) is not int or not 128 <= budget <= 512:
            raise PrivacyFilterError("The local encoder token limit is unsupported.")
        if configs[0].get("architecture", "span") != "span":
            raise PrivacyFilterError("This app requires the verified span model.")
    except PrivacyFilterError:
        raise
    except Exception:
        raise PrivacyFilterError("The local model configuration could not be verified.") from None
    return path, budget


class GLiNER2Recognizer(EntityRecognizer):
    """A real Presidio recognizer using GLiNER2's returned character spans."""

    def __init__(
        self,
        model: Any,
        threshold: float = 0.35,
        labels: Sequence[str] = SUPPORTED_LABELS,
        max_encoder_tokens: int = 512,
        chunk_tokens: int = 128,
        overlap_tokens: int = 64,
    ) -> None:
        if not 0 < threshold < 1:
            raise ValueError("threshold must be between zero and one")
        if not labels or any(label not in LABEL_MAP for label in labels):
            raise ValueError("labels must be supported model-card labels")
        if not 0 < overlap_tokens < chunk_tokens:
            raise ValueError("overlap_tokens must be positive and smaller than chunk_tokens")
        self.model = model
        self.threshold = threshold
        self.labels = tuple(dict.fromkeys(labels))
        self.max_encoder_tokens = max_encoder_tokens
        self.chunk_tokens = chunk_tokens
        self.overlap_tokens = overlap_tokens
        self.tokenizer = model.processor.tokenizer
        self.schema = model.create_schema().entities(list(self.labels)).build()
        super().__init__(
            supported_entities=sorted({LABEL_MAP[label] for label in self.labels}),
            name="LocalGLiNER2", supported_language="en", version="2.0.0",
        )

    def load(self) -> None:
        # The constructor receives an already-loaded local model.
        return None

    def _encoded_length(self, text: str) -> int:
        # Count exactly the schema markers, labels and text that inference uses.
        # Public processor API; strict errors prevent its fallback blank record.
        batch = self.model.processor.collate_fn_inference(
            [(text, copy.deepcopy(self.schema))], max_len=None,
            error_policy="raise", architecture="span",
        )
        return int(batch.input_ids.shape[1])

    def _chunks(self, text: str) -> Iterator[tuple[int, str]]:
        if not text.strip():
            return
        encoded = self.tokenizer(
            text, add_special_tokens=False, return_offsets_mapping=True,
            return_attention_mask=False, truncation=False,
        )
        offsets = encoded.get("offset_mapping")
        if not offsets:
            raise PrivacyFilterError("The text could not be tokenized safely.")
        if any(
            len(pair) != 2 or type(pair[0]) is not int or type(pair[1]) is not int
            or not 0 <= pair[0] < pair[1] <= len(text)
            for pair in offsets
        ):
            raise PrivacyFilterError("The tokenizer returned invalid offsets.")
        position = 0
        while position < len(offsets):
            stop = min(position + self.chunk_tokens, len(offsets))
            while True:
                start_char = 0 if position == 0 else offsets[position][0]
                end_char = len(text) if stop == len(offsets) else offsets[stop - 1][1]
                chunk = text[start_char:end_char]
                if self._encoded_length(chunk) <= self.max_encoder_tokens:
                    break
                if stop - position <= 1:
                    raise PrivacyFilterError("A text segment exceeds the safe encoder budget.")
                stop -= max(1, (stop - position) // 4)
            yield start_char, chunk
            if stop == len(offsets):
                break
            # Keep overlap even if schema overhead forced a smaller chunk.
            overlap = min(self.overlap_tokens, max(1, (stop - position) // 2))
            position = max(position + 1, stop - overlap)

    def analyze(self, text: str, entities: list[str], nlp_artifacts=None) -> list[RecognizerResult]:
        try:
            requested = set(entities)
            results = []
            for base_offset, chunk in self._chunks(text):
                result = self.model.extract_entities(
                    chunk, list(self.labels), threshold=self.threshold,
                    include_confidence=True, include_spans=True, max_len=None,
                )
                entity_map = result.get("entities") if isinstance(result, dict) else None
                if not isinstance(entity_map, dict):
                    raise PrivacyFilterError("The local detector returned an invalid result.")
                for label, values in entity_map.items():
                    if label not in self.labels or not isinstance(values, list):
                        raise PrivacyFilterError("The local detector returned an unsupported result.")
                    for value in values:
                        if not isinstance(value, dict):
                            raise PrivacyFilterError("The local detector did not return character spans.")
                        start, end, score = value.get("start"), value.get("end"), value.get("confidence")
                        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(chunk):
                            raise PrivacyFilterError("The local detector returned invalid offsets.")
                        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= 1:
                            raise PrivacyFilterError("The local detector returned an invalid score.")
                        if "text" in value and value["text"] != chunk[start:end]:
                            raise PrivacyFilterError("The local detector returned inconsistent offsets.")
                        entity_type = LABEL_MAP[label]
                        if entity_type in requested and score >= self.threshold:
                            results.append(RecognizerResult(
                                entity_type=entity_type, start=base_offset + start,
                                end=base_offset + end, score=float(score),
                                recognition_metadata={"recognizer_name": self.name, "recognizer_identifier": self.id},
                            ))
            return results
        except PrivacyFilterError:
            raise
        except Exception:
            raise PrivacyFilterError("Local detection failed; no masked output was produced.") from None


def merge_findings(findings: Sequence[dict], text_length: int) -> list[dict]:
    """Union overlapping/touching ranges; do not discard a wider low score span."""
    normalized = []
    for item in findings:
        start, end, score = item.get("start"), item.get("end"), item.get("score")
        label, source = item.get("entity_type"), item.get("source")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= text_length:
            raise PrivacyFilterError("A detector returned invalid offsets.")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= 1:
            raise PrivacyFilterError("A detector returned an invalid score.")
        if not isinstance(label, str) or not label or not isinstance(source, str):
            raise PrivacyFilterError("A detector returned invalid metadata.")
        normalized.append({"start": start, "end": end, "score": float(score), "labels": {label}, "sources": {source}})
    normalized.sort(key=lambda f: (f["start"], -f["end"]))
    merged = []
    for item in normalized:
        if merged and item["start"] <= merged[-1]["end"]:
            current = merged[-1]
            current["end"] = max(current["end"], item["end"])
            current["score"] = max(current["score"], item["score"])
            current["labels"].update(item["labels"])
            current["sources"].update(item["sources"])
        else:
            merged.append(item)
    return [
        {"entity_type": next(iter(f["labels"])) if len(f["labels"]) == 1 else "SENSITIVE_DATA",
         "start": f["start"], "end": f["end"], "score": round(f["score"], 6),
         "source": "+".join(sorted(f["sources"]))}
        for f in merged
    ]


class PrivacyFilter:
    def __init__(self, model_path: str | Path, spacy_model: str = "en_core_web_sm", threshold: float = 0.35) -> None:
        if not 0 < threshold < 1:
            raise ValueError("threshold must be between zero and one")
        path, encoder_budget = _local_model_assets(model_path)
        try:
            import spacy
            import torch
            from gliner2 import GLiNER2

            # Upstream warnings can include a problematic token. Suppress model
            # logging rather than recording any submitted text.
            logging.getLogger("gliner2").setLevel(logging.CRITICAL)
            torch.set_num_threads(min(4, os.cpu_count() or 1))
            model = GLiNER2.from_pretrained(
                str(path), map_location="cpu", local_files_only=True,
                use_flashdeberta=False,
            )
            model.to("cpu").eval()
            # Load explicitly: Presidio's default loader may auto-download an
            # absent spaCy package. An already-loaded NLP engine bypasses it.
            if not spacy.util.is_package(spacy_model) and not Path(spacy_model).is_dir():
                raise PrivacyFilterError("The installed English language model is missing.")
            nlp_engine = SpacyNlpEngine(models=[{"lang_code": "en", "model_name": spacy_model}])
            nlp_engine.nlp = {"en": spacy.load(spacy_model)}
            self.analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine, supported_languages=["en"],
                default_score_threshold=threshold, log_decision_process=False,
            )
            self.recognizer = GLiNER2Recognizer(model, threshold, max_encoder_tokens=encoder_budget)
            self.analyzer.registry.add_recognizer(self.recognizer)
            # Stock EmailRecognizer's FQDN validation invokes tldextract, whose
            # default extractor can fetch a suffix list. Reuse its regex/context
            # without external validation; favour detecting syntactic emails.
            self.analyzer.registry.remove_recognizer("EmailRecognizer", language="en")
            self.analyzer.registry.add_recognizer(PatternRecognizer(
                name="OfflineEmailRecognizer", supported_entity="EMAIL_ADDRESS",
                supported_language="en", patterns=EmailRecognizer.PATTERNS,
                context=EmailRecognizer.CONTEXT,
            ))
            self.analyzer.registry.add_recognizer(PatternRecognizer(
                supported_entity="PHONE_NUMBER", name="AustralianPhoneRule",
                supported_language="en", patterns=[
                    Pattern("AU mobile", r"(?<!\w)(?:\+?61[ .-]?|0)4\d{2}[ .-]?\d{3}[ .-]?\d{3}(?!\w)", 0.85),
                    Pattern("AU landline", r"(?<!\w)(?:\+?61[ .-]?|0)[2378][ .-]?\d{4}[ .-]?\d{4}(?!\w)", 0.85),
                ],
            ))
            self.anonymizer = AnonymizerEngine()
            self.threshold = threshold
        except PrivacyFilterError:
            raise
        except Exception:
            raise PrivacyFilterError("Local model initialization failed. Verify the installed files.") from None

    def redact(self, text: str) -> dict:
        if not isinstance(text, str):
            raise PrivacyFilterError("Input must be text.")
        if len(text) > MAX_INPUT_CHARACTERS:
            raise PrivacyFilterError("Input exceeds the 100,000-character limit.")
        try:
            results = self.analyzer.analyze(
                text=text, language="en", score_threshold=self.threshold,
                return_decision_process=False,
            ) if text.strip() else []
            findings = merge_findings([
                {"entity_type": result.entity_type, "start": result.start,
                 "end": result.end, "score": result.score,
                 "source": str((result.recognition_metadata or {}).get("recognizer_name", "Presidio"))}
                for result in results
            ], len(text))
            replacement_types = {finding["entity_type"] for finding in findings}
            masked = self.anonymizer.anonymize(
                text=text,
                analyzer_results=[RecognizerResult(
                    entity_type=f["entity_type"], start=f["start"], end=f["end"], score=f["score"],
                ) for f in findings],
                operators={label: OperatorConfig("replace", {"new_value": f"[{label}]"})
                           for label in replacement_types},
            ).text
            return {"redacted_text": masked, "findings": findings,
                    "counts": dict(sorted(Counter(f["entity_type"] for f in findings).items())),
                    "entity_count": len(findings), "warnings": [REVIEW_WARNING]}
        except PrivacyFilterError:
            raise
        except Exception:
            raise PrivacyFilterError("Local detection failed; no masked output was produced.") from None
