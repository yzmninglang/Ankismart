from ankismart.ui.styles import (
    DARK_PAGE_BACKGROUND_HEX,
    DEFAULT_THEME_ACCENT_HEX,
    Colors,
    DarkColors,
    get_list_widget_palette,
    get_page_background_color,
    get_stylesheet,
    get_theme_accent_hex,
    get_theme_accent_text_hex,
    refresh_theme_accent_cache,
)


def test_light_stylesheet_contains_light_bg(monkeypatch):
    monkeypatch.setattr("ankismart.ui.styles._read_windows_accent_hex", lambda: "#123456")
    refresh_theme_accent_cache()
    css = get_stylesheet(dark=False)
    assert get_page_background_color(dark=False) in css
    assert "#123456" in css
    assert len(css) > 100


def test_dark_stylesheet_contains_dark_bg(monkeypatch):
    monkeypatch.setattr("ankismart.ui.styles._read_windows_accent_hex", lambda: "#123456")
    refresh_theme_accent_cache()
    css = get_stylesheet(dark=True)
    assert DARK_PAGE_BACKGROUND_HEX in css
    assert DarkColors.TEXT_PRIMARY in css
    assert get_theme_accent_text_hex(dark=True) in css
    assert len(css) > 100


def test_dark_colors_differ_from_light():
    assert Colors.BACKGROUND != DarkColors.BACKGROUND
    assert Colors.TEXT_PRIMARY != DarkColors.TEXT_PRIMARY
    assert Colors.SURFACE != DarkColors.SURFACE


def test_list_widget_palette_light_and_dark_are_distinct():
    light = get_list_widget_palette(dark=False)
    dark = get_list_widget_palette(dark=True)

    assert light.background != dark.background
    assert light.border != dark.border
    assert light.selected_background != dark.selected_background


def test_page_background_color_matches_theme(monkeypatch):
    monkeypatch.setattr("ankismart.ui.styles._read_windows_accent_hex", lambda: "#123456")
    refresh_theme_accent_cache()
    assert get_page_background_color(dark=False) != Colors.BACKGROUND
    assert get_page_background_color(dark=True) == DARK_PAGE_BACKGROUND_HEX


def test_theme_accent_uses_cached_default_before_refresh(monkeypatch):
    calls: list[str] = []

    def _reader() -> str:
        calls.append("read")
        return "#112233"

    monkeypatch.setattr("ankismart.ui.styles._read_windows_accent_hex", _reader)

    assert get_theme_accent_hex() == DEFAULT_THEME_ACCENT_HEX
    assert calls == []


def test_theme_accent_prefers_windows_system_color_after_refresh(monkeypatch):
    monkeypatch.setattr("ankismart.ui.styles._read_windows_accent_hex", lambda: "#112233")
    refresh_theme_accent_cache()

    light = get_list_widget_palette(dark=False)
    dark = get_list_widget_palette(dark=True)

    assert get_theme_accent_hex() == "#112233"
    assert light.selected_background == "rgba(17, 34, 51, 0.15)"
    assert dark.selected_background == "rgba(17, 34, 51, 0.30)"


def test_theme_accent_falls_back_to_default_when_system_color_missing(monkeypatch):
    monkeypatch.setattr("ankismart.ui.styles._read_windows_accent_hex", lambda: None)

    assert refresh_theme_accent_cache() == DEFAULT_THEME_ACCENT_HEX
    assert get_theme_accent_hex() == DEFAULT_THEME_ACCENT_HEX


def test_refresh_theme_accent_cache_reloads_system_color(monkeypatch):
    state = {"value": "#112233"}
    monkeypatch.setattr("ankismart.ui.styles._read_windows_accent_hex", lambda: state["value"])
    refresh_theme_accent_cache()
    assert get_theme_accent_hex() == "#112233"

    state["value"] = "#445566"
    assert get_theme_accent_hex() == "#112233"

    assert refresh_theme_accent_cache() == "#445566"
    assert get_theme_accent_hex() == "#445566"
