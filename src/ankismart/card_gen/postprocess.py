from __future__ import annotations

import json
import re
from pathlib import Path

from ankismart.core.errors import CardGenError, ErrorCode
from ankismart.core.logging import get_logger
from ankismart.core.models import CardDraft, CardMetadata
from ankismart.core.tracing import get_trace_id

logger = get_logger("card_gen.postprocess")

_CLOZE_PATTERN = re.compile(r"\{\{c\d+::.*?\}\}")


def parse_llm_output(raw: str) -> list[dict]:
    """Extract JSON array from LLM output, handling markdown code blocks."""
    trace_id = get_trace_id()
    text = raw.strip()

    # Strip markdown code block wrapper if present
    if text.startswith("```"):
        # Remove first line (```json or ```) and last line (```)
        lines = text.split("\n")
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()

    # Try to find JSON array in the text
    bracket_start = text.find("[")
    bracket_end = text.rfind("]")
    if bracket_start != -1 and bracket_end != -1 and bracket_end > bracket_start:
        text = text[bracket_start:bracket_end + 1]

    try:
        result = json.loads(text)
        if not isinstance(result, list):
            raise ValueError("Expected JSON array")
        return result
    except (json.JSONDecodeError, ValueError) as exc:
        raise CardGenError(
            f"Failed to parse LLM output as JSON: {exc}",
            code=ErrorCode.E_LLM_PARSE_ERROR,
            trace_id=trace_id,
        ) from exc


def validate_cloze(text: str) -> bool:
    """Check that text contains at least one valid cloze deletion."""
    return bool(_CLOZE_PATTERN.search(text))


def _has_required_fields(card: dict, note_type: str) -> bool:
    normalized_note_type = (note_type or "").strip()

    if normalized_note_type in {"Cloze", "AnkiSmart Cloze"} or normalized_note_type.startswith(
        "Cloze"
    ):
        text = str(card.get("Text", "")).strip()
        return bool(text) and validate_cloze(text)

    if normalized_note_type in {"Basic", "AnkiSmart Basic"} or normalized_note_type.startswith(
        "Basic"
    ):
        question = str(card.get("Front", "") or card.get("Question", "")).strip()
        answer = str(card.get("Back", "") or card.get("Answer", "")).strip()
        return bool(question and answer)

    return bool(card)


def _normalize_card_fields(card: dict, note_type: str) -> dict[str, object]:
    normalized = dict(card)
    normalized_note_type = (note_type or "").strip()

    if normalized_note_type in {"Basic", "AnkiSmart Basic"} or normalized_note_type.startswith(
        "Basic"
    ):
        front = str(normalized.get("Front", "") or normalized.get("Question", "")).strip()
        back = str(normalized.get("Back", "") or normalized.get("Answer", "")).strip()
        if front:
            normalized["Front"] = front
        if back:
            normalized["Back"] = back
        normalized.pop("Question", None)
        normalized.pop("Answer", None)

    return normalized


def _build_quality_flags(fields: dict[str, object], note_type: str) -> list[str]:
    normalized_note_type = (note_type or "").strip()
    question = str(fields.get("Front", "") or fields.get("Question", "")).strip()
    answer = str(fields.get("Back", "") or fields.get("Answer", "")).strip()
    text = str(fields.get("Text", "")).strip()

    flags: list[str] = []
    if normalized_note_type in {"Basic", "AnkiSmart Basic"} or normalized_note_type.startswith(
        "Basic"
    ):
        if len(question) < 3 or len(answer) < 3:
            flags.append("too_short")
        if question and answer and question == answer:
            flags.append("question_equals_answer")
    elif normalized_note_type.startswith("Cloze") and len(text) < 8:
        flags.append("too_short")
    return flags


def build_card_drafts(
    raw_cards: list[dict],
    deck_name: str,
    note_type: str,
    tags: list[str],
    trace_id: str,
    source_format: str = "",
    source_path: str = "",
    source_document: str = "",
    strategy_id: str = "",
) -> list[CardDraft]:
    """Convert raw LLM output dicts into validated CardDraft objects."""
    drafts: list[CardDraft] = []

    for i, card in enumerate(raw_cards):
        if not isinstance(card, dict):
            logger.warning("Skipping non-dict card", extra={"index": i, "trace_id": trace_id})
            continue

        if not _has_required_fields(card, note_type):
            logger.warning(
                "Skipping malformed card",
                extra={"index": i, "note_type": note_type, "trace_id": trace_id},
            )
            continue

        normalized_fields = _normalize_card_fields(card, note_type)
        quality_flags = _build_quality_flags(normalized_fields, note_type)
        resolved_source_document = source_document or (
            Path(source_path).name if source_path else ""
        )

        draft = CardDraft(
            trace_id=trace_id,
            deck_name=deck_name,
            note_type=note_type,
            fields=normalized_fields,
            tags=tags,
            metadata=CardMetadata(
                source_format=source_format,
                source_path=source_path,
                source_document=resolved_source_document,
                strategy_id=strategy_id,
                quality_flags=quality_flags,
            ),
        )
        drafts.append(draft)

    return drafts
