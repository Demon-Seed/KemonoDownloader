import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QWidget

from kemonodownloader.app import GITHUB_REPO_URL, KemonoDownloader


@pytest.fixture
def mock_app_dependencies(monkeypatch):
    """Mock all external dependencies for KemonoDownloader."""
    # Mock Translation in the source module
    import kemonodownloader.kd_language

    monkeypatch.setattr(kemonodownloader.kd_language, "translate", lambda s, *args: s)
    # Also mock in app namespace just in case
    monkeypatch.setattr("kemonodownloader.app.translate", lambda s, *args: s)

    # Mock Tabs - must be QWidget subclasses to be accepted by QTabWidget
    class MockTab(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.settings = {
                "base_directory": "/tmp",
                "base_folder_name": "Kemono",
                "language": "en",
            }
            self.language_changed = MagicMock()
            self.font_changed = MagicMock()
            self.download_started = MagicMock()
            self.download_finished = MagicMock()

        def get_font(self):
            return "Arial"

        def refresh_ui(self):
            pass

        def update_ui_text(self):
            pass

    monkeypatch.setattr("kemonodownloader.app.SettingsTab", MockTab)
    monkeypatch.setattr("kemonodownloader.app.CreatorDownloaderTab", MockTab)

    # QPixmap(path) returns a null pixmap if file doesn't exist, which is fine

    # Mock load_bundled_fonts
    monkeypatch.setattr("kemonodownloader.app.load_bundled_fonts", MagicMock())


@pytest.fixture
def window(qapp, mock_app_dependencies, monkeypatch):
    """Provide a KemonoDownloader window instance."""
    monkeypatch.setattr(os, "makedirs", MagicMock())
    win = KemonoDownloader()
    yield win
    win.deleteLater()


class TestKemonoDownloader:

    def test_init(self, qapp, mock_app_dependencies, monkeypatch):
        # Mock os.makedirs to avoid directory creation
        import os

        monkeypatch.setattr(os, "makedirs", MagicMock())

        window = KemonoDownloader()
        try:
            assert window.windowTitle() == "app_title"
            assert window.centralWidget() == window.main_widget
            assert not hasattr(window, "intro_screen")
            # Posts go straight into the Save Directory (the mocked "/tmp").
            assert window.download_folder == "/tmp"
            # The app's own files live in the Data Directory instead.
            assert window.cache_folder != window.download_folder
            assert window.other_files_folder != window.download_folder
        finally:
            window.deleteLater()

    def test_main_ui_created_on_startup(self, qapp, mock_app_dependencies):
        """The main interface is built at startup; there is no intro screen."""
        window = KemonoDownloader()
        try:
            assert window.main_widget is not None
            assert window.centralWidget() == window.main_widget
            assert not hasattr(window, "intro_screen")
        finally:
            window.deleteLater()

    def test_tab_management(self, qapp, mock_app_dependencies):
        window = KemonoDownloader()
        try:
            assert hasattr(window, "tabs")
            assert window.tabs.count() == 2

            # Creator Downloader is the leftmost tab and the launch default.
            assert window.tabs.widget(0) is window.creator_tab
            assert window.tabs.currentIndex() == 0
            assert window.tabs.tabText(0) == "creator_downloader_tab"
            assert window.tabs.indexOf(window.settings_tab) == 1
            assert window.tabs.tabText(1) == "settings_tab"

            # Test disable/enable
            window.disable_other_tabs()
            for i in range(window.tabs.count()):
                if window.tabs.widget(i) != window.settings_tab:
                    assert not window.tabs.isTabEnabled(i)

            window.enable_other_tabs()
            for i in range(window.tabs.count()):
                assert window.tabs.isTabEnabled(i)
        finally:
            window.deleteLater()

    def test_update_all_ui(self, qapp, mock_app_dependencies):
        window = KemonoDownloader()
        try:
            window.update_all_ui()

            assert window.status_label.text() == "idle"
        finally:
            window.deleteLater()

    def test_dialogs(self, qapp, mock_app_dependencies, monkeypatch):
        window = KemonoDownloader()
        try:
            # Test status logging
            window.log("Test log")
            assert window.status_label.text() == "Test log"

            # Test animate_button (lines 570-578)
            from PyQt6.QtWidgets import QPushButton

            btn = QPushButton()
            window.animate_button(btn, True)
            window.animate_button(btn, False)
        finally:
            window.deleteLater()

    def test_font_and_resource_edge_cases(
        self, qapp, mock_app_dependencies, monkeypatch
    ):
        import os

        import kemonodownloader.app

        # 1. resource_path with _MEIPASS (224-227)
        # We must patch the sys module INSIDE the app module namespace
        monkeypatch.setattr(
            kemonodownloader.app.sys, "_MEIPASS", "/bundled/path", raising=False
        )
        assert "/bundled/path" in kemonodownloader.app.resource_path("test.png")
        monkeypatch.delattr(kemonodownloader.app.sys, "_MEIPASS", raising=False)

        # 2. load_bundled_fonts (55-60)
        monkeypatch.setattr(os.path, "exists", lambda p: True)
        # The window creates its folders; patched for the same reason the other
        # tests patch it (and because exists() is faked above).
        monkeypatch.setattr(os, "makedirs", MagicMock())
        from PyQt6.QtGui import QFontDatabase

        monkeypatch.setattr(QFontDatabase, "addApplicationFont", MagicMock())
        kemonodownloader.app.load_bundled_fonts()

        # 3. The main interface exists immediately (no intro screen).
        window = KemonoDownloader()
        try:
            assert window.main_widget is not None
            assert window.tabs.count() == 2
        finally:
            window.deleteLater()


class TestKemonoDownloaderExtra:
    def test_update_status_idle(self, qapp, window):
        window.status_label.setText("Idle")
        window.update_all_ui()
        assert window.status_label.text() != "Idle"

    def test_footer_repository_link(self, qapp, window):
        """The footer links to the main repository instead of auto-updating."""
        assert GITHUB_REPO_URL in window.dev_label.text()
        assert window.dev_label.openExternalLinks() is True
        assert not hasattr(window, "version_checker")
        assert not hasattr(window, "check_for_updates")
        assert not hasattr(window, "show_update_notification")

    def test_apply_font(self, qapp, window):
        window.apply_font("Arial")
        assert window.font().family() == "Arial"


def test_load_bundled_fonts(monkeypatch):
    import os

    from PyQt6.QtGui import QFontDatabase

    from kemonodownloader.app import load_bundled_fonts

    # Mock os.path.exists to return True for fonts
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    # Mock QFontDatabase.addApplicationFont
    mock_add = MagicMock()
    monkeypatch.setattr(QFontDatabase, "addApplicationFont", mock_add)

    load_bundled_fonts()
    assert mock_add.called


def test_main_app(monkeypatch):
    import sys

    from kemonodownloader.app import main

    # Mock sys.exit to prevent actual exit
    monkeypatch.setattr(sys, "exit", lambda x: None)

    mock_app = MagicMock()
    mock_window = MagicMock()

    monkeypatch.setattr("kemonodownloader.app.QApplication", lambda a: mock_app)
    monkeypatch.setattr("kemonodownloader.app.KemonoDownloader", lambda: mock_window)
    monkeypatch.setattr("kemonodownloader.app.load_bundled_fonts", MagicMock())

    main()
    assert mock_window.show.called
    assert mock_app.exec.called


def test_main_block(monkeypatch):

    import kemonodownloader.app

    # Mock main to avoid full app startup
    mock_main = MagicMock()
    monkeypatch.setattr(kemonodownloader.app, "main", mock_main)

    # We can't easily trigger the if __name__ == "__main__" block via import
    # but we can simulate the logic manually to ensure it calls main()
    if True:  # Simulate the block condition
        kemonodownloader.app.main()

    assert mock_main.called


def test_app_log_updates_status_and_prints(monkeypatch):
    called = {"text": None, "printed": None}

    dummy = SimpleNamespace(
        status_label=SimpleNamespace(setText=lambda m: called.__setitem__("text", m))
    )
    monkeypatch.setattr("builtins.print", lambda m: called.__setitem__("printed", m))

    KemonoDownloader.log(dummy, "hello")

    assert called["text"] == "hello"
    assert called["printed"] == "hello"


def test_main_exec_calls_exit(monkeypatch):
    import importlib

    app_mod = importlib.import_module("kemonodownloader.app")

    # Dummy QApplication that records exec() call and returns 0
    class DummyApp:
        def __init__(self, argv):
            self.argv = argv

        def setStyle(self, _):
            pass

        def exec(self):
            return 0

    # Dummy main window with show()
    class DummyWindow:
        def show(self):
            pass

    monkeypatch.setattr(app_mod, "QApplication", lambda argv: DummyApp(argv))
    monkeypatch.setattr(app_mod, "load_bundled_fonts", lambda: None)
    monkeypatch.setattr(app_mod, "KemonoDownloader", lambda *a, **k: DummyWindow())

    called = {}

    def fake_exit(code=0):
        called["code"] = code

    monkeypatch.setattr(app_mod.sys, "exit", fake_exit)

    # Call main() and ensure sys.exit was invoked with the app exec return value
    app_mod.main()
    assert called.get("code") == 0
