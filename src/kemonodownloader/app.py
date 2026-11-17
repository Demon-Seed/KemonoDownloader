from __future__ import annotations

import os
import sys
import warnings

import qtawesome as qta
from bs4 import MarkupResemblesLocatorWarning
from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QFont, QFontDatabase, QIcon, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from kemonodownloader import kd_paths
from kemonodownloader.creator_downloader import CreatorDownloaderTab
from kemonodownloader.kd_errors import install_exception_hook
from kemonodownloader.kd_language import translate
from kemonodownloader.kd_settings import GITHUB_REPO_URL, SettingsTab
from kemonodownloader.kd_theme import MENU_STYLE, TOOLTIP_STYLE, WINDOW_BG

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
        # Posts go straight into the configured Save Directory; the app's own
        # working files (databases and saved config profiles) live in the Data
        # Directory so a library folder only ever contains saved posts.
        self.download_folder = self.settings_tab.settings["base_directory"]
        self.other_files_folder = kd_paths.other_files_dir(
            self.settings_tab.settings.get("data_directory")
        )
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
            self.download_folder,
            self.other_files_folder,
        ]:
            kd_paths.ensure_directory(folder, "application folder")

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
        main_widget.setStyleSheet(f"background: {WINDOW_BG};")

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

        self.tabs.addTab(
            self.settings_tab,
            qta.icon("fa5s.cog", color="white"),
            translate("settings_tab"),
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
                (self.settings_tab, "settings_tab"),
            ):
                index = self.tabs.indexOf(widget)
                if index != -1:
                    self.tabs.setTabText(index, translate(key))

            self.status_label.setText(translate("idle"))
            self.dev_label.setText(self._footer_text())

            self.creator_tab.refresh_ui()
            self.settings_tab.update_ui_text()

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

    def closeEvent(self, event):
        """Stop background helpers that are not part of a download run."""
        stop = getattr(self.creator_tab, "stop_name_lookups", None)
        if callable(stop):
            stop()
        super().closeEvent(event)


# Qt's QTipLabel expires after 10 s plus 40 ms per character past 100 (see
# QTipLabel::restartExpireTimer), and the style hints that used to tune this
# (SH_ToolTip_WakeUpDelay / FallAsleepDelay) are no longer read by QToolTip.
# The event filter below therefore stretches each widget's display time to int
# max and hides the tip itself, so hover help stays on screen for as long as
# the pointer actually rests on the widget.
TOOLTIP_HOVER_TIME = 2**31 - 1  # ms, effectively forever

# How long the pointer must rest on a widget before its tooltip appears. Qt's
# own wake-up delay is platform-dependent (~700 ms on Windows) and grows again
# right after another tip closes, which made hover help feel inconsistent. The
# filter below times the tip itself so every widget answers in the same 350 ms.
TOOLTIP_HOVER_DELAY = 350  # ms
# Movement smaller than this does not restart the rest timer, so a jittery
# hand cannot postpone the tip forever.
TOOLTIP_MOVE_THRESHOLD = 2  # px


class _TooltipLifetimeFilter(QObject):
    """Show hover help promptly, then keep it up while the widget is hovered."""

    # QTipLabel gives itself this object name; hiding it directly skips Qt's
    # 300 ms fade-out timer, which made tooltips trail behind the pointer.
    TOOLTIP_OBJECT_NAME = "qtooltip_label"

    def __init__(self, parent=None, hide=QToolTip.hideText):
        super().__init__(parent)
        self._hide = hide
        self._owner = None
        # A clicked widget keeps its tip hidden until the pointer leaves, so a
        # tooltip never pops back up under a resting cursor.
        self._suppressed = None
        # True while the tip is on screen, so moving within the widget does not
        # restart the rest timer (which would hide and re-show it).
        self._shown = False
        self._arm_pos = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(TOOLTIP_HOVER_DELAY)
        self._timer.timeout.connect(self._show_now)

    def _arm(self, widget, moved=False):
        """(Re)start the rest timer for *widget*.

        *moved* is True for HoverMove: tiny jitter does not restart the clock,
        but any real movement puts the tip back to waiting for the pointer to
        rest again.
        """
        if widget is not self._owner:
            self._hide_now()
            self._owner = widget
        if self._shown:
            return
        pos = QCursor.pos()
        if moved and self._arm_pos is not None:
            if (pos - self._arm_pos).manhattanLength() < TOOLTIP_MOVE_THRESHOLD:
                return
        self._arm_pos = pos
        self._timer.start()

    def _show_now(self):
        """Show the hovered widget's tip now, at the pointer."""
        owner = self._owner
        if owner is None or owner is self._suppressed:
            return
        try:
            text = owner.toolTip()
        except RuntimeError:  # owner deleted while the timer ran
            self._owner = None
            return
        if not text:
            return
        self._shown = True
        # QWidget::event() passes toolTipDuration() to QToolTip::showText(),
        # so this stops Qt's own expiry while the pointer rests on the widget;
        # Leave hides the tip below.
        owner.setToolTipDuration(TOOLTIP_HOVER_TIME)
        QToolTip.showText(QCursor.pos(), text, owner)

    def _hide_now(self):
        """Hide the tooltip without waiting for Qt's fade-out timer."""
        if (
            not self._shown
            and self._owner is None
            and not self._timer.isActive()
            and not QToolTip.isVisible()
        ):
            # Nothing on screen and nothing pending: keyboards and wheels fire
            # this often, so skip the top-level walk entirely.
            return
        self._timer.stop()
        self._owner = None
        self._shown = False
        self._arm_pos = None
        self._hide()
        for widget in QApplication.topLevelWidgets():
            if widget.objectName() == self.TOOLTIP_OBJECT_NAME and widget.isVisible():
                widget.hide()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.Polish:
            if isinstance(obj, QWidget) and not obj.testAttribute(
                Qt.WidgetAttribute.WA_Hover
            ):
                # Hover events are what tell the filter that the pointer is
                # still resting on a widget after a scroll, key press or tiny
                # move - Enter alone only fires when the widget is entered.
                obj.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        elif kind == QEvent.Type.Enter:
            if isinstance(obj, QWidget):
                try:
                    text = obj.toolTip() if obj.isEnabled() else ""
                except RuntimeError:
                    text = ""
                if obj is self._suppressed:
                    # A click can make Qt re-enter the widget under the
                    # pointer; that is the same hover, so stay quiet until a
                    # real Leave arrives.
                    return False
                if text:
                    self._arm(obj)
        elif kind in (QEvent.Type.HoverEnter, QEvent.Type.HoverMove):
            if isinstance(obj, QWidget) and obj is not self._suppressed:
                try:
                    text = obj.toolTip() if obj.isEnabled() else ""
                except RuntimeError:
                    text = ""
                if text:
                    self._arm(obj, moved=True)
        elif kind == QEvent.Type.ToolTip:
            if isinstance(obj, QWidget):
                if obj is self._suppressed:
                    # Clicked or typed on: stay quiet until the pointer leaves.
                    return True
                if obj is self._owner:
                    # Hover tracking already owns this hover; never show on
                    # Qt's platform-dependent schedule.
                    return True
                if obj.underMouse():
                    # Qt's tip can wake before Enter reaches the filter (its
                    # event is "awake" right after another tip), so arm the
                    # timer instead of showing instantly. Whichever event
                    # arrives first, the tip waits the same 350 ms.
                    self._arm(obj)
                    return True
                # A synthetic help event with no hover behind it: let Qt show
                # it, but track the owner so Leave still hides it.
                self._owner = obj
                obj.setToolTipDuration(TOOLTIP_HOVER_TIME)
        elif kind in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            if obj is self._owner:
                # Moving off the widget means the tip should vanish at once.
                self._hide_now()
            if obj is self._suppressed:
                self._suppressed = None
        elif kind in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
        ):
            self._suppressed = self._owner
            self._hide_now()
        elif kind in (QEvent.Type.Wheel, QEvent.Type.KeyPress):
            # Do not suppress: the next movement over the widget arms the tip
            # again, so its delay stays the same after scrolling or typing.
            self._hide_now()
        elif kind == QEvent.Type.Hide and obj is self._owner:
            # The owner is gone, so nothing is being hovered any more.
            self._hide_now()
        elif kind == QEvent.Type.Hide and obj is self._suppressed:
            # Drop the reference to a hidden widget so it is not held alive.
            self._suppressed = None
        return False


def install_tooltip_lifetime(app):
    """Keep hover help on screen while its widget is hovered."""
    if not isinstance(app, QObject):
        # Tests replace QApplication with a stub; there is nothing to filter.
        return None
    event_filter = _TooltipLifetimeFilter(app)
    app.installEventFilter(event_filter)
    # Keep the Python wrapper alive next to its C++ parent.
    app._tooltip_lifetime_filter = event_filter
    return event_filter


def disable_ui_effects():
    """Turn off Qt's popup and tooltip animations.

    The combo popup animation and the tooltip fades made the hover help feel
    flickery and delayed; the widgets are instant without them.
    """
    setter = getattr(QApplication, "setEffectEnabled", None)
    if not callable(setter):
        # Tests replace QApplication with a stub; there is nothing to toggle.
        return
    for effect in (
        Qt.UIEffect.UI_AnimateCombo,
        Qt.UIEffect.UI_AnimateTooltip,
        Qt.UIEffect.UI_FadeTooltip,
    ):
        setter(effect, False)


def main():
    app = QApplication(sys.argv)
    # Without this, an exception that escapes a slot, an event handler or a
    # worker's run() calls qFatal() and ends the process with no message.
    install_exception_hook()
    app.setStyle("Fusion")
    # Standard edit menus on plain line edits are shown by Qt itself with
    # popup(), so no per-widget code can style them. Application-wide rules
    # give every context menu the same dark surface and low-opacity hover
    # highlight, and every tooltip the same dark background.
    app.setStyleSheet(MENU_STYLE + TOOLTIP_STYLE)
    disable_ui_effects()
    tooltip_filter = install_tooltip_lifetime(app)
    load_bundled_fonts()
    window = KemonoDownloader()
    window.show()
    exit_code = app.exec()
    # Detach before shutdown: Qt keeps dispatching events while it destroys the
    # window, and calling into a Python filter while the interpreter is being
    # torn down crashes natively (an access violation on exit).
    if tooltip_filter is not None:
        app.removeEventFilter(tooltip_filter)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()  # pragma: no cover
