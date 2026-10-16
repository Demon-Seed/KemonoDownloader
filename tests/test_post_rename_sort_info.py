"""Tests for the Post Downloader's 'Rename & Sort by File order' option."""

from unittest.mock import MagicMock

from PyQt6.QtGui import QIcon

from kemonodownloader import post_downloader as pd
from kemonodownloader.kd_language import language_manager, translate


def make_tab(monkeypatch):
    monkeypatch.setattr("qtawesome.icon", lambda *a, **k: QIcon())
    monkeypatch.setattr("os.makedirs", MagicMock())
    parent = MagicMock()
    parent.cache_folder = "/tmp/cache_rn"
    parent.other_files_folder = "/tmp/other_rn"
    parent.settings_tab = MagicMock()
    return pd.PostDownloaderTab(parent)


def test_label_escapes_ampersand(qapp, monkeypatch):
    tab = make_tab(monkeypatch)
    # Qt swallows a lone "&" as a mnemonic marker, so the label escapes it as
    # "&&" to render a literal ampersand.
    assert tab.auto_rename_checkbox.text() == "Rename && Sort by File order"
    assert tab.auto_rename_checkbox.text().replace("&&", "&") == translate(
        "auto_rename"
    )


def test_info_button_shows_explanation(qapp, monkeypatch):
    tab = make_tab(monkeypatch)
    captured = {}

    def fake_information(parent, title, text):
        captured["parent"] = parent
        captured["title"] = title
        captured["text"] = text

    monkeypatch.setattr(pd.QMessageBox, "information", fake_information)

    tab.auto_rename_info_btn.click()

    assert captured["parent"] is tab
    assert captured["title"] == translate("auto_rename_info_title")
    text = captured["text"]
    assert "1_first.jpg" in text
    assert "starts at 1" in text


def test_info_button_disabled_in_fast_mode(qapp, monkeypatch):
    tab = make_tab(monkeypatch)
    tab.toggle_fast_mode(2)  # Qt.CheckState.Checked -> fast mode on
    assert tab.auto_rename_checkbox.isEnabled() is False
    assert tab.auto_rename_info_btn.isEnabled() is False


def test_post_info_text_translated_in_all_languages():
    original = language_manager.current_language
    try:
        for lang in language_manager.get_available_languages():
            language_manager.set_language(lang)
            text = translate("post_auto_rename_info_text")
            assert text and text != "post_auto_rename_info_text"
            assert len(text) > 50
    finally:
        language_manager.set_language(original)
