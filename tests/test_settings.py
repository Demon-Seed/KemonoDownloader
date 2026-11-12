"""
Integration tests for the Settings module.
These tests verify settings loading, saving, and UI configuration logic.
"""

import ast
import os
import pathlib
import sys
from unittest.mock import MagicMock

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox

from kemonodownloader.kd_language import translate
from kemonodownloader.kd_settings import DownloadTorThread, SettingsTab


class TestDefaultSettings:
    """Tests for default settings values."""

    def test_default_settings_values(self, qapp):
        """The shipped defaults, as a fresh Settings tab shows them."""
        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(None)
        try:
            defaults = st.default_settings
            assert defaults["base_folder_name"] == "Kemono Downloader"
            assert defaults["simultaneous_downloads"] == 5
            assert defaults["language"] == "english"
            assert defaults["creator_posts_max_attempts"] == 200
            assert defaults["post_data_max_retries"] == 7
            assert defaults["file_download_max_retries"] == 50
            assert defaults["api_request_max_retries"] == 3
            assert defaults["show_only_found_filetypes"] == "on_with_count"
            assert defaults["creator_filename_template"] == (
                "{post_id}_{file_number}_{orig_name}"
            )
            assert defaults["creator_filename_template_shared"] == (
                "{post_id}_{file_number}_{orig_name}"
            )
            assert defaults["creator_folder_name_template"] == "{post_id}_{post_title}"
            assert defaults["creator_unique_filenames"] == "both"
            assert defaults["creator_folder_strategy"] == "per_post"
            assert defaults["font"] == "JetBrains Mono"
            assert defaults["use_proxy"] is False
            assert defaults["proxy_type"] == "tor"
        finally:
            st.deleteLater()

    def test_creator_filename_and_folder_defaults(self):
        """Ensure the creator filename template and folder strategy defaults exist."""
        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(None)
        try:
            assert st.get_creator_filename_template() != ""
            assert st.get_creator_folder_strategy() in [
                "per_post",
                "single_folder",
                "by_file_type",
            ]
        finally:
            st.deleteLater()


class TestBaseDirectoryLogic:
    """Tests for base directory path logic."""

    def test_windows_default_directory(self):
        """Test default directory path on Windows."""
        if sys.platform == "win32":
            appdata = os.getenv("APPDATA", os.path.expanduser("~"))
            expected_base = os.path.join(appdata, "Kemono Downloader")

            # Path should be under APPDATA on Windows
            assert "Kemono Downloader" in expected_base
            assert os.path.isabs(expected_base)

    def test_macos_default_directory(self):
        """Test default directory path on macOS."""
        if sys.platform == "darwin":
            expected_base = os.path.expanduser(
                "~/Library/Application Support/Kemono Downloader"
            )

            assert "Library/Application Support" in expected_base
            assert "Kemono Downloader" in expected_base

        if sys.platform not in ["win32", "darwin"]:
            xdg_data = os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
            expected_base = os.path.join(xdg_data, "Kemono Downloader")

            assert "Kemono Downloader" in expected_base

    def test_get_default_base_directory_mock(self, monkeypatch):
        """Test get_default_base_directory logic with mocked sys.platform."""
        from kemonodownloader.kd_settings import SettingsTab

        # Mock parent
        class MockParent:
            def log(self, m):
                pass

        st = SettingsTab(MockParent())
        try:
            # Mock Windows
            monkeypatch.setattr(sys, "platform", "win32")
            monkeypatch.setenv("APPDATA", "C:\\AppData")
            # For comparison on Mac, normalize to forward slashes
            assert (
                st.get_default_base_directory().replace("\\", "/")
                == "C:/AppData/Kemono Downloader"
            )

            # Mock Linux
            monkeypatch.setattr(sys, "platform", "linux")
            monkeypatch.setenv("XDG_DATA_HOME", "/home/user/.local/share")
            assert (
                st.get_default_base_directory().replace("\\", "/")
                == "/home/user/.local/share/Kemono Downloader"
            )

            # Mock Linux without XDG_DATA_HOME
            monkeypatch.delenv("XDG_DATA_HOME", raising=False)
            home = os.path.expanduser("~")
            expected = os.path.join(home, ".local", "share", "Kemono Downloader")
            assert st.get_default_base_directory() == expected
        finally:
            st.deleteLater()

    def test_directory_path_is_absolute(self):
        """Test that directory paths are absolute."""
        if sys.platform == "win32":
            base_dir = os.path.join(
                os.getenv("APPDATA", os.path.expanduser("~")), "Kemono Downloader"
            )
        elif sys.platform == "darwin":
            base_dir = os.path.expanduser(
                "~/Library/Application Support/Kemono Downloader"
            )
        else:
            base_dir = os.path.join(
                os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                "Kemono Downloader",
            )

        assert os.path.isabs(base_dir)


class TestLanguageSettings:
    """Tests for the single supported language."""

    def test_available_languages(self):
        """Only English ships, so that is all that is offered."""
        from kemonodownloader.kd_language import language_manager

        assert language_manager.get_available_languages() == ["english"]

    def test_language_persistence(self):
        """A non-English value is rejected instead of switching the app."""
        from kemonodownloader.kd_language import language_manager

        original = language_manager.get_language()

        try:
            assert language_manager.set_language("japanese") is False
            assert language_manager.set_language("korean") is False
            assert language_manager.get_language() == "english"
        finally:
            language_manager.set_language(original)


class TestSettingsMigration:
    """Tests for settings migration and backward compatibility."""

    def test_legacy_proxy_type_migration(self, qapp):
        """Test conversion of legacy 'none' proxy type to 'tor'."""
        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def log(self, m):
                pass

        # Seed the legacy value in the isolated store (see isolate_qsettings
        # in tests/conftest.py) and verify load_settings migrates it. Never
        # point this at the real "VoxDroid"/"KemonoDownloader" settings.
        st = SettingsTab(MockParent())
        try:
            st.qsettings.setValue("proxy_type", "none")
            st.qsettings.sync()
            settings_dict = st.load_settings()
            assert settings_dict["proxy_type"] == "tor"
        finally:
            st.deleteLater()


class TestSettingsUIInteractions:
    """Tests for UI component interactions in SettingsTab."""

    def test_update_temp_setting(self, qapp):
        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def log(self, m):
                pass

        st = SettingsTab(MockParent())
        try:
            st.update_temp_setting("base_folder_name", "New Folder")
            assert st.temp_settings["base_folder_name"] == "New Folder"
        finally:
            st.deleteLater()

    def test_update_simultaneous_downloads(self, qapp):
        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def log(self, m):
                pass

        st = SettingsTab(MockParent())
        try:
            # Update via slider
            st.download_slider.setValue(10)
            assert st.temp_settings["simultaneous_downloads"] == 10
            assert st.download_spinbox.value() == 10

            # Update via spinbox
            st.download_spinbox.setValue(15)
            assert st.temp_settings["simultaneous_downloads"] == 15
            assert st.download_slider.value() == 15
        finally:
            st.deleteLater()

    def test_on_use_proxy_changed(self, qapp):

        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def log(self, m):
                pass

        st = SettingsTab(MockParent())
        try:
            # Check proxy
            st.use_proxy_checkbox.setChecked(True)
            assert st.temp_settings["use_proxy"] is True
            assert st.proxy_group.isHidden() is False

            # Uncheck proxy
            st.use_proxy_checkbox.setChecked(False)
            assert st.temp_settings["use_proxy"] is False
            assert st.proxy_group.isHidden() is True
        finally:
            st.deleteLater()

    def test_on_proxy_type_changed(self, qapp):
        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def log(self, m):
                pass

        st = SettingsTab(MockParent())
        try:
            st.use_proxy_checkbox.setChecked(True)

            # Switch to custom
            idx = st.proxy_type_combo.findData("custom")
            st.proxy_type_combo.setCurrentIndex(idx)
            assert st.temp_settings["proxy_type"] == "custom"
            assert st.custom_proxy_input.isHidden() is False
            assert st.tor_label.isHidden() is True

            # Switch to tor
            idx = st.proxy_type_combo.findData("tor")
            st.proxy_type_combo.setCurrentIndex(idx)
            assert st.temp_settings["proxy_type"] == "tor"
            assert st.custom_proxy_input.isHidden() is True
            assert st.tor_label.isHidden() is False
        finally:
            st.deleteLater()

    def test_language_and_font_updates(self, qapp):
        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def log(self, m):
                pass

        st = SettingsTab(MockParent())
        try:
            # Update font
            idx = st.font_combo.findData("Poppins")
            st.font_combo.setCurrentIndex(idx)
            assert st.temp_settings["font"] == "Poppins"

            # Update font with missing index
            st.update_font(-1)
        finally:
            st.deleteLater()

    def test_browse_directory(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog

        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def log(self, m):
                pass

        st = SettingsTab(MockParent())
        try:
            monkeypatch.setattr(
                QFileDialog, "getExistingDirectory", lambda *a, **k: "/new/path"
            )
            st.browse_directory()
            assert st.directory_input.text() == "/new/path"
            assert st.temp_settings["base_directory"] == "/new/path"
        finally:
            st.deleteLater()

    def test_settings_apply_and_reset(self, qapp, monkeypatch):
        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def __init__(self):
                self.base_folder = "initial"
                self.download_folder = ""
                self.cache_folder = ""
                self.other_files_folder = ""
                self.post_tab = MagicMock()
                self.creator_tab = MagicMock()
                self.post_tab.cache_dir = ""
                self.post_tab.other_files_dir = ""
                self.creator_tab.cache_dir = ""
                self.creator_tab.other_files_dir = ""

            def log(self, msg):
                pass

            def ensure_folders_exist(self):
                pass

        parent = MockParent()

        # Mock translate and language_manager before creating SettingsTab
        import kemonodownloader.kd_settings

        monkeypatch.setattr(kemonodownloader.kd_settings, "translate", lambda s, *a: s)
        monkeypatch.setattr(
            kemonodownloader.kd_settings, "language_manager", MagicMock()
        )

        st = SettingsTab(parent)
        try:
            # Mock filesystem and save to avoid real operations and hangs
            monkeypatch.setattr(os.path, "isdir", lambda p: True)
            monkeypatch.setattr(os, "makedirs", lambda p, **k: None)
            monkeypatch.setattr(st, "save_settings", lambda: None)

            # Test Apply
            st.update_temp_setting("base_directory", "/fake/Applied Folder")
            from PyQt6.QtWidgets import QMessageBox

            # Patch all dialog methods for safety
            monkeypatch.setattr(
                QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
            )
            monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
            monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

            st.confirm_and_apply_settings()
            # Posts now go straight into the Save Directory, with no
            # "<folder name>/Downloads" layer under it.
            assert str(parent.download_folder) == "/fake/Applied Folder"

            # Test Reset
            st.confirm_and_reset_settings()
            assert (
                st.temp_settings["data_directory"]
                == st.default_settings["data_directory"]
            )
        finally:
            st.deleteLater()

    def test_show_help_dialogs(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def log(self, m):
                pass

        st = SettingsTab(MockParent())
        try:
            mock_info = []
            monkeypatch.setattr(
                QMessageBox, "information", lambda *a, **k: mock_info.append(a)
            )

            st.show_template_help()
            st.show_tor_help()
            assert len(mock_info) == 2
        finally:
            st.deleteLater()


class TestTorManagement:
    """Tests for Tor process management in SettingsTab."""

    def test_tor_io_handlers(self, qapp, monkeypatch):
        from PyQt6.QtCore import QByteArray

        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def __init__(self):
                self.base_folder = ""

            def log(self, msg):
                pass

        st = SettingsTab(MockParent())
        try:
            # Mock tor_process
            class MockProcess:
                def readAllStandardOutput(self):
                    return QByteArray(b"Tor is starting\n")

                def readAllStandardError(self):
                    return QByteArray(b"Tor error happened\n")

            st.tor_process = MockProcess()

            # Mock translate and QMessageBox for bootstrap check
            import kemonodownloader.kd_settings

            monkeypatch.setattr(
                kemonodownloader.kd_settings, "translate", lambda s, *a: s
            )
            from PyQt6.QtWidgets import QMessageBox

            monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

            st.handle_tor_output()
            assert "Tor is starting" in st.tor_output_text.toPlainText()

            st.handle_tor_error()
            assert "Tor error happened" in st.tor_output_text.toPlainText()

            # Test Bootstrapped 100%
            class MockProcessBootstrap:
                def readAllStandardOutput(self):
                    return QByteArray(b"Bootstrapped 100%\n")

            st.tor_process = MockProcessBootstrap()
            st.handle_tor_output()
            assert (
                "running" in st.tor_status_label.text().lower()
                or "Running" in st.tor_status_label.text()
            )
        finally:
            st.deleteLater()

    def test_start_stop_tor_logic(self, qapp, monkeypatch):
        from PyQt6.QtCore import QProcess

        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def __init__(self):
                self.base_folder = ""

            def log(self, msg):
                pass

        st = SettingsTab(MockParent())
        try:
            # Mock start_tor to avoid actual process creation
            mock_started = False

            def mock_start(*args):
                nonlocal mock_started
                mock_started = True

            # Use fixed path for tor
            st.temp_settings["tor_path"] = "/usr/bin/tor"

            # Mock os.path.exists to allow start_tor to proceed
            monkeypatch.setattr(os.path, "exists", lambda p: True)

            # Mock QProcess methods
            monkeypatch.setattr(QProcess, "start", mock_start)
            monkeypatch.setattr(QProcess, "terminate", lambda self: None)
            monkeypatch.setattr(
                QProcess, "state", lambda self: QProcess.ProcessState.Running
            )
            monkeypatch.setattr(QProcess, "waitForFinished", lambda self, t: True)

            # Mock QMessageBox.information to avoid hang
            from PyQt6.QtWidgets import QMessageBox

            monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
            monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

            st.start_tor()
            assert mock_started is True

            st.stop_tor()
        finally:
            st.deleteLater()


class TestTorAsync:
    """Tests for asynchronous Tor download and network tests."""

    def test_download_tor_logic(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        import kemonodownloader.kd_settings
        from kemonodownloader.kd_settings import SettingsTab

        monkeypatch.setattr(kemonodownloader.kd_settings, "translate", lambda s, *a: s)
        monkeypatch.setattr(
            kemonodownloader.kd_settings, "language_manager", MagicMock()
        )
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

        mock_thread = MagicMock()
        monkeypatch.setattr(
            "kemonodownloader.kd_settings.DownloadTorThread", lambda *a: mock_thread
        )

        st = SettingsTab(MagicMock())
        try:
            st.download_tor()
            assert mock_thread.start.called

            # Test handlers
            st.on_tor_download_success("/path/to/extracted/tor")
            st.on_tor_download_error("Error message")
        finally:
            st.deleteLater()

    def test_download_tor_thread_run(self, qapp, monkeypatch):
        import tarfile

        import requests

        from kemonodownloader.kd_settings import DownloadTorThread

        # Mock requests.get for download
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content = lambda *a, **k: [b"dummy data"]
        mock_resp.headers = {"content-length": "10"}
        monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

        # Mock tarfile
        mock_tar = MagicMock()
        monkeypatch.setattr(tarfile, "open", lambda *a, **k: mock_tar)

        # Mock os/shutil
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)
        monkeypatch.setattr(os, "remove", lambda *a, **k: None)
        monkeypatch.setattr(os.path, "exists", lambda p: True)
        monkeypatch.setattr(os, "walk", lambda p: [("root", [], ["tor.exe"])])
        import shutil

        monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)
        monkeypatch.setattr(shutil, "move", lambda *a, **k: None)

        thread = DownloadTorThread(
            "http://example.com/tor.tar.gz", "extract_dir", "tor_path"
        )
        events = []
        thread.progress.connect(lambda v: None)
        thread.finished_success.connect(lambda p: events.append(("ok", p)))
        thread.finished_error.connect(lambda e: events.append(("err", e)))

        thread.run()
        assert events and events[0][0] == "ok"

        # Test error path: 404
        mock_resp.raise_for_status.side_effect = Exception("404 Client Error")
        thread.run()
        assert events[-1][0] == "err"
        mock_resp.raise_for_status.side_effect = None

        # Test error path: Exception
        monkeypatch.setattr(requests, "get", MagicMock(side_effect=Exception("Failed")))
        thread.run()
        assert len([event for event in events if event[0] == "err"]) >= 2

    def test_download_tor_thread_extra_errors(self, qapp, monkeypatch):
        import hashlib
        import tarfile

        import requests

        from kemonodownloader.kd_settings import DownloadTorThread

        thread = DownloadTorThread("url", "ex_dir", "tor_p")
        outcomes = []
        thread.finished_success.connect(lambda p: outcomes.append("ok"))
        thread.finished_error.connect(lambda e: outcomes.append("err"))

        # Test hash verification failure
        mock_resp = MagicMock(status_code=200, headers={"content-length": "10"})
        mock_resp.iter_content = lambda b: [b"dummy"]
        monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)
        monkeypatch.setattr(os, "remove", lambda *a, **k: None)
        # Mock file write and hash
        mock_open = MagicMock()
        monkeypatch.setattr("builtins.open", MagicMock(return_value=mock_open))

        # Mock a different hash to trigger failure
        mock_hash = MagicMock()
        mock_hash.hexdigest.return_value = "wrong_hash"
        monkeypatch.setattr(hashlib, "sha256", lambda *a: mock_hash)

        thread.run()

        # Test extraction failure
        monkeypatch.setattr(
            hashlib, "sha256", lambda *a: MagicMock(hexdigest=lambda: thread.TOR_HASH)
        )
        monkeypatch.setattr(
            tarfile, "open", MagicMock(side_effect=Exception("Extract Error"))
        )
        thread.run()

        assert outcomes == ["err", "err"], "both failures must be reported"

    def test_download_tor_thread_success_search(self, qapp, monkeypatch):
        import hashlib
        import tarfile

        import requests

        from kemonodownloader.kd_settings import DownloadTorThread

        thread = DownloadTorThread("url", "ex_dir", "tor_p")
        outcomes = []
        thread.finished_success.connect(lambda p: outcomes.append("ok"))
        thread.finished_error.connect(lambda e: outcomes.append("err"))

        # Mock download success
        mock_resp = MagicMock(status_code=200, headers={"content-length": "10"})
        mock_resp.iter_content = lambda *a, **k: [b"dummy"]
        monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)
        monkeypatch.setattr(os, "remove", lambda *a, **k: None)
        # Mock file write and hash
        mock_open = MagicMock()
        monkeypatch.setattr("builtins.open", MagicMock(return_value=mock_open))
        monkeypatch.setattr(
            hashlib, "sha256", lambda *a: MagicMock(hexdigest=lambda: thread.TOR_HASH)
        )
        monkeypatch.setattr(tarfile, "open", lambda *a, **k: MagicMock())
        monkeypatch.setattr(os, "unlink", lambda p: None)

        # Test 1: Tor exe NOT found
        monkeypatch.setattr(os, "walk", lambda p: [("root", [], ["not_tor.txt"])])
        thread.run()

        # Test 2: Tor exe FOUND
        monkeypatch.setattr(os, "walk", lambda p: [("root", [], ["tor.exe"])])
        thread.run()

        # Test 3: Download error (status code 404)
        mock_resp.raise_for_status.side_effect = Exception("404 Client Error")
        thread.run()

        # No tor binary -> error; tor.exe found -> success; 404 -> error.
        assert outcomes == ["err", "ok", "err"]

    def test_test_tor_network_errors(self, qapp, monkeypatch):
        import subprocess

        import requests
        from PyQt6.QtWidgets import QMessageBox

        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            st.temp_settings["tor_path"] = "/usr/bin/tor"
            monkeypatch.setattr(os.path, "exists", lambda p: True)
            warnings = []
            monkeypatch.setattr(
                QMessageBox, "warning", lambda *a, **k: warnings.append(a)
            )

            # Subprocess version check failure
            mock_res = MagicMock()
            mock_res.returncode = 1
            monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_res)
            st.test_tor()

            # Subprocess exception
            monkeypatch.setattr(
                subprocess, "run", MagicMock(side_effect=Exception("Exec error"))
            )
            st.test_tor()

            # Network test failure (JSON Decode Error)
            mock_res.returncode = 0
            mock_res.stdout = "Tor version 0.4.8"
            monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_res)
            mock_resp = MagicMock(status_code=200)
            mock_resp.json.side_effect = ValueError("Invalid JSON")
            monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)
            st.test_tor()

            # Tor process handlers (stderr/stdout)
            mock_proc = MagicMock()
            mock_proc.readAllStandardError.return_value = MagicMock(
                data=lambda: b"Tor Error"
            )
            st.tor_process = mock_proc
            st.handle_tor_error()  # Line 1915

            mock_proc.readAllStandardOutput.return_value = MagicMock(
                data=lambda: b"Tor Status: 100%"
            )
            st.handle_tor_output()  # Line 1891

            # handle_tor_finished cleanup path (Lines 1935-1941)
            st.tor_config_file = MagicMock()
            st.tor_config_file.name = "/tmp/fake.torrc"
            monkeypatch.setattr(os, "unlink", lambda p: None)
            st.handle_tor_finished(0, MagicMock())

            assert len(warnings) >= 3, "each failure path must warn the user"
        finally:
            st.deleteLater()

    def test_tor_io_error_handlers(self, qapp, monkeypatch):
        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            # Mock tor_process to avoid None check failure
            st.tor_process = MagicMock()
            # Mock readAllStandardError to return something with .data()
            mock_data = MagicMock()
            mock_data.data.return_value = b"Some error from tor"
            st.tor_process.readAllStandardError.return_value = mock_data

            st.handle_tor_error()

            assert st.tor_process.readAllStandardError.called

            # Test handle_tor_finished
            st.tor_config_file = MagicMock()
            st.tor_config_file.name = "/tmp/dummy.torrc"
            monkeypatch.setattr(os.path, "exists", lambda p: True)
            st.handle_tor_finished(0, 0)
        finally:
            st.deleteLater()


class TestCustomUIState:
    """Tests for specific UI initialization states (lines 384-387)."""

    def test_custom_template_init(self, qapp, monkeypatch):
        from kemonodownloader.kd_settings import SettingsTab

        parent = MagicMock()
        parent.base_folder = ""

        # Mock class method load_settings BEFORE creating SettingsTab
        # Must include all keys used in __init__
        mock_settings = {
            "base_folder_name": "Kemono Downloader",
            "base_directory": "/tmp",
            "simultaneous_downloads": 5,
            "language": "english",
            "creator_posts_max_attempts": 200,
            "post_data_max_retries": 7,
            "file_download_max_retries": 50,
            "api_request_max_retries": 3,
            "use_proxy": False,
            "proxy_type": "tor",
            "custom_proxy_url": "",
            "tor_path": "",
            "creator_filename_template": "custom_{id}",
            "creator_folder_strategy": "per_post",
            "font": "JetBrains Mono",
        }
        monkeypatch.setattr(SettingsTab, "load_settings", lambda self: mock_settings)
        # Mock kemonodownloader.kd_settings.translate for items
        import kemonodownloader.kd_settings

        monkeypatch.setattr(kemonodownloader.kd_settings, "translate", lambda s, *a: s)
        monkeypatch.setattr(
            kemonodownloader.kd_settings, "language_manager", MagicMock()
        )

        st = SettingsTab(parent)
        try:
            # Should hit lines 384-387
            # We check the line edit text
            assert st.creator_filename_input.text() == "custom_{id}"
        finally:
            st.deleteLater()


class TestDetailedUI:
    """Tests for remaining UI edge cases and help dialogs."""

    def test_help_dialogs(self, qapp, monkeypatch):
        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            from PyQt6.QtWidgets import QMessageBox

            shown = []
            monkeypatch.setattr(
                QMessageBox, "information", lambda *a, **k: shown.append(a)
            )
            st.show_template_help()
            st.show_tor_help()

            assert len(shown) == 2, "both help buttons must show a dialog"
            assert all(call[1] for call in shown), "each dialog needs a title"
        finally:
            st.deleteLater()

    def test_update_handlers(self, qapp):
        from kemonodownloader.kd_settings import SettingsTab

        parent = MagicMock()
        st = SettingsTab(parent)
        try:
            # Pass integer index
            st.font_combo = MagicMock()
            st.font_combo.itemData.return_value = "Poppins"
            st.update_font(0)

            assert st.temp_settings["font"] == "Poppins"
        finally:
            st.deleteLater()


def test_auto_detect_tor_in_base_directory(tmp_path, monkeypatch, qapp):
    """Auto-detect should find tor executable under the configured base directory."""
    import subprocess
    import sys

    # Minimal mock parent
    class MockParent:
        base_folder = ""
        download_folder = ""
        cache_folder = ""
        other_files_folder = ""

        def log(self, msg):
            pass

        def ensure_folders_exist(self):
            pass

    settings_tab = None
    try:
        # Create SettingsTab (requires QApplication available in conftest)
        from kemonodownloader.kd_settings import SettingsTab

        settings_tab = SettingsTab(MockParent())

        # Point settings to tmp base directory
        base_dir = str(tmp_path)
        settings_tab.temp_settings["base_directory"] = base_dir
        settings_tab.temp_settings["base_folder_name"] = "Kemono Downloader"

        # Create a fake tor executable in the expected app Tor folder
        tor_dir = tmp_path / "Kemono Downloader" / "Tor"
        tor_dir.mkdir(parents=True)
        tor_file = tor_dir / ("tor.exe" if sys.platform == "win32" else "tor")
        tor_file.write_text("#!/bin/sh\necho Tor 0.4\n")
        tor_file.chmod(0o755)

        # Patch subprocess.run to simulate a valid 'tor --version' output
        class FakeResult:
            returncode = 0
            stdout = "Tor version 0.4"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeResult)

        detected = settings_tab.auto_detect_tor()
        assert detected is not None
        assert str(tor_file) in detected
    finally:
        # Attempt to cleanup SettingsTab if it exists
        if settings_tab is not None:
            settings_tab.deleteLater()


class TestQSettingsIntegration:
    """Tests for QSettings integration."""

    def test_qsettings_value_types(self, tmp_path):
        """Test QSettings value type handling."""
        settings = QSettings(
            str(tmp_path / "value_types.ini"), QSettings.Format.IniFormat
        )

        try:
            # Test setting and getting different types
            settings.setValue("test_string", "hello")
            settings.setValue("test_int", 42)
            settings.setValue("test_bool", True)

            # Retrieve with type hints
            assert settings.value("test_string", type=str) == "hello"
            assert settings.value("test_int", type=int) == 42
            assert settings.value("test_bool", type=bool) is True
        finally:
            # Cleanup
            settings.clear()

    def test_qsettings_default_values(self, tmp_path):
        """Test QSettings default value handling."""
        settings = QSettings(
            str(tmp_path / "default_values.ini"), QSettings.Format.IniFormat
        )

        try:
            # Non-existent key should return default
            assert settings.value("nonexistent_key", "default_value") == "default_value"
            assert settings.value("nonexistent_int", 100, type=int) == 100
        finally:
            settings.clear()

    def test_apply_settings_validation_errors(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            monkeypatch.setattr(
                QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
            )
            warnings = []
            monkeypatch.setattr(
                QMessageBox, "warning", lambda *a, **k: warnings.append(a)
            )
            monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

            # Directory creation failure: the Save Directory cannot be made.
            st.temp_settings["base_directory"] = "/root/no_permission"
            monkeypatch.setattr(os.path, "isdir", lambda p: False)
            monkeypatch.setattr(
                os, "makedirs", MagicMock(side_effect=OSError("Permission denied"))
            )
            st.confirm_and_apply_settings()

            assert warnings, "a directory that cannot be made must warn, not apply"
        finally:
            st.deleteLater()

    def test_help_dialog_exception(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        import kemonodownloader.kd_settings
        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            # Trigger exception in show_template_help (777-779)
            shown = []
            monkeypatch.setattr(
                QMessageBox, "information", lambda *a, **k: shown.append(a)
            )
            monkeypatch.setattr(
                kemonodownloader.kd_settings,
                "translate",
                MagicMock(side_effect=Exception("Error")),
            )
            st.show_template_help()

            assert shown, "the fallback help dialog must still appear"
            assert shown[0][1] == "Template Help"
        finally:
            st.deleteLater()

    def test_update_font_edge_cases(self, qapp):
        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            # Test update_font with -1 index
            st.update_font(-1)

            # An invalid index selects nothing instead of crashing.
            assert st.temp_settings["font"] is None
        finally:
            st.deleteLater()

    def test_load_settings_platforms(self, qapp, monkeypatch):
        import sys

        from kemonodownloader.kd_settings import SettingsTab

        # Mock Windows
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(
            os, "getenv", lambda k, d=None: "C:\\Users\\fake" if k == "APPDATA" else d
        )
        st = SettingsTab(MagicMock())
        try:
            # Trigger load_settings
            s = st.load_settings()
            assert "base_directory" in s
        finally:
            st.deleteLater()

        # Mock Linux
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            os,
            "getenv",
            lambda k, d=None: "/home/fake/.local/share" if k == "XDG_DATA_HOME" else d,
        )
        st = SettingsTab(MagicMock())
        try:
            s = st.load_settings()
            assert "base_directory" in s
        finally:
            st.deleteLater()


def test_download_tor_thread_skips_path_traversal(monkeypatch, tmp_path):
    # Prepare fake response for requests.get
    class FakeResp:
        status_code = 200

        def __init__(self, chunks):
            self._chunks = chunks
            self.headers = {"content-length": str(sum(len(c) for c in chunks))}

        def iter_content(self, chunk_size=8192):
            for c in self._chunks:
                yield c

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "requests.get",
        lambda *a, **k: FakeResp([b"data"]),
    )

    # Fake tarfile object that records extracted member names
    class FakeMember:
        def __init__(self, name):
            self.name = name

    class FakeTar:
        def __init__(self, members):
            self._members = [FakeMember(n) for n in members]
            self.extracted = []

        def getmembers(self):
            return self._members

        def extract(self, member, path):
            # record the member name that would be extracted
            self.extracted.append(member.name)

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    # Create tar_ref with a safe and an unsafe member
    members = ["tor/tor", "../../etc/passwd", "tor/bin/tor"]
    fake_tar = FakeTar(members)

    monkeypatch.setattr("tarfile.open", lambda *a, **k: fake_tar)

    # Ensure os.unlink doesn't remove anything important during test
    monkeypatch.setattr("os.unlink", lambda p: None)

    # Run the DownloadTorThread
    tor_path = str(tmp_path / "tor_dir")
    os.makedirs(tor_path, exist_ok=True)
    thread = DownloadTorThread("http://example.com/tor.tar.gz", str(tmp_path), tor_path)
    # Connect signals to no-op to avoid Qt requirements
    thread.progress.connect(lambda v: None)
    thread.finished_success.connect(lambda p: None)
    thread.finished_error.connect(lambda e: None)

    # Execute run() directly
    thread.run()

    # After run, only safe members should have been extracted
    assert all(".." not in name for name in fake_tar.extracted)
    assert any(name.startswith("tor/") for name in fake_tar.extracted)


class MockParent:
    def __init__(self):
        self.download_folder = ""
        self.cache_folder = ""
        self.other_files_folder = ""

        # Minimal post/creator tabs used elsewhere
        class DummyTab:
            pass

        self.post_tab = DummyTab()
        self.creator_tab = DummyTab()

    def ensure_folders_exist(self):
        # Real window creates the folders; the mock only needs the call to work.
        return None

    def log(self, msg):
        pass


def test_settings_applied_message_includes_template_and_strategy(
    monkeypatch, tmp_path, qapp
):
    parent = MockParent()
    st = SettingsTab(parent)
    try:
        # Prepare temp settings with non-empty directory to avoid directory creation warning
        st.temp_settings["base_directory"] = str(tmp_path)
        st.temp_settings["simultaneous_downloads"] = 3
        st.temp_settings["creator_posts_max_attempts"] = 12
        st.temp_settings["post_data_max_retries"] = 9
        st.temp_settings["file_download_max_retries"] = 33
        st.temp_settings["api_request_max_retries"] = 4
        st.temp_settings["verbose_logging"] = True
        st.temp_settings["show_only_found_filetypes"] = "on"

        # Set creator-specific settings
        st.temp_settings["creator_filename_template"] = "{post_title}-{post_id}"
        st.temp_settings["creator_folder_strategy"] = "single_folder"
        st.temp_settings["creator_unique_filenames"] = False

        # Monkeypatch question to behave as if the user clicked Yes
        asked = {}

        def fake_question(parent_arg, title, text, *args, **kwargs):
            asked["text"] = text
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", fake_question)

        captured = {}

        def fake_info(self_arg, title, message):
            captured["title"] = title
            captured["message"] = message

        monkeypatch.setattr(QMessageBox, "information", fake_info)

        # Call apply
        st.confirm_and_apply_settings()

        assert "{post_title}-{post_id}" in captured["message"]
        # Folder strategy display uses translate("single_creator_folder")
        assert translate("single_creator_folder") in captured["message"]

        # Both prompts carry what changed, newer settings included.
        for prompt in (asked["text"], captured["message"]):
            assert translate("unique_filenames") in prompt
            assert translate("option_off") in prompt
            assert translate("creator_posts_max_attempts") in prompt
            assert translate("post_data_max_retries") in prompt
            assert translate("file_download_max_retries") in prompt
            assert translate("api_request_max_retries") in prompt
            assert translate("verbose_logging") in prompt
            assert translate("show_only_found_filetypes") in prompt
            assert str(st.temp_settings["file_download_max_retries"]) in prompt
            # Only what changed: untouched settings stay out of the prompt.
            assert translate("font") not in prompt
            assert translate("data_directory") not in prompt
            assert translate("language") not in prompt
    finally:
        st.deleteLater()


def test_the_prompt_says_when_nothing_changed(monkeypatch, tmp_path, qapp):
    parent = MockParent()
    st = SettingsTab(parent)
    try:
        # Same value on both sides, so nothing counts as a change.
        st.settings["base_directory"] = str(tmp_path)
        st.temp_settings["base_directory"] = str(tmp_path)

        asked = {}

        def fake_question(parent_arg, title, text, *args, **kwargs):
            asked["text"] = text
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", fake_question)
        captured = {}

        def fake_info(self_arg, title, message):
            captured["message"] = message

        monkeypatch.setattr(QMessageBox, "information", fake_info)

        st.confirm_and_apply_settings()

        assert translate("no_settings_changed") in asked["text"]
        assert translate("no_settings_changed") in captured["message"]
        # Not a single value is repeated back.
        assert translate("font") not in asked["text"]
        assert translate("save_directory") not in asked["text"]
    finally:
        st.deleteLater()


def test_settings_tab_uses_the_isolated_store(qapp):
    from kemonodownloader.kd_settings import SettingsTab

    st = SettingsTab(None)
    try:
        file_name = st.qsettings.fileName()
        assert "kd_settings.ini" in file_name
        assert "VoxDroid" not in file_name

        st.qsettings.setValue("isolation_sentinel", 1)
        assert st.qsettings.value("isolation_sentinel", type=int) == 1
    finally:
        st.deleteLater()


def _real_settings_call_lines(path):
    """Return the line numbers where *path* builds the real settings store."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "QSettings":
            continue
        first_args = [
            arg.value for arg in node.args[:2] if isinstance(arg, ast.Constant)
        ]
        if first_args == ["VoxDroid", "KemonoDownloader"]:
            hits.append(node.lineno)
    return hits


def test_no_test_module_constructs_the_real_settings_store():
    """Fail if any test binds the real QSettings class directly.

    A module-level ``from PyQt6.QtCore import QSettings`` resolved at import
    time bypasses the ``isolate_qsettings`` fixture, which is exactly how
    earlier suite runs emptied the user's Settings page.
    """
    offenders = {}
    for path in pathlib.Path(__file__).resolve().parent.glob("test_*.py"):
        hits = _real_settings_call_lines(path)
        if hits:
            offenders[path.name] = hits
    assert offenders == {}
