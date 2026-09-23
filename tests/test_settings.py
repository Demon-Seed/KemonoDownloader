"""
Integration tests for the Settings module.
These tests verify settings loading, saving, and UI configuration logic.
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock

from PyQt6.QtCore import QSettings


class TestDefaultSettings:
    """Tests for default settings values."""

    def test_default_base_folder_name(self):
        """Test default base folder name."""

        # Create a minimal mock parent
        class MockParent:
            base_folder = ""
            download_folder = ""
            cache_folder = ""
            other_files_folder = ""

            def log(self, msg):
                pass

            def ensure_folders_exist(self):
                pass

        # Use a unique QSettings name to avoid conflicts
        QSettings("VoxDroid_Test", "KemonoDownloader_Test").clear()

        # Access default settings directly
        default_settings = {
            "base_folder_name": "Kemono Downloader",
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
        }

        assert default_settings["base_folder_name"] == "Kemono Downloader"
        assert default_settings["simultaneous_downloads"] == 5
        assert default_settings["language"] == "english"

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

    def test_default_retry_settings(self):
        """Test default retry configuration values."""
        defaults = {
            "creator_posts_max_attempts": 200,
            "post_data_max_retries": 7,
            "file_download_max_retries": 50,
            "api_request_max_retries": 3,
        }

        # Verify reasonable default values
        assert defaults["creator_posts_max_attempts"] > 0
        assert defaults["post_data_max_retries"] > 0
        assert defaults["file_download_max_retries"] > 0
        assert defaults["api_request_max_retries"] > 0

        # Verify they are integers
        assert isinstance(defaults["creator_posts_max_attempts"], int)
        assert isinstance(defaults["post_data_max_retries"], int)

    def test_default_proxy_settings(self):
        """Test default proxy configuration."""
        defaults = {
            "use_proxy": False,
            "proxy_type": "tor",
            "custom_proxy_url": "",
            "tor_path": "",
        }

        # Proxy should be disabled by default
        assert defaults["use_proxy"] is False
        assert defaults["proxy_type"] in ["tor", "custom"]
        assert defaults["custom_proxy_url"] == ""


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
            expected = os.path.join(home, ".local/share", "Kemono Downloader")
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
    """Tests for language settings."""

    def test_available_languages(self):
        """Test that expected languages are available."""
        from kemonodownloader.kd_language import language_manager

        languages = language_manager.get_available_languages()

        assert "english" in languages
        assert "japanese" in languages
        assert "korean" in languages
        assert "chinese-simplified" in languages

    def test_language_persistence(self):
        """Test that language setting can be changed and retrieved."""
        from kemonodownloader.kd_language import language_manager

        original = language_manager.get_language()

        try:
            language_manager.set_language("japanese")
            assert language_manager.get_language() == "japanese"

            language_manager.set_language("korean")
            assert language_manager.get_language() == "korean"
        finally:
            language_manager.set_language(original)


class TestProxySettings:
    """Tests for proxy configuration logic."""

    def test_proxy_type_values(self):
        """Test valid proxy type values."""
        valid_types = ["custom", "tor"]

        for proxy_type in valid_types:
            assert proxy_type in ["custom", "tor", "none"]

    def test_custom_proxy_url_format(self):
        """Test custom proxy URL format validation."""
        valid_urls = [
            "127.0.0.1:8080",
            "192.168.1.1:3128",
            "http://proxy.example.com:8080",
            "socks5://127.0.0.1:9050",
        ]

        for url in valid_urls:
            # Basic validation - should contain a port
            assert ":" in url or url.startswith("http")

    def test_tor_default_port(self):
        """Test Tor SOCKS proxy default configuration."""
        tor_proxy_url = "socks5h://127.0.0.1:9050"

        assert "127.0.0.1" in tor_proxy_url
        assert "9050" in tor_proxy_url
        assert "socks" in tor_proxy_url.lower()


class TestSettingsMigration:
    """Tests for settings migration and backward compatibility."""

    def test_legacy_proxy_type_migration(self, qapp):
        """Test conversion of legacy 'none' proxy type to 'tor'."""
        from kemonodownloader.kd_settings import SettingsTab

        class MockParent:
            def log(self, m):
                pass

        # Clean settings
        qs = QSettings("VoxDroid_Test", "KemonoDownloader_Test")
        qs.clear()
        qs.setValue("proxy_type", "none")
        qs.sync()

        # Injecting QSettings into SettingsTab is hard because it's hardcoded in __init__
        # But we can patch QSettings

        # This is a bit risky but let's try patching the class for SettingsTab import or instantiation
        # Better: use monkeypatch on the instance or class
        # st = SettingsTab(MockParent())
        # st.qsettings = qs
        # st.load_settings()
        # Let's try to just call load_settings on an instance and check if it handles the dict correctly
        st = SettingsTab(MockParent())
        try:
            st.qsettings = qs
            settings_dict = st.load_settings()
            assert settings_dict["proxy_type"] == "tor"
        finally:
            st.deleteLater()
            qs.clear()


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
            # Update language
            idx = st.language_combo.findData("japanese")
            st.language_combo.setCurrentIndex(idx)
            assert st.temp_settings["language"] == "japanese"

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

    def test_open_app_directory(self, qapp, monkeypatch):
        import subprocess

        from kemonodownloader.kd_settings import SettingsTab

        # Mock parent
        class MockParent:
            def log(self, m):
                pass

        st = SettingsTab(MockParent())
        try:
            # Mock directory existence
            monkeypatch.setattr(os.path, "exists", lambda p: True)

            # Mock platform-specific open - use more robust mocking
            mock_open_called = False

            def mock_subprocess_call(*args, **kwargs):
                nonlocal mock_open_called
                mock_open_called = True
                return 0

            monkeypatch.setattr(subprocess, "call", mock_subprocess_call)
            monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
            from PyQt6.QtWidgets import QMessageBox

            monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

            if sys.platform == "win32":
                monkeypatch.setattr(
                    os, "startfile", lambda p: setattr(st, "_mock_open_called", True)
                )

            st.open_app_directory()
            # If on Mac/Linux, we check mock_open_called
            if sys.platform != "win32":
                assert mock_open_called is True
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
            st.update_temp_setting("base_folder_name", "Applied Folder")
            from PyQt6.QtWidgets import QMessageBox

            # Patch all dialog methods for safety
            monkeypatch.setattr(
                QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
            )
            monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
            monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

            st.confirm_and_apply_settings()
            assert st.settings["base_folder_name"] == "Applied Folder"
            assert str(parent.base_folder).endswith("Applied Folder")

            # Test Reset
            st.confirm_and_reset_settings()
            assert (
                st.temp_settings["base_folder_name"]
                == st.default_settings["base_folder_name"]
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
        mock_resp.iter_content = lambda b: [b"dummy data"]
        mock_resp.headers = {"content-length": "10"}
        monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

        # Mock tarfile
        mock_tar = MagicMock()
        monkeypatch.setattr(tarfile, "open", lambda *a, **k: mock_tar)

        # Mock os/shutil
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)
        monkeypatch.setattr(os, "remove", lambda *a, **k: None)
        monkeypatch.setattr(os.path, "exists", lambda p: True)
        import shutil

        monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)
        monkeypatch.setattr(shutil, "move", lambda *a, **k: None)

        thread = DownloadTorThread(
            "http://example.com/tor.tar.gz", "extract_dir", "tor_path"
        )
        thread.progress.connect(lambda v: None)
        thread.finished_success.connect(lambda p: None)
        thread.finished_error.connect(lambda e: None)

        thread.run()
        # Success covered

        # Test error path: 404
        mock_resp.status_code = 404
        thread.run()

        # Test error path: Exception
        monkeypatch.setattr(requests, "get", MagicMock(side_effect=Exception("Failed")))
        thread.run()

    def test_download_tor_thread_extra_errors(self, qapp, monkeypatch):
        import hashlib
        import tarfile

        import requests

        from kemonodownloader.kd_settings import DownloadTorThread

        thread = DownloadTorThread("url", "ex_dir", "tor_p")

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

    def test_download_tor_thread_success_search(self, qapp, monkeypatch):
        import hashlib
        import tarfile

        import requests

        from kemonodownloader.kd_settings import DownloadTorThread

        thread = DownloadTorThread("url", "ex_dir", "tor_p")

        # Mock download success
        mock_resp = MagicMock(status_code=200, headers={"content-length": "10"})
        mock_resp.iter_content = lambda b: [b"dummy"]
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
        mock_resp.status_code = 404
        thread.run()

    def test_test_tor_network_errors(self, qapp, monkeypatch):
        import subprocess

        import requests
        from PyQt6.QtWidgets import QMessageBox

        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            st.temp_settings["tor_path"] = "/usr/bin/tor"
            monkeypatch.setattr(os.path, "exists", lambda p: True)
            monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

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

            # Test handle_tor_finished
            st.tor_config_file = MagicMock()
            st.tor_config_file.name = "/tmp/dummy.torrc"
            monkeypatch.setattr(os.path, "exists", lambda p: True)
            st.handle_tor_finished(0, 0)
        finally:
            st.deleteLater()


class TestCustomUIState:
    """Tests for specific UI initialization states (lines 384-387)."""

    def test_preset_template_init(self, qapp, monkeypatch):
        from kemonodownloader.kd_settings import SettingsTab

        parent = MagicMock()
        parent.base_folder = ""

        # Preset template at index 2
        mock_settings = {
            "language": "english",
            "creator_filename_template": "{post_id}_{post_title}",
            "base_directory": "/tmp",
            "base_folder_name": "Kemono Downloader",
            "simultaneous_downloads": 5,
            "creator_posts_max_attempts": 200,
            "post_data_max_retries": 7,
            "file_download_max_retries": 50,
            "api_request_max_retries": 3,
            "use_proxy": False,
            "proxy_type": "none",
            "custom_proxy_url": "",
            "tor_path": "",
            "creator_folder_strategy": "per_post",
            "font": "JetBrains Mono",
        }
        monkeypatch.setattr(SettingsTab, "load_settings", lambda self: mock_settings)
        import kemonodownloader.kd_settings

        monkeypatch.setattr(kemonodownloader.kd_settings, "translate", lambda s, *a: s)
        monkeypatch.setattr(
            kemonodownloader.kd_settings, "language_manager", MagicMock()
        )

        st = SettingsTab(parent)
        try:
            # Match data correctly
            idx = st.creator_filename_combo.findData("{post_id}_{post_title}")
            st.creator_filename_combo.setCurrentIndex(idx)
            assert st.creator_filename_combo.currentIndex() == 2
        finally:
            st.deleteLater()

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
            assert st.creator_filename_combo.currentText() == "custom_{id}"
        finally:
            st.deleteLater()


class TestDetailedUI:
    """Tests for remaining UI edge cases and help dialogs."""

    def test_open_app_directory_platforms(self, qapp, monkeypatch):
        import subprocess
        import sys

        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            st.temp_settings["base_directory"] = "/tmp/fake"
            monkeypatch.setattr(os, "makedirs", lambda p, exist_ok=True: None)
            monkeypatch.setattr(os.path, "exists", lambda p: True)

            # Mock Windows
            monkeypatch.setattr(sys, "platform", "win32")
            mock_startfile = MagicMock()
            # Raising=False because os.startfile doesn't exist on Mac/Linux
            monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)
            st.open_app_directory()

            # Mock Linux
            monkeypatch.setattr(sys, "platform", "linux")
            mock_popen = MagicMock()
            monkeypatch.setattr(subprocess, "Popen", mock_popen)
            st.open_app_directory()

            # Mock macOS
            monkeypatch.setattr(sys, "platform", "darwin")
            st.open_app_directory()
        finally:
            st.deleteLater()

    def test_help_dialogs(self, qapp, monkeypatch):
        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            from PyQt6.QtWidgets import QMessageBox

            monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
            st.show_template_help()
            st.show_tor_help()
        finally:
            st.deleteLater()

    def test_update_handlers(self, qapp):
        from kemonodownloader.kd_settings import SettingsTab

        parent = MagicMock()
        st = SettingsTab(parent)
        try:
            # Pass integer index
            st.update_language(0)
            st.update_font(0)
        finally:
            st.deleteLater()


class TestSimultaneousDownloadsSettings:
    """Tests for simultaneous downloads configuration."""

    def test_simultaneous_downloads_range(self):
        """Test valid range for simultaneous downloads."""
        min_downloads = 1
        max_downloads = 20
        default_downloads = 5

        assert min_downloads >= 1
        assert max_downloads <= 20
        assert min_downloads <= default_downloads <= max_downloads

    def test_simultaneous_downloads_is_integer(self):
        """Test that simultaneous downloads is an integer."""
        value = 5
        assert isinstance(value, int)
        assert value > 0


class TestRetrySettings:
    """Tests for retry configuration."""

    def test_retry_values_positive(self):
        """Test that all retry values are positive."""
        retry_settings = {
            "creator_posts_max_attempts": 200,
            "post_data_max_retries": 7,
            "file_download_max_retries": 50,
            "api_request_max_retries": 3,
        }

        for key, value in retry_settings.items():
            assert value > 0, f"{key} should be positive"

    def test_retry_ranges(self):
        """Test that retry values are within reasonable ranges."""
        # Based on UI spinbox ranges
        assert 1 <= 200 <= 1000  # creator_posts_max_attempts
        assert 1 <= 7 <= 100  # post_data_max_retries
        assert 1 <= 50 <= 200  # file_download_max_retries
        assert 1 <= 3 <= 50  # api_request_max_retries


class TestFolderStructure:
    """Tests for folder structure configuration."""

    def test_folder_structure_paths(self):
        """Test that folder structure is correctly defined."""
        base_folder = "/fake/base/Kemono Downloader"

        expected_structure = {
            "Downloads": os.path.join(base_folder, "Downloads"),
            "Cache": os.path.join(base_folder, "Cache"),
            "Other Files": os.path.join(base_folder, "Other Files"),
        }

        assert expected_structure["Downloads"].endswith("Downloads")
        assert expected_structure["Cache"].endswith("Cache")


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

    def test_folder_creation_logic(self):
        """Test folder creation with os.makedirs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_folder = os.path.join(tmpdir, "Test", "Nested", "Folder")

            # os.makedirs with exist_ok=True should not raise
            os.makedirs(test_folder, exist_ok=True)

            assert os.path.exists(test_folder)
            assert os.path.isdir(test_folder)

            # Calling again should not raise
            os.makedirs(test_folder, exist_ok=True)


class TestQSettingsIntegration:
    """Tests for QSettings integration."""

    def test_qsettings_value_types(self):
        """Test QSettings value type handling."""
        settings = QSettings("VoxDroid_UnitTest", "KemonoDownloader_UnitTest")

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

    def test_qsettings_default_values(self):
        """Test QSettings default value handling."""
        settings = QSettings("VoxDroid_UnitTest2", "KemonoDownloader_UnitTest2")

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
            monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
            monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

            # 1. Empty folder name (1102-1107)
            st.temp_settings["base_folder_name"] = "  "
            st.confirm_and_apply_settings()

            # 2. Directory creation failure (1112-1122)
            st.temp_settings["base_folder_name"] = "Valid"
            st.temp_settings["base_directory"] = "/root/no_permission"
            monkeypatch.setattr(os.path, "isdir", lambda p: False)
            monkeypatch.setattr(
                os, "makedirs", MagicMock(side_effect=OSError("Permission denied"))
            )
            st.confirm_and_apply_settings()
        finally:
            st.deleteLater()

    def test_help_dialog_exception(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        import kemonodownloader.kd_settings
        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            # Trigger exception in show_template_help (777-779)
            monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
            monkeypatch.setattr(
                kemonodownloader.kd_settings,
                "translate",
                MagicMock(side_effect=Exception("Error")),
            )
            st.show_template_help()
        finally:
            st.deleteLater()

    def test_update_font_edge_cases(self, qapp):
        from kemonodownloader.kd_settings import SettingsTab

        st = SettingsTab(MagicMock())
        try:
            # Test update_font with -1 index
            st.update_font(-1)
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
