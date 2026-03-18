from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

from ankismart.core.models import CardDraft, CardMetadata, RegenerateRequest
from ankismart.ui.card_preview_page import CardPreviewPage

_APP = QApplication.instance() or QApplication(sys.argv)


def _make_card(
    *,
    front: str,
    back: str,
    quality_flags: list[str] | None = None,
    source_document: str = "",
    strategy_id: str = "basic",
) -> CardDraft:
    return CardDraft(
        fields={"Front": front, "Back": back},
        note_type="Basic",
        deck_name="Default",
        tags=["ankismart"],
        metadata=CardMetadata(
            quality_flags=list(quality_flags or []),
            source_document=source_document,
            strategy_id=strategy_id,
        ),
    )


def _make_main_window() -> MagicMock:
    main = MagicMock()
    main.config = SimpleNamespace(
        language="zh",
        allow_duplicate=False,
        duplicate_scope="deck",
        duplicate_check_model=True,
        semantic_duplicate_threshold=0.9,
        anki_connect_url="",
        anki_connect_key="",
        proxy_url="",
        last_update_mode="create_or_update",
    )
    main.switch_to_preview = MagicMock()
    main.preview_page = MagicMock()
    return main


def test_card_preview_can_filter_only_low_quality_cards() -> None:
    page = CardPreviewPage(_make_main_window())
    page.load_cards(
        [
            _make_card(
                front="Q",
                back="A",
                quality_flags=["too_short"],
                source_document="sample.md",
            ),
            _make_card(front="Long enough question", back="Long enough answer"),
        ]
    )

    page._on_toggle_low_quality_filter(True)

    assert page._card_list.count() == 1


def test_regenerate_selected_cards_reuses_source_document(monkeypatch) -> None:
    page = CardPreviewPage(_make_main_window())
    page.load_cards(
        [
            _make_card(
                front="Question",
                back="Answer",
                source_document="sample.md",
                strategy_id="basic",
            )
        ]
    )
    captured: dict[str, RegenerateRequest] = {}
    monkeypatch.setattr(
        page,
        "_dispatch_regenerate_request",
        lambda request: captured.setdefault("request", request),
    )
    page._card_list.setCurrentRow(0)

    page._regenerate_selected_cards()

    assert captured["request"].scope == "selected_cards"
    assert captured["request"].source_documents == ["sample.md"]
