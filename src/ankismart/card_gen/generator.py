from __future__ import annotations

import inspect
import re
from pathlib import Path

from ankismart.card_gen.llm_client import LLMClient
from ankismart.card_gen.postprocess import build_card_drafts, parse_llm_output
from ankismart.card_gen.prompts import (
    BASIC_SYSTEM_PROMPT,
    CLOZE_SYSTEM_PROMPT,
    CONCEPT_SYSTEM_PROMPT,
    IMAGE_QA_SYSTEM_PROMPT,
    KEY_TERMS_SYSTEM_PROMPT,
    MULTIPLE_CHOICE_SYSTEM_PROMPT,
    OCR_CORRECTION_PROMPT,
    SINGLE_CHOICE_SYSTEM_PROMPT,
)
from ankismart.core.logging import get_logger
from ankismart.core.models import CardDraft, GenerateRequest, MediaItem
from ankismart.core.tracing import timed, trace_context

logger = get_logger("card_gen")

_STRATEGY_MAP: dict[str, tuple[str, str]] = {
    "basic": (BASIC_SYSTEM_PROMPT, "Basic"),
    "cloze": (CLOZE_SYSTEM_PROMPT, "Cloze"),
    "concept": (CONCEPT_SYSTEM_PROMPT, "Basic"),
    "key_terms": (KEY_TERMS_SYSTEM_PROMPT, "Basic"),
    "single_choice": (SINGLE_CHOICE_SYSTEM_PROMPT, "Basic"),
    "multiple_choice": (MULTIPLE_CHOICE_SYSTEM_PROMPT, "Basic"),
    "image_qa": (IMAGE_QA_SYSTEM_PROMPT, "Basic"),
    "image_occlusion": (IMAGE_QA_SYSTEM_PROMPT, "Basic"),
}

_STRATEGY_ALIASES = {
    "basic_qa": "basic",
    "fill_blank": "cloze",
    "concept_explanation": "concept",
}

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}


class CardGenerator:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    @staticmethod
    def _build_target_instruction(target_count: int, *, auto_target_count: bool) -> str:
        if target_count <= 0:
            return ""
        if auto_target_count:
            return (
                f"\n- Generate around {target_count} cards\n"
                "- cover all important knowledge points while keeping the output concise\n"
            )
        return f"\n- Generate exactly {target_count} cards\n"

    @staticmethod
    def _estimate_request_timeout(
        *,
        content_length: int,
        target_count: int,
        chunk_count: int = 1,
        auto_target_count: bool = False,
    ) -> float:
        base_timeout = 120.0
        length_bonus = min(240.0, max(0.0, content_length / 1500.0))
        target_bonus = min(180.0, max(0, target_count) * 10.0)
        chunk_bonus = min(180.0, max(0, chunk_count - 1) * 25.0)
        auto_bonus = 30.0 if auto_target_count else 0.0
        return base_timeout + length_bonus + target_bonus + chunk_bonus + auto_bonus

    def _chat_with_timeout(
        self, system_prompt: str, user_prompt: str, *, timeout: float | None
    ) -> str:
        chat_fn = self._llm.chat
        side_effect = getattr(chat_fn, "side_effect", None)
        signature_target = side_effect if callable(side_effect) else chat_fn

        supports_timeout = True
        try:
            parameters = inspect.signature(signature_target).parameters.values()
        except (TypeError, ValueError):
            parameters = ()

        if parameters:
            supports_timeout = False
            positional_count = 0
            for parameter in parameters:
                if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                    supports_timeout = True
                    break
                if parameter.name == "timeout":
                    supports_timeout = True
                    break
                if parameter.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                ):
                    positional_count += 1
            if positional_count >= 3:
                supports_timeout = True

        if supports_timeout and timeout is not None:
            return self._llm.chat(system_prompt, user_prompt, timeout=timeout)
        return self._llm.chat(system_prompt, user_prompt)

    @staticmethod
    def _hard_split_text(text: str, threshold: int) -> list[str]:
        value = str(text or "")
        if threshold <= 0 or len(value) <= threshold:
            return [value]

        parts: list[str] = []
        start = 0
        while start < len(value):
            parts.append(value[start : start + threshold])
            start += threshold
        return [part for part in parts if part]

    def _split_code_block(self, code_block_buffer: list[str], threshold: int) -> list[str]:
        if not code_block_buffer:
            return []

        if len(code_block_buffer) == 1 and "\n" in code_block_buffer[0]:
            raw_lines = code_block_buffer[0].splitlines()
            opening = raw_lines[0]
            if len(raw_lines) > 1 and raw_lines[-1].strip() == "```":
                closing = raw_lines[-1].strip()
                body = "\n".join(raw_lines[1:-1])
            else:
                closing = "```"
                body = "\n".join(raw_lines[1:])
        else:
            opening = code_block_buffer[0]
            closing = code_block_buffer[-1] if len(code_block_buffer) > 1 else "```"
            body = "\n\n".join(code_block_buffer[1:-1] if len(code_block_buffer) > 1 else [])

        if len(f"{opening}\n{body}\n{closing}") <= threshold:
            return [f"{opening}\n{body}\n{closing}".strip()]

        max_body_length = max(1, threshold - len(opening) - len(closing) - 2)
        return [
            f"{opening}\n{piece}\n{closing}"
            for piece in self._hard_split_text(body, max_body_length)
        ]

    def _split_markdown(self, markdown: str, threshold: int) -> list[str]:
        """Split markdown content into chunks at paragraph boundaries.

        Args:
            markdown: The markdown content to split
            threshold: Maximum character count per chunk

        Returns:
            List of markdown chunks, each under the threshold
        """
        if len(markdown) <= threshold:
            return [markdown]

        chunks = []
        current_chunk = []
        current_length = 0

        # Split by double newlines (paragraph boundaries)
        paragraphs = re.split(r"\n\n+", markdown)

        # Track if we're inside a code block or table
        in_code_block = False
        code_block_buffer = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Detect code block boundaries
            if para.startswith("```"):
                if not in_code_block:
                    # Start of code block
                    in_code_block = True
                    code_block_buffer = [para]
                    continue
                else:
                    # End of code block
                    in_code_block = False
                    code_block_buffer.append(para)
                    complete_block = "\n\n".join(code_block_buffer)

                    # If code block is too large, add it as separate chunk
                    if len(complete_block) > threshold:
                        if current_chunk:
                            chunks.append("\n\n".join(current_chunk))
                            current_chunk = []
                            current_length = 0
                        chunks.extend(self._split_code_block(code_block_buffer, threshold))
                    else:
                        # Try to add to current chunk
                        if current_length + len(complete_block) > threshold:
                            if current_chunk:
                                chunks.append("\n\n".join(current_chunk))
                            current_chunk = [complete_block]
                            current_length = len(complete_block)
                        else:
                            current_chunk.append(complete_block)
                            current_length += len(complete_block) + 2

                    code_block_buffer = []
                    continue

            # If inside code block, accumulate
            if in_code_block:
                code_block_buffer.append(para)
                continue

            para_length = len(para)

            # If single paragraph exceeds threshold, split it by sentences
            if para_length > threshold:
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # Split by sentences for very long paragraphs
                sentences = re.split(r"([.!?。！？]\s+)", para)
                sentence_chunk = []
                sentence_length = 0

                for i in range(0, len(sentences), 2):
                    sentence = sentences[i]
                    if i + 1 < len(sentences):
                        sentence += sentences[i + 1]

                    if sentence_length + len(sentence) > threshold:
                        if sentence_chunk:
                            chunks.append("".join(sentence_chunk))
                        if len(sentence) > threshold:
                            for piece in self._hard_split_text(sentence, threshold):
                                chunks.append(piece)
                            sentence_chunk = []
                            sentence_length = 0
                        else:
                            sentence_chunk = [sentence]
                            sentence_length = len(sentence)
                    else:
                        sentence_chunk.append(sentence)
                        sentence_length += len(sentence)

                if sentence_chunk:
                    chunks.append("".join(sentence_chunk))
                continue

            # Normal paragraph handling
            if current_length + para_length > threshold:
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                current_chunk = [para]
                current_length = para_length
            else:
                current_chunk.append(para)
                current_length += para_length + 2  # +2 for \n\n

        # Add remaining content
        if code_block_buffer:
            trailing_chunks = self._split_code_block(code_block_buffer, threshold)
            if len(trailing_chunks) == 1 and len(trailing_chunks[0]) <= threshold:
                if current_chunk and current_length + len(trailing_chunks[0]) <= threshold:
                    current_chunk.append(trailing_chunks[0])
                else:
                    if current_chunk:
                        chunks.append("\n\n".join(current_chunk))
                    current_chunk = trailing_chunks
            else:
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                chunks.extend(trailing_chunks)

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        logger.info(
            "Document split into chunks",
            extra={
                "original_length": len(markdown),
                "chunk_count": len(chunks),
                "threshold": threshold,
            },
        )

        return chunks

    def generate(self, request: GenerateRequest) -> list[CardDraft]:
        with trace_context(request.trace_id or None) as trace_id:
            with timed("card_generate_total"):
                normalized_strategy = _STRATEGY_ALIASES.get(request.strategy, request.strategy)
                strategy_info = _STRATEGY_MAP.get(normalized_strategy)
                if strategy_info is None:
                    strategy_info = _STRATEGY_MAP["basic"]
                    normalized_strategy = "basic"

                base_system_prompt, note_type = strategy_info
                markdown = request.markdown
                auto_target_count = bool(getattr(request, "auto_target_count", False))

                system_prompt = base_system_prompt
                system_prompt += self._build_target_instruction(
                    request.target_count,
                    auto_target_count=auto_target_count,
                )

                logger.info(
                    "Generating cards",
                    extra={
                        "strategy": normalized_strategy,
                        "strategy_requested": request.strategy,
                        "note_type": note_type,
                        "content_length": len(markdown),
                        "target_count": request.target_count,
                        "trace_id": trace_id,
                    },
                )

                # Check if auto-split is needed
                enable_split = getattr(request, "enable_auto_split", False)
                split_threshold = getattr(request, "split_threshold", 70000)

                all_drafts = []

                if enable_split and len(markdown) > split_threshold:
                    # Split document into chunks
                    chunks = self._split_markdown(markdown, split_threshold)
                    remaining_target = max(0, request.target_count)

                    logger.info(
                        "Processing document in chunks",
                        extra={
                            "chunk_count": len(chunks),
                            "trace_id": trace_id,
                        },
                    )

                    # Process each chunk
                    for i, chunk in enumerate(chunks, 1):
                        if (
                            remaining_target <= 0
                            and request.target_count > 0
                            and not auto_target_count
                        ):
                            break

                        logger.info(
                            f"Processing chunk {i}/{len(chunks)}",
                            extra={
                                "chunk_index": i,
                                "chunk_length": len(chunk),
                                "trace_id": trace_id,
                            },
                        )

                        chunk_system_prompt = base_system_prompt
                        chunk_target = 0
                        if remaining_target > 0:
                            chunks_left = len(chunks) - i + 1
                            base_target = remaining_target // max(1, chunks_left)
                            extra_target = 1 if remaining_target % max(1, chunks_left) else 0
                            chunk_target = max(1, base_target + extra_target)
                            chunk_system_prompt += self._build_target_instruction(
                                chunk_target,
                                auto_target_count=auto_target_count,
                            )

                        request_timeout = self._estimate_request_timeout(
                            content_length=len(chunk),
                            target_count=chunk_target or request.target_count,
                            chunk_count=len(chunks),
                            auto_target_count=auto_target_count,
                        )

                        # Call LLM for this chunk
                        with timed(f"llm_generate_chunk_{i}"):
                            raw_output = self._chat_with_timeout(
                                chunk_system_prompt,
                                chunk,
                                timeout=request_timeout,
                            )

                        # Parse and build card drafts for this chunk
                        raw_cards = parse_llm_output(raw_output)
                        chunk_drafts = build_card_drafts(
                            raw_cards=raw_cards,
                            deck_name=request.deck_name,
                            note_type=note_type,
                            tags=request.tags or ["ankismart"],
                            trace_id=trace_id,
                            source_path=request.source_path,
                            source_document=(
                                Path(request.source_path).name if request.source_path else ""
                            ),
                            strategy_id=normalized_strategy,
                        )

                        if (
                            chunk_target > 0
                            and not auto_target_count
                            and len(chunk_drafts) > chunk_target
                        ):
                            chunk_drafts = chunk_drafts[:chunk_target]

                        all_drafts.extend(chunk_drafts)
                        if remaining_target > 0:
                            remaining_target = max(0, remaining_target - len(chunk_drafts))
                            if auto_target_count and request.target_count > 0:
                                remaining_target = max(1, remaining_target)
                            if remaining_target <= 0 and not auto_target_count:
                                break

                    drafts = all_drafts
                else:
                    request_timeout = self._estimate_request_timeout(
                        content_length=len(markdown),
                        target_count=request.target_count,
                        auto_target_count=auto_target_count,
                    )
                    # Normal processing without split
                    with timed("llm_generate"):
                        raw_output = self._chat_with_timeout(
                            system_prompt,
                            markdown,
                            timeout=request_timeout,
                        )

                    # Parse and build card drafts
                    raw_cards = parse_llm_output(raw_output)
                    drafts = build_card_drafts(
                        raw_cards=raw_cards,
                        deck_name=request.deck_name,
                        note_type=note_type,
                        tags=request.tags or ["ankismart"],
                        trace_id=trace_id,
                        source_path=request.source_path,
                        source_document=(
                            Path(request.source_path).name if request.source_path else ""
                        ),
                        strategy_id=normalized_strategy,
                    )

                # Attach source image for image-based strategy
                if normalized_strategy in {"image_qa", "image_occlusion"} and request.source_path:
                    self._attach_image(drafts, request.source_path)

                if (
                    request.target_count > 0
                    and not auto_target_count
                    and len(drafts) > request.target_count
                ):
                    drafts = drafts[: request.target_count]

                logger.info(
                    "Card generation completed",
                    extra={
                        "card_count": len(drafts),
                        "trace_id": trace_id,
                    },
                )
                return drafts

    def _attach_image(self, drafts: list[CardDraft], source_path: str) -> None:
        """Attach source image to card fields and media."""
        p = Path(source_path)
        if p.suffix.lower() not in _IMAGE_EXTENSIONS:
            return
        filename = p.name
        img_tag = f'<img src="{filename}">'
        for draft in drafts:
            # Append image to Back field
            back = draft.fields.get("Back", "")
            draft.fields["Back"] = f"{back}<br>{img_tag}" if back else img_tag
            # Add as picture media
            draft.media.picture.append(
                MediaItem(
                    filename=filename,
                    path=str(p),
                    fields=["Back"],
                )
            )

    def correct_ocr_text(self, text: str) -> str:
        """Use LLM to correct OCR errors in text."""
        with timed("ocr_correction"):
            return self._llm.chat(OCR_CORRECTION_PROMPT, text)
