"""Tests for Punctuation Matching Behavior in Settings.

The old lenient-keyword setting was replaced by wildcard syntax, so
Punctuation Matching Behavior is now the single global matching-rule setting.
It applies to plain and wildcard values in Skip Posts, Skip Files and
sorting; whole-tag matches and ``*`` edges are unaffected.
"""

from types import SimpleNamespace

from PyQt6.QtCore import QSettings

from kemonodownloader import kd_settings as ks
from kemonodownloader.kd_settings import SettingsTab


def make_tab(tmp_path):
    parent = SimpleNamespace()
    parent.base_folder = str(tmp_path / "base")
    parent.download_folder = str(tmp_path / "base" / "Downloads")
    parent.cache_folder = str(tmp_path / "base" / "Cache")
    parent.other_files_folder = str(tmp_path / "base" / "Other Files")
    parent.ensure_folders_exist = lambda: None
    parent.post_tab = SimpleNamespace()
    parent.creator_tab = SimpleNamespace()
    return ks.SettingsTab(parent)


def _stored_settings(tmp_path):
    return {
        "base_folder_name": "F",
        "base_directory": str(tmp_path / "base"),
        "simultaneous_downloads": 3,
        "language": "english",
        "creator_posts_max_attempts": 10,
        "post_data_max_retries": 2,
        "file_download_max_retries": 5,
        "api_request_max_retries": 1,
        "verbose_logging": False,
        "show_only_found_filetypes": "off",
        "proxy_type": "tor",
        "custom_proxy_url": "",
        "tor_path": "",
        "creator_filename_template": "{post_id}_{orig_name}",
        "creator_folder_strategy": "per_post",
        "creator_unique_filenames": "both",
        "creator_folder_name_template": "{post_title}",
        "font": "JetBrains Mono",
    }


def test_getter_defaults_to_default_and_accepts_each_mode():
    s = SettingsTab.__new__(SettingsTab)
    s.settings = {}

    assert s.get_punctuation_matching_rules() == "default"
    for mode in ks.PUNCTUATION_MATCHING_MODES:
        s.settings = {"punctuation_matching_rules": mode}
        assert s.get_punctuation_matching_rules() == mode

    s.settings = {"punctuation_matching_rules": "sometimes"}
    assert s.get_punctuation_matching_rules() == "default"
    assert not hasattr(SettingsTab, "get_lenient_keyword_matching")


def test_settings_roundtrip_through_qsettings(tmp_path):
    ini_path = str(tmp_path / "matching.ini")
    s = SettingsTab.__new__(SettingsTab)
    s.qsettings = QSettings(ini_path, QSettings.Format.IniFormat)
    s.settings = _stored_settings(tmp_path)
    s.settings["punctuation_matching_rules"] = "lenient"

    SettingsTab.save_settings(s)

    s2 = SettingsTab.__new__(SettingsTab)
    s2.qsettings = QSettings(ini_path, QSettings.Format.IniFormat)
    s2.default_settings = s.settings.copy()
    loaded = SettingsTab.load_settings(s2)

    assert loaded["punctuation_matching_rules"] == "lenient"
    assert "lenient_keyword_matching" not in loaded


def test_legacy_keyword_setting_is_ignored_and_removed(tmp_path):
    ini_path = str(tmp_path / "matching.ini")
    qs = QSettings(ini_path, QSettings.Format.IniFormat)
    qs.setValue("lenient_keyword_matching", "both")
    qs.setValue("punctuation_matching_rules", "lenient")
    qs.sync()

    s = SettingsTab.__new__(SettingsTab)
    s.qsettings = QSettings(ini_path, QSettings.Format.IniFormat)
    s.default_settings = _stored_settings(tmp_path)

    loaded = SettingsTab.load_settings(s)

    assert "lenient_keyword_matching" not in loaded
    assert loaded["punctuation_matching_rules"] == "lenient"

    s.settings = loaded
    SettingsTab.save_settings(s)
    assert s.qsettings.value("lenient_keyword_matching") is None


def test_invalid_stored_punctuation_mode_falls_back_on_load(tmp_path):
    ini_path = str(tmp_path / "matching.ini")
    qs = QSettings(ini_path, QSettings.Format.IniFormat)
    qs.setValue("punctuation_matching_rules", "yes")
    qs.sync()

    s = SettingsTab.__new__(SettingsTab)
    s.qsettings = QSettings(ini_path, QSettings.Format.IniFormat)
    s.default_settings = _stored_settings(tmp_path)

    loaded = SettingsTab.load_settings(s)

    assert loaded["punctuation_matching_rules"] == "default"


def test_widgets_are_punctuation_only(qtbot, tmp_path):
    tab = make_tab(tmp_path)
    qtbot.addWidget(tab)

    assert tab.punctuation_matching_rules_label.text() == ks.translate(
        "punctuation_matching_rules"
    )
    assert tab.punctuation_matching_rules_combo.currentData() == "default"
    assert [
        tab.punctuation_matching_rules_combo.itemText(i)
        for i in range(tab.punctuation_matching_rules_combo.count())
    ] == ["Default", "Relaxed"]
    assert tab.show_only_found_filetypes_label.text() == "Filetype Display:"
    assert [
        tab.show_only_found_filetypes_combo.itemText(i)
        for i in range(tab.show_only_found_filetypes_combo.count())
    ] == ["Show all", "Show found only", "Show found only (with counts)"]
    assert tab.creator_unique_filenames_label.text() == "Name Dedup:"
    assert not hasattr(tab, "lenient_keyword_matching_combo")
    assert not hasattr(tab, "lenient_keyword_matching_help_btn")
    assert ks.translate("keyword_matching_rules") == "keyword_matching_rules"
    # The help lives in the info-circle button; the combos have no tooltip.
    assert tab.punctuation_matching_rules_combo.toolTip() == ""
    assert tab.show_only_found_filetypes_combo.toolTip() == ""
    for button in (
        tab.punctuation_matching_help_btn,
        tab.filetype_display_help_btn,
    ):
        assert button.text() == ""
        assert not button.icon().isNull()
        assert button.toolTip() != ""


def test_help_box_explains_punctuation_in_both_contexts(qtbot, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(
        ks.QMessageBox,
        "information",
        lambda parent, title, text: shown.append((title, text)),
    )
    tab = make_tab(tmp_path)
    qtbot.addWidget(tab)

    tab.show_punctuation_matching_help()
    tab.show_filetype_display_help()

    assert shown[0][0] == ks.translate("punctuation_matching_help_title")
    assert "[JP]" in shown[0][1]
    assert "sorting value" in shown[0][1]
    assert shown[1][0] == ks.translate("filetype_display_help_title")
    assert "Show found only (with counts)" in shown[1][1]


def test_reset_restores_the_punctuation_default(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(ks.QMessageBox, "information", lambda *args, **kwargs: None)
    tab = make_tab(tmp_path)
    qtbot.addWidget(tab)

    tab.punctuation_matching_rules_combo.setCurrentIndex(
        tab.punctuation_matching_rules_combo.findData("lenient")
    )
    tab.reset_to_defaults()

    assert tab.punctuation_matching_rules_combo.currentData() == "default"


def test_apply_summary_lists_only_the_punctuation_row(qtbot, tmp_path):
    tab = make_tab(tmp_path)
    qtbot.addWidget(tab)
    tab.update_temp_setting("punctuation_matching_rules", "lenient")

    summary = tab._settings_summary(tab.temp_settings)

    assert ks.translate("punctuation_matching_rules") in summary
    assert ks.translate("punctuation_rules_relaxed") in summary
    assert ks.translate("keyword_matching_rules") not in summary

