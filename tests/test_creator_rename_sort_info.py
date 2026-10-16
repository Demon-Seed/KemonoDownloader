"""Tests for the 'Rename & Sort by File order' option and its info button."""

from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd
from kemonodownloader.kd_language import language_manager, translate


def make_parent(tmp_path):
    class FakeTabs:
        def count(self):
            return 1

        def currentIndex(self):
            return 0

        def setTabEnabled(self, i, enabled):
            pass

    settings_tab = SimpleNamespace(
        settings_applied=SimpleNamespace(connect=lambda cb: None),
        language_changed=SimpleNamespace(connect=lambda cb: None),
    )
    return SimpleNamespace(
        cache_folder=str(tmp_path / "cache_rn"),
        other_files_folder=str(tmp_path / "other_rn"),
        download_folder=str(tmp_path / "download_rn"),
        settings_tab=settings_tab,
        tabs=FakeTabs(),
        status_label=SimpleNamespace(setText=lambda s: None),
        animate_button=lambda *a, **k: None,
    )


def test_auto_rename_label_is_simplified(tmp_path):
    tab = cd.CreatorDownloaderTab(make_parent(tmp_path))
    # Qt swallows a lone "&" as a mnemonic marker, so the label escapes it as
    # "&&" to render a literal ampersand.
    assert tab.creator_auto_rename_check.text() == "Rename && Sort by File order"
    assert tab.creator_auto_rename_check.text().replace("&&", "&") == translate(
        "auto_rename"
    )
    assert translate("auto_rename") == "Rename & Sort by File order"


def test_auto_rename_has_info_button(tmp_path):
    tab = cd.CreatorDownloaderTab(make_parent(tmp_path))
    assert hasattr(tab, "creator_auto_rename_info_btn")
    assert (
        tab.creator_auto_rename_info_btn.toolTip() == translate("auto_rename_info_title")
    )


def test_info_button_shows_explanation(tmp_path, monkeypatch):
    tab = cd.CreatorDownloaderTab(make_parent(tmp_path))
    captured = {}

    def fake_information(parent, title, text):
        captured["parent"] = parent
        captured["title"] = title
        captured["text"] = text

    monkeypatch.setattr(cd.QMessageBox, "information", fake_information)

    tab.creator_auto_rename_info_btn.click()

    assert captured["parent"] is tab
    assert captured["title"] == translate("auto_rename_info_title")

    text = captured["text"]
    # Per-post and shared-folder naming rules are both explained.
    assert "1_first.jpg" in text
    assert "1_1_first.jpg" in text
    # The shared-folder cases and the archive exception are named explicitly.
    assert "Skip Post Folder" in text
    assert "Always Post Folder for Compressed Files" in text


def test_info_keys_translated_in_all_languages():
    original = language_manager.current_language
    try:
        for lang in language_manager.get_available_languages():
            language_manager.set_language(lang)
            title = translate("auto_rename_info_title")
            text = translate("auto_rename_info_text")
            assert title and title != "auto_rename_info_title"
            assert text and text != "auto_rename_info_text"
            assert len(text) > 50
    finally:
        language_manager.set_language(original)


def test_info_button_disabled_while_downloading(tmp_path):
    tab = cd.CreatorDownloaderTab(make_parent(tmp_path))
    tab.set_downloading_ui_state(True)
    assert tab.creator_auto_rename_check.isEnabled() is False
    assert tab.creator_auto_rename_info_btn.isEnabled() is False
