import os
import sys
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QSettings

from kemonodownloader import kd_paths

from kemonodownloader import kd_settings as ks
from kemonodownloader.kd_settings import SettingsTab


def test_get_default_base_directory_platforms(monkeypatch, tmp_path):
    # Windows
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    path = SettingsTab.get_default_base_directory(None)
    assert "Kemono Downloader" in path

    # macOS
    monkeypatch.setattr(sys, "platform", "darwin")
    path = SettingsTab.get_default_base_directory(None)
    assert "Library/Application Support" in path

    # Linux/other
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    path = SettingsTab.get_default_base_directory(None)
    assert "Kemono Downloader" in path


def test_show_only_found_filetypes_defaults_to_on_with_count():
    s = SettingsTab.__new__(SettingsTab)
    s.settings = {}

    assert s.get_show_only_found_filetypes() == "on_with_count"


def test_show_only_found_filetypes_reads_each_mode():
    s = SettingsTab.__new__(SettingsTab)

    for mode in ("off", "on", "on_with_count"):
        s.settings = {"show_only_found_filetypes": mode}
        assert s.get_show_only_found_filetypes() == mode


def test_show_only_found_filetypes_falls_back_on_junk():
    s = SettingsTab.__new__(SettingsTab)
    s.settings = {"show_only_found_filetypes": "yes please"}

    assert s.get_show_only_found_filetypes() == "off"


def test_save_and_load_settings_roundtrip(tmp_path):
    ini_path = str(tmp_path / "test_settings.ini")
    qs = QSettings(ini_path, QSettings.Format.IniFormat)

    # Build a fake SettingsTab-like object for save_settings
    s = SettingsTab.__new__(SettingsTab)
    s.qsettings = qs
    s.settings = {
        "base_folder_name": "My Folder",
        "base_directory": str(tmp_path / "base"),
        "simultaneous_downloads": 3,
        "language": "english",
        "creator_posts_max_attempts": 10,
        "post_data_max_retries": 2,
        "file_download_max_retries": 5,
        "api_request_max_retries": 1,
        "verbose_logging": False,
        "show_only_found_filetypes": "off",
        "proxy_type": "custom",
        "custom_proxy_url": "http://127.0.0.1:8080",
        "tor_path": "",
        "creator_filename_template": "{post_id}_{orig_name}",
        "creator_folder_strategy": "per_post",
        "font": "JetBrains Mono",
    }

    # Call save_settings which should write to the INI
    SettingsTab.save_settings(s)

    # Now load settings using a fresh object
    s2 = SettingsTab.__new__(SettingsTab)
    s2.qsettings = QSettings(ini_path, QSettings.Format.IniFormat)
    # Provide default_settings minimal shape referenced by load_settings
    s2.default_settings = s.settings.copy()
    loaded = SettingsTab.load_settings(s2)

    assert loaded["base_folder_name"] == s.settings["base_folder_name"]
    assert int(loaded["simultaneous_downloads"]) == s.settings["simultaneous_downloads"]
    assert loaded["proxy_type"] == s.settings["proxy_type"]


def make_tab(tmp_path):
    parent = SimpleNamespace()
    # Ensure parent has methods used when applying settings
    parent.base_folder = str(tmp_path / "base")
    parent.download_folder = str(tmp_path / "base" / "Downloads")
    parent.cache_folder = str(tmp_path / "base" / "Cache")
    parent.other_files_folder = str(tmp_path / "base" / "Other Files")
    parent.ensure_folders_exist = lambda: None
    parent.post_tab = SimpleNamespace()
    parent.creator_tab = SimpleNamespace()
    return ks.SettingsTab(parent)


def test_getters_and_temp_update(tmp_path):
    tab = make_tab(tmp_path)
    # initial getters
    assert isinstance(tab.get_creator_folder_strategy(), str)
    tab.update_temp_setting("simultaneous_downloads", 7)
    tab.update_simultaneous_downloads(7)
    assert tab.temp_settings["simultaneous_downloads"] == 7
    assert tab.download_slider.value() == 7
    assert tab.download_spinbox.value() == 7


def test_proxy_type_and_get_proxy_settings(tmp_path, monkeypatch):
    tab = make_tab(tmp_path)
    # custom proxy
    tab.temp_settings["use_proxy"] = True
    tab.temp_settings["proxy_type"] = "custom"
    tab.temp_settings["custom_proxy_url"] = "http://127.0.0.1:8080"
    proxies = tab.get_proxy_settings()
    assert proxies is not None
    assert proxies["http"].startswith("http")

    # tor proxy when tor not running -> error, never a direct connection
    tab.temp_settings["proxy_type"] = "tor"
    tab.tor_process = None
    with pytest.raises(ks.ProxyUnavailableError):
        tab.get_proxy_settings()

    # simulate tor process running but no socks package -> fallback to http
    class FakeProc:
        def state(self):
            return ks.QProcess.ProcessState.Running

    tab.tor_process = FakeProc()
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    proxies = tab.get_proxy_settings()
    assert "http" in proxies


def test_browse_sets_each_directory(tmp_path, monkeypatch):
    tab = make_tab(tmp_path)
    monkeypatch.setattr(
        "kemonodownloader.kd_settings.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(tmp_path),
    )

    tab.browse_directory()

    assert tab.directory_input.text() == str(tmp_path)

    # The program data folder is fixed now: the button opens it instead.
    opened = []
    monkeypatch.setattr(
        "kemonodownloader.kd_settings.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()),
    )
    tab.open_data_directory()

    assert [os.path.normpath(path) for path in opened] == [
        os.path.normpath(kd_paths.data_directory())
    ]
    assert tab.data_directory_input.text() == kd_paths.data_directory()
    assert tab.data_directory_input.isReadOnly() is True


def test_the_folder_group_has_no_open_buttons(tmp_path):
    """Both rows are just a path and a Browse button."""
    tab = make_tab(tmp_path)

    assert tab.browse_button.text() != ""
    assert tab.browse_data_button.text() != ""
    for removed in ("open_directory_button", "open_data_button"):
        assert not hasattr(tab, removed)


def test_reset_to_defaults_and_template_help(tmp_path, monkeypatch):
    tab = make_tab(tmp_path)
    # change some fields
    tab.data_directory_input.setText("X")
    tab.directory_input.setText(str(tmp_path))
    # Reset should restore defaults
    monkeypatch.setattr(
        "kemonodownloader.kd_settings.QMessageBox.information", lambda *a, **k: None
    )
    tab.reset_to_defaults()
    # The data folder is fixed, so the field reads it back rather than a
    # stored default.
    assert tab.data_directory_input.text() == kd_paths.data_directory()


def test_reset_also_restores_the_creator_templates(tmp_path, monkeypatch):
    """A15: the template fields and layout combos are defaults too."""
    tab = make_tab(tmp_path)
    monkeypatch.setattr(
        "kemonodownloader.kd_settings.QMessageBox.information", lambda *a, **k: None
    )

    tab.creator_filename_input.setText("{orig_name}")
    tab.creator_shared_filename_input.setText("{orig_name}")
    tab.creator_folder_name_input.setText("{post_title}")
    tab.creator_folder_strategy_combo.setCurrentIndex(
        tab.creator_folder_strategy_combo.findData("single_folder")
    )
    tab.creator_unique_filenames_combo.setCurrentIndex(
        tab.creator_unique_filenames_combo.findData(False)
    )

    tab.reset_to_defaults()

    defaults = tab.default_settings
    assert tab.creator_filename_input.text() == defaults["creator_filename_template"]
    assert (
        tab.creator_shared_filename_input.text()
        == defaults["creator_filename_template_shared"]
    )
    assert tab.creator_folder_name_input.text() == defaults["creator_folder_name_template"]
    assert (
        tab.creator_folder_strategy_combo.currentData()
        == defaults["creator_folder_strategy"]
    )
    assert (
        tab.creator_unique_filenames_combo.currentData()
        == defaults["creator_unique_filenames"]
    )


def test_B5_the_cached_proxy_answer_costs_no_qprocess_call(tmp_path):
    """Download threads read the proxy answer, never QProcess itself."""

    class FakeProcess:
        def state(self):
            from PyQt6.QtCore import QProcess

            return QProcess.ProcessState.Running

    tab = make_tab(tmp_path)
    tab.tor_process = FakeProcess()
    tab.temp_settings["use_proxy"] = True
    tab.temp_settings["proxy_type"] = "tor"
    # The GUI-thread snapshot (what a widget change or stateChanged does).
    tab._refresh_proxy_cache()

    def no_qt_off_thread():
        raise AssertionError("QProcess.state() was read off the GUI thread")

    tab.tor_process.state = no_qt_off_thread

    # Same signature, so the cached answer is returned without asking Qt.
    assert "http" in tab.get_proxy_settings()


def test_B5_editing_the_proxy_refreshes_the_cached_answer(tmp_path):
    tab = make_tab(tmp_path)
    tab.temp_settings["use_proxy"] = True
    tab.temp_settings["proxy_type"] = "custom"

    tab.update_temp_setting("custom_proxy_url", "1.2.3.4:8080")

    assert tab.get_proxy_settings() == {
        "http": "1.2.3.4:8080",
        "https": "1.2.3.4:8080",
    }
