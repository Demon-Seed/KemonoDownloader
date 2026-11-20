"""Tests for the two keyword-matching rules that live in Settings.

"Keyword Matching Rules" decides which keyword filters drop the whole-word
rule; "Punctuation Matching Rules" decides whether only enclosing punctuation
(brackets, CJK brackets, quotes) may delimit a keyword, or any punctuation at
its edge. Both are stored with the rest of the settings.
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


def test_getters_default_to_off_and_default():
    s = SettingsTab.__new__(SettingsTab)
    s.settings = {}

    assert s.get_lenient_keyword_matching() == "off"
    assert s.get_punctuation_matching_rules() == "default"


def test_getters_accept_each_mode_and_reject_junk():
    s = SettingsTab.__new__(SettingsTab)

    for mode in ks.LENIENT_KEYWORD_MODES:
        s.settings = {"lenient_keyword_matching": mode}
        assert s.get_lenient_keyword_matching() == mode
    for mode in ks.PUNCTUATION_MATCHING_MODES:
        s.settings = {"punctuation_matching_rules": mode}
        assert s.get_punctuation_matching_rules() == mode

    s.settings = {
        "lenient_keyword_matching": "sometimes",
        "punctuation_matching_rules": "sometimes",
    }
    assert s.get_lenient_keyword_matching() == "off"
    assert s.get_punctuation_matching_rules() == "default"



def test_settings_roundtrip_through_qsettings(tmp_path):
    ini_path = str(tmp_path / "matching.ini")
    s = SettingsTab.__new__(SettingsTab)
    s.qsettings = QSettings(ini_path, QSettings.Format.IniFormat)
    s.settings = _stored_settings(tmp_path)
    s.settings["lenient_keyword_matching"] = "both"
    s.settings["punctuation_matching_rules"] = "lenient"

    SettingsTab.save_settings(s)

    s2 = SettingsTab.__new__(SettingsTab)
    s2.qsettings = QSettings(ini_path, QSettings.Format.IniFormat)
    s2.default_settings = s.settings.copy()
    loaded = SettingsTab.load_settings(s2)

    assert loaded["lenient_keyword_matching"] == "both"
    assert loaded["punctuation_matching_rules"] == "lenient"


def test_invalid_stored_modes_fall_back_on_load(tmp_path):
    ini_path = str(tmp_path / "matching.ini")
    qs = QSettings(ini_path, QSettings.Format.IniFormat)
    qs.setValue("lenient_keyword_matching", "sometimes")
    qs.setValue("punctuation_matching_rules", "yes")
    qs.sync()

    s = SettingsTab.__new__(SettingsTab)
    s.qsettings = QSettings(ini_path, QSettings.Format.IniFormat)
    s.default_settings = _stored_settings(tmp_path)

    loaded = SettingsTab.load_settings(s)

    assert loaded["lenient_keyword_matching"] == "off"
    assert loaded["punctuation_matching_rules"] == "default"


def test_widgets_default_and_have_no_hover_dialog(qtbot, tmp_path):
    tab = make_tab(tmp_path)
    qtbot.addWidget(tab)

    assert tab.lenient_keyword_matching_label.text() == ks.translate(
        "keyword_matching_rules"
    )
    assert tab.lenient_keyword_matching_combo.currentData() == "off"
    assert [
        tab.lenient_keyword_matching_combo.itemText(i)
        for i in range(tab.lenient_keyword_matching_combo.count())
    ] == ["Default", "Relaxed (Posts)", "Relaxed (Files)", "Relaxed (Both)"]
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
    # The help lives in the info-circle button; the combos have no tooltip.
    assert tab.lenient_keyword_matching_combo.toolTip() == ""
    assert tab.punctuation_matching_rules_combo.toolTip() == ""
    assert tab.show_only_found_filetypes_combo.toolTip() == ""
    for button in (
        tab.lenient_keyword_matching_help_btn,
        tab.punctuation_matching_help_btn,
        tab.filetype_display_help_btn,
    ):
        # Icon-only, like the Creator tab's info buttons.
        assert button.text() == ""
        assert not button.icon().isNull()
        assert button.toolTip() != ""


def test_help_boxes_explain_each_setting(qtbot, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(
        ks.QMessageBox,
        "information",
        lambda parent, title, text: shown.append((title, text)),
    )
    tab = make_tab(tmp_path)
    qtbot.addWidget(tab)

    tab.show_keyword_matching_rules_help()
    tab.show_punctuation_matching_help()
    tab.show_filetype_display_help()

    assert shown[0][0] == ks.translate("keyword_matching_rules_help_title")
    assert "beanstoast" in shown[0][1]
    assert shown[1][0] == ks.translate("punctuation_matching_help_title")
    assert "[JP]" in shown[1][1]
    assert shown[2][0] == ks.translate("filetype_display_help_title")
    assert "Show found only (with counts)" in shown[2][1]


def test_reset_restores_the_defaults(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(ks.QMessageBox, "information", lambda *args, **kwargs: None)
    tab = make_tab(tmp_path)
    qtbot.addWidget(tab)

    tab.lenient_keyword_matching_combo.setCurrentIndex(
        tab.lenient_keyword_matching_combo.findData("both")
    )
    tab.punctuation_matching_rules_combo.setCurrentIndex(
        tab.punctuation_matching_rules_combo.findData("lenient")
    )

    tab.reset_to_defaults()

    assert tab.lenient_keyword_matching_combo.currentData() == "off"
    assert tab.punctuation_matching_rules_combo.currentData() == "default"


def test_apply_summary_lists_the_new_rows(qtbot, tmp_path):
    tab = make_tab(tmp_path)
    qtbot.addWidget(tab)
    tab.update_temp_setting("lenient_keyword_matching", "files")
    tab.update_temp_setting("punctuation_matching_rules", "lenient")

    summary = tab._settings_summary(tab.temp_settings)

    assert ks.translate("keyword_matching_rules") in summary
    assert ks.translate("keyword_matching_relaxed_files") in summary
    assert ks.translate("punctuation_matching_rules") in summary
    assert ks.translate("punctuation_rules_relaxed") in summary