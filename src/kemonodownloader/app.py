from __future__ import annotations

import os
import sys
import warnings

import qtawesome as qta
from bs4 import MarkupResemblesLocatorWarning
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QFontDatabase, QIcon, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from kemonodownloader.creator_downloader import CreatorDownloaderTab
from kemonodownloader.kd_extension import ExtensionTab
from kemonodownloader.kd_help import HelpTab
from kemonodownloader.kd_language import translate
from kemonodownloader.kd_settings import GITHUB_REPO_URL, SettingsTab
from kemonodownloader.post_downloader import PostDownloaderTab

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

CURRENT_VERSION = "5.11.1"

# Available Google Fonts bundled with the app
BUNDLED_FONTS = {
    "JetBrains Mono": [
        "JetBrainsMono-Regular.ttf",
        "JetBrainsMono-Bold.ttf",
        "JetBrainsMono-Medium.ttf",
    ],
    "Poppins": [
        "Poppins-Regular.ttf",
        "Poppins-Bold.ttf",
        "Poppins-Medium.ttf",
    ],
}


def load_bundled_fonts():
    """Load all bundled Google Fonts into the application font database."""
    fonts_dir = os.path.join(os.path.dirname(__file__), "resources", "fonts")
    for font_family, font_files in BUNDLED_FONTS.items():
        for font_file in font_files:
            font_path = os.path.join(fonts_dir, font_file)
            if os.path.exists(font_path):
                QFontDatabase.addApplicationFont(font_path)


def resource_path(relative_path):
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return os.path.join(meipass, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)


class KemonoDownloader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(translate("app_title"))
        self.setGeometry(100, 100, 1000, 700)

        self.settings_tab = SettingsTab(self)
        self.settings_tab.download_started.connect(self.disable_other_tabs)
        self.settings_tab.download_finished.connect(self.enable_other_tabs)
        self.base_folder = os.path.join(
            self.settings_tab.settings["base_directory"],
            self.settings_tab.settings["base_folder_name"],
        )
        self.download_folder = os.path.join(self.base_folder, "Downloads")
        self.cache_folder = os.path.join(self.base_folder, "Cache")
        self.other_files_folder = os.path.join(self.base_folder, "Other Files")
        self.ensure_folders_exist()

        self.setWindowIcon(QIcon(resource_path("resources/KemonoDownloader.png")))

        # The main interface is built during startup: there is no intro/"launch"
        # splash screen, so the default tab is usable immediately.
        self.main_widget = self.setup_main_ui()
        self.setCentralWidget(self.main_widget)
        self.apply_palette()

        self.settings_tab.language_changed.connect(self.update_all_ui)
        self.settings_tab.font_changed.connect(self.apply_font)

        # Apply the saved font setting
        self.apply_font(self.settings_tab.get_font())

    def _footer_text(self):
        """Build the footer text with a clickable link to the main repository."""
        return (
            f"{translate('developed_by')} | "
            f'<a href="{GITHUB_REPO_URL}" style="color: #A0C0FF; '
            f'text-decoration: none;">GitHub: VoxDroid/KemonoDownloader</a> | '
            f"{translate('current_version', CURRENT_VERSION)}"
        )

    def apply_font(self, font_family: str):
        """Apply the selected font family to the entire application and all widgets."""
        app = QApplication.instance()
        if app:
            font = QFont(font_family)
            font.setPointSize(app.font().pointSize())
            app.setFont(font)
        # Update all existing widgets that have explicit fonts set
        self._apply_font_recursive(self, font_family)
        # Refresh help and extension tabs if they exist
        if hasattr(self, "help_tab"):
            self.help_tab.update_ui_text()
        if hasattr(self, "extension_tab"):
            self.extension_tab.update_ui_text()

    def _apply_font_recursive(self, widget, font_family: str):
        """Recursively update the font family on all child widgets."""
        current_font = widget.font()
        current_font.setFamily(font_family)
        widget.setFont(current_font)
        for child in widget.findChildren(QWidget):
            child_font = child.font()
            child_font.setFamily(font_family)
            child.setFont(child_font)

    def apply_palette(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#1A2A44"))
        palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Base, QColor("#2A3B5A"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#3A4B6A"))
        palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Button, QColor("#3A5B7A"))
        palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        self.setPalette(palette)

    def ensure_folders_exist(self):
        for folder in [
            self.base_folder,
            self.download_folder,
            self.cache_folder,
            self.other_files_folder,
        ]:
            os.makedirs(folder, exist_ok=True)

    def disable_other_tabs(self):
        if hasattr(self, "tabs"):
            for i in range(self.tabs.count()):
                if self.tabs.widget(i) != self.settings_tab:
                    self.tabs.setTabEnabled(i, False)

    def enable_other_tabs(self):
        if hasattr(self, "tabs"):
            for i in range(self.tabs.count()):
                self.tabs.setTabEnabled(i, True)

    def setup_main_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        main_widget.setStyleSheet("background: #1A2A44;")

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: none;
                background: #1A2A44;
            }
            QTabBar::tab {
                background: #3A4B6A;
                color: white;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 100px;
            }
            QTabBar::tab:selected {
                background: #4A5B7A;
                color: white;
            }
            QTabBar::tab:!selected {
                margin-top: 2px;
            }
            QTabBar::tab:disabled {
                color: gray;
            }
            * {
                color: white;
            }
        """
        )
        main_layout.addWidget(self.tabs)

        # Add Tabs. The Creator Downloader tab is placed first and selected by
        # default, as it is the primary workflow of the application.
        self.creator_tab = CreatorDownloaderTab(self)
        self.tabs.addTab(
            self.creator_tab,
            qta.icon("fa5s.user-edit", color="white"),
            translate("creator_downloader_tab"),
        )

        self.post_tab = PostDownloaderTab(self)
        self.tabs.addTab(
            self.post_tab,
            qta.icon("fa5s.download", color="white"),
            translate("post_downloader_tab"),
        )

        self.tabs.addTab(
            self.settings_tab,
            qta.icon("fa5s.cog", color="white"),
            translate("settings_tab"),
        )

        self.help_tab = HelpTab(self)
        self.tabs.addTab(
            self.help_tab,
            qta.icon("fa5s.question-circle", color="white"),
            translate("help_tab"),
        )

        self.extension_tab = ExtensionTab(self)
        self.tabs.addTab(
            self.extension_tab,
            qta.icon("fa5s.puzzle-piece", color="white"),
            translate("extension_tab"),
        )

        # Creator Downloader is the tab selected on launch.
        self.tabs.setCurrentIndex(0)

        # Footer
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 5, 10, 5)
        self.status_label = QLabel(translate("idle"))
        self.status_label.setStyleSheet("color: white; font-size: 12px;")
        footer_layout.addWidget(self.status_label)
        footer_layout.addStretch()
        self.dev_label = QLabel(self._footer_text())
        self.dev_label.setTextFormat(Qt.TextFormat.RichText)
        self.dev_label.setOpenExternalLinks(True)
        self.dev_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.dev_label.setStyleSheet("color: white; font-size: 12px;")
        footer_layout.addWidget(self.dev_label)
        main_layout.addWidget(footer)

        return main_widget

    def update_all_ui(self):
        self.setWindowTitle(translate("app_title"))

        if self.main_widget:
            # Resolve tab labels by widget so the tab order can change freely.
            for widget, key in (
                (self.creator_tab, "creator_downloader_tab"),
                (self.post_tab, "post_downloader_tab"),
                (self.settings_tab, "settings_tab"),
                (self.help_tab, "help_tab"),
                (self.extension_tab, "extension_tab"),
            ):
                index = self.tabs.indexOf(widget)
                if index != -1:
                    self.tabs.setTabText(index, translate(key))

            if (
                self.status_label.text() == "Idle"
                or self.status_label.text() == "アイドル"
                or self.status_label.text() == "대기 중"
            ):
                self.status_label.setText(translate("idle"))

            self.dev_label.setText(self._footer_text())

            self.post_tab.refresh_ui()
            self.creator_tab.refresh_ui()
            self.settings_tab.update_ui_text()
            self.help_tab.update_ui_text()
            self.extension_tab.update_ui_text()

    def animate_button(self, button, enter):
        anim = QPropertyAnimation(button, b"geometry")
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        rect = button.geometry()
        if enter:
            anim.setEndValue(rect.adjusted(-3, -3, 3, 3))
        else:
            anim.setEndValue(rect.adjusted(3, 3, -3, -3))
        anim.start()

    def log(self, message):
        self.status_label.setText(message)
        print(message)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    load_bundled_fonts()
    window = KemonoDownloader()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()  # pragma: no cover
