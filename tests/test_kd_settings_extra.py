import importlib
import os
import subprocess
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QByteArray, QProcess

from kemonodownloader import kd_paths
from PyQt6.QtWidgets import QMessageBox


def make_parent():
    class MockParent:
        def __init__(self):
            self.base_folder = "base"
            self.download_folder = os.path.join("base", "Downloads")
            self.cache_folder = os.path.join("base", "Cache")
            self.other_files_folder = os.path.join("base", "Other Files")

        def log(self, msg):
            pass

        def ensure_folders_exist(self):
            pass

    return MockParent()


def test_confirm_and_apply_no_response(qapp, monkeypatch):
    from kemonodownloader.kd_settings import SettingsTab

    parent = make_parent()

    # Simulate user clicking 'No' on confirmation
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )

    st = SettingsTab(parent)
    orig = st.settings["base_folder_name"]
    st.temp_settings["base_folder_name"] = "changed"

    st.confirm_and_apply_settings()
    assert st.settings["base_folder_name"] == orig


def test_apply_uses_the_save_and_data_directories(qapp, monkeypatch, tmp_path):
    """Posts land in the Save Directory; the app's files in the Data Directory.

    The old "<save>/<folder name>/Downloads" layer is gone, and Cache/Other
    Files no longer live under the save folder at all.
    """
    from kemonodownloader import kd_paths
    from kemonodownloader.kd_settings import SettingsTab

    parent = make_parent()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    st = SettingsTab(parent)
    try:
        save_dir = str(tmp_path / "posts")
        # A typed data folder is ignored now: the location is fixed.
        st.temp_settings["base_directory"] = save_dir
        st.temp_settings["data_directory"] = str(tmp_path / "appdata")

        st.confirm_and_apply_settings()

        assert parent.download_folder == save_dir
        assert parent.cache_folder == kd_paths.cache_dir()
        assert parent.other_files_folder == kd_paths.other_files_dir()
        assert st.settings["data_directory"] == kd_paths.data_directory()
    finally:
        st.deleteLater()


def test_A7_old_boolean_dedup_settings_are_migrated():
    """True meant "files only" but the folder check used to run anyway."""
    from kemonodownloader import kd_settings

    assert kd_settings.normalize_name_dedup(True) == "both"
    assert kd_settings.normalize_name_dedup(False) == "off"
    assert kd_settings.normalize_name_dedup("file") == "file"
    assert kd_settings.normalize_name_dedup("folder") == "folder"
    assert kd_settings.normalize_name_dedup("true") == "both"
    assert kd_settings.normalize_name_dedup("false") == "off"
    assert kd_settings.normalize_name_dedup("nonsense") == "both"


def test_the_data_directory_is_a_fixed_readout(qapp):
    """A17: the folder lives next to the app and cannot be chosen."""
    from kemonodownloader.kd_settings import SettingsTab

    st = SettingsTab(make_parent())
    try:
        assert st.data_directory_input.isReadOnly() is True
        assert st.data_directory_input.text() == kd_paths.data_directory()
        # It is no longer the Save Directory default: posts and databases must
        # not share a folder.
        assert st.default_settings["data_directory"] != st.default_settings[
            "base_directory"
        ]
        assert st.data_directory_label.text() != ""
    finally:
        st.deleteLater()


def test_typing_into_the_data_field_changes_nothing(qapp, tmp_path):
    from kemonodownloader.kd_settings import SettingsTab

    st = SettingsTab(make_parent())
    try:
        before = dict(st.temp_settings)
        st.data_directory_input.setText(str(tmp_path / "somewhere"))

        # No signal is wired any more, so the setting cannot follow the field.
        assert st.temp_settings == before
    finally:
        st.deleteLater()


def test_open_data_directory_opens_the_fixed_folder(qapp, monkeypatch):
    from kemonodownloader.kd_settings import SettingsTab

    st = SettingsTab(make_parent())
    try:
        opened = []
        monkeypatch.setattr(
            "kemonodownloader.kd_settings.QDesktopServices.openUrl",
            lambda url: opened.append(url.toLocalFile()),
        )

        st.open_data_directory()

        assert [os.path.normpath(path) for path in opened] == [
            os.path.normpath(kd_paths.data_directory())
        ]
    finally:
        st.deleteLater()


def test_confirm_and_apply_directory_creation_failure(qapp, monkeypatch):
    from kemonodownloader.kd_settings import SettingsTab

    parent = make_parent()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    warned = {}
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warned.setdefault("w", True)
    )

    # Force directory creation to fail
    monkeypatch.setattr(os.path, "isdir", lambda p: False)

    def fail_makedirs(p, exist_ok=True):
        raise OSError("fail")

    monkeypatch.setattr(os, "makedirs", fail_makedirs)

    st = SettingsTab(parent)
    # Ensure we attempt to create a non-existent directory
    st.temp_settings["base_directory"] = "/nonexistent/path"
    st.confirm_and_apply_settings()

    assert warned.get("w") is True
    # Reset should keep settings' base_directory
    assert st.temp_settings["base_directory"] == st.settings["base_directory"]


def test_auto_detect_tor_finds_executable(qapp, monkeypatch):
    from kemonodownloader.kd_settings import SettingsTab

    parent = make_parent()

    st = SettingsTab(parent)

    # Make tor paths present and return a successful --version
    monkeypatch.setattr(os.path, "exists", lambda p: "tor" in str(p).lower())
    monkeypatch.setattr(os.path, "isfile", lambda p: "tor" in str(p).lower())

    def fake_run(args, capture_output=True, text=True, timeout=5):
        return SimpleNamespace(returncode=0, stdout="Tor v")

    monkeypatch.setattr(subprocess, "run", fake_run)

    found = st.auto_detect_tor()
    assert found is not None and "tor" in found.lower()


def test_get_proxy_settings_custom_and_tor(qapp, monkeypatch):
    from kemonodownloader.kd_settings import ProxyUnavailableError, SettingsTab

    parent = make_parent()
    st = SettingsTab(parent)

    # Custom proxy
    for settings in (st.settings, st.temp_settings):
        settings["use_proxy"] = True
        settings["proxy_type"] = "custom"
        settings["custom_proxy_url"] = "127.0.0.1:8080"
    assert st.get_proxy_settings() == {
        "http": "127.0.0.1:8080",
        "https": "127.0.0.1:8080",
    }

    # Tor proxy when Tor not running -> error, never a direct connection
    st.settings["proxy_type"] = "tor"
    st.temp_settings["proxy_type"] = "tor"
    st.tor_process = None
    with pytest.raises(ProxyUnavailableError):
        st.get_proxy_settings()

    # Tor running and socks available
    class FakeProcess:
        def state(self):
            return QProcess.ProcessState.Running

    st.tor_process = FakeProcess()
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: object() if name == "socks" else None
    )
    proxies = st.get_proxy_settings()
    assert proxies is not None
    assert proxies["http"].startswith("socks5h://")


def test_handle_tor_output_and_error(qapp, monkeypatch):
    from kemonodownloader.kd_settings import SettingsTab

    parent = make_parent()
    st = SettingsTab(parent)

    # Prepare fake process that returns Bootstrapped output
    class FakeProcOut:
        def readAllStandardOutput(self):
            return QByteArray(b"Bootstrapped 100%\n")

        def readAllStandardError(self):
            return QByteArray(b"")

    st.tor_process = FakeProcOut()
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    st.handle_tor_output()
    assert "running" in st.tor_status_label.text().lower()

    # Now test error handling
    class FakeProcErr:
        def readAllStandardOutput(self):
            return QByteArray(b"")

        def readAllStandardError(self):
            return QByteArray(b"Some error\n")

    st.tor_process = FakeProcErr()
    st.handle_tor_error()
    assert (
        "error" in st.tor_output_text.toPlainText().lower()
        or "some error" in st.tor_output_text.toPlainText().lower()
    )


def test_on_tor_download_handlers(qapp, monkeypatch):
    from kemonodownloader.kd_settings import SettingsTab

    parent = make_parent()
    st = SettingsTab(parent)

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    # Success path
    st.on_tor_download_success("/tmp/tor_exe")
    assert st.tor_path_input.text() == "/tmp/tor_exe"

    # Error paths
    st.on_tor_download_error("tor_exe_not_found")
    st.on_tor_download_error("other error")
