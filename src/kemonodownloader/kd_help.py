"""One modeless help window shared by the app's info buttons.

The Sort rules editor keeps its own inline help page: it has an editor to
return to, so a Back button there means something different. Every other
info button uses this window, which keeps the last topic visible and lets a
new help button replace the content in place instead of stacking dialogs.
"""

from __future__ import annotations

import math
import re

from PyQt6.QtCore import QPoint, QSize
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from kemonodownloader.kd_language import translate
from kemonodownloader.kd_theme import BUTTON_BG, PANEL_BG, TEXT_MUTED, WINDOW_BG, scoped

# A help window should stay readable rather than filling the screen. Short
# topics use only the space their text needs; long topics stop growing and
# scroll inside the browser.
MIN_WIDTH = 360
MIN_HEIGHT = 140
MIN_CONTENT_WIDTH = 340
MAX_CONTENT_WIDTH = 720
# The screen itself is the real height limit; this only keeps a pathological
# topic from asking for an absurd window on an unusually tall display.
MAX_HEIGHT = 2000
# Keep only a small gutter at the screen edge. The previous 80px cap, combined
# with display scaling, could leave a tall topic a few pixels too short.
SCREEN_MARGIN = 24
# Space kept beside the content for the browser's vertical scrollbar, so the
# text is measured at least as narrow as it will actually be rendered.
SCROLLBAR_ALLOWANCE = 24

_RICH_TEXT = re.compile(r"</?[A-Za-z][^>]*>")
_HELP_BUTTON_STYLE = scoped(
    "QPushButton", f"background: {BUTTON_BG}; padding: 8px; border-radius: 5px;"
)
_RELATED_BUTTON_STYLE = scoped(
    "QPushButton", f"background: {BUTTON_BG}; padding: 5px; border-radius: 5px;"
)

# Reference topics reached through the Related buttons in contextual help.
# Keeping the mapping here means the text is rendered once and can be reached
# from every keyword or punctuation help topic.
_REFERENCE_TOPICS = {
    "keyword-syntax": ("keyword_syntax_help_title", "keyword_syntax_help_text"),
    "punctuation-matching": (
        "punctuation_matching_help_title",
        "punctuation_matching_help_text",
    ),
}
_RELATED_TOPICS = {
    "keyword-syntax": ("punctuation-matching",),
    "punctuation-matching": ("keyword-syntax",),
}


class HelpWindow(QDialog):
    """A reusable, modeless browser for one help topic at a time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(False)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.setSizeGripEnabled(False)
        self.setStyleSheet(f"background: {WINDOW_BG}; color: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.setStyleSheet(
            f"background: {PANEL_BG}; border-radius: 5px; color: white;"
        )
        layout.addWidget(self._browser, 1)

        self._related_bar = QWidget()
        self._related_layout = QHBoxLayout(self._related_bar)
        self._related_layout.setContentsMargins(0, 0, 0, 0)
        self._related_layout.setSpacing(6)
        self._related_bar.setVisible(False)
        layout.addWidget(self._related_bar)

        buttons = QHBoxLayout()
        self._back_button = QPushButton(translate("back"))
        self._back_button.setStyleSheet(_HELP_BUTTON_STYLE)
        self._back_button.clicked.connect(self._go_back)
        self._back_button.setVisible(False)
        buttons.addWidget(self._back_button)
        buttons.addStretch()

        self._close_button = QPushButton(translate("close"))
        self._close_button.setStyleSheet(_HELP_BUTTON_STYLE)
        self._close_button.clicked.connect(self.close)
        buttons.addWidget(self._close_button)
        layout.addLayout(buttons)

        self._history = []
        self._current_topic = None

    def show_topic(self, title, text, topic_id=None, related=()):
        """Show *text* under *title*, replacing any previous topic.

        Opening a fresh help button starts a new trail. Related-topic buttons
        keep history for the Back button.
        """
        self._history.clear()
        self._set_content(title, text, topic_id, related)
        self._present()

    def _set_content(self, title, text, topic_id=None, related=()):
        self._current_topic = (title, text, topic_id, tuple(related))
        self.setWindowTitle(title)
        self._back_button.setText(translate("back"))
        self._close_button.setText(translate("close"))
        self._back_button.setVisible(bool(self._history))

        is_rich = bool(_RICH_TEXT.search(text or ""))
        if is_rich:
            self._browser.setHtml(text)
        else:
            self._browser.setPlainText(text or "")
        self._browser.verticalScrollBar().setValue(0)
        self._update_related(related)
        self._fit_to_content(text or "", is_rich)

    def _update_related(self, related):
        while self._related_layout.count():
            item = self._related_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        topic_ids = [topic_id for topic_id in related if topic_id in _REFERENCE_TOPICS]
        if not topic_ids:
            self._related_bar.setVisible(False)
            return

        label = QLabel(translate("related_help"))
        label.setStyleSheet(f"color: {TEXT_MUTED};")
        self._related_layout.addWidget(label)
        label.show()
        for topic_id in topic_ids:
            title_key, _text_key = _REFERENCE_TOPICS[topic_id]
            button = QPushButton(translate(title_key).removesuffix(" Help"))
            button.setStyleSheet(_RELATED_BUTTON_STYLE)
            button.clicked.connect(
                lambda _checked=False, target=topic_id: self._follow_topic(target)
            )
            self._related_layout.addWidget(button)
            # Widgets added to a layout start hidden, and hidden widgets do
            # not contribute a size hint until the event loop runs. Show them
            # now so this pass can size the window to the bar it just built.
            button.show()
        self._related_layout.addStretch()
        self._related_bar.setVisible(True)
        self._related_bar.adjustSize()

    def _fit_to_content(self, text, is_rich):
        """Resize to the content, independent of the previous window size."""
        document = QTextDocument()
        document.setDefaultFont(self._browser.font())
        document.setDocumentMargin(0)
        if is_rich:
            document.setHtml(text)
        else:
            document.setPlainText(text)
        document.setTextWidth(-1)
        ideal = int(document.idealWidth() or document.size().width() or 0)

        margins = self.layout().contentsMargins()
        button_height = max(
            self._back_button.sizeHint().height(),
            self._close_button.sizeHint().height(),
        )
        related_visible = not self._related_bar.isHidden()
        related_hint = self._related_bar.sizeHint() if related_visible else QSize(0, 0)
        related_height = related_hint.height() if related_visible else 0

        # The Related bar can be wider than the text, so it takes part in the
        # width decision; sizing from the text alone squeezed its buttons.
        content_width = max(MIN_CONTENT_WIDTH, ideal, related_hint.width())
        content_width = min(content_width, MAX_CONTENT_WIDTH)
        width = content_width + margins.left() + margins.right() + SCROLLBAR_ALLOWANCE

        screen = self.screen() or QApplication.primaryScreen()
        max_width = (
            MAX_CONTENT_WIDTH + margins.left() + margins.right() + SCROLLBAR_ALLOWANCE
        )
        max_height = MAX_HEIGHT
        if screen is not None:
            available = screen.availableGeometry()
            max_width = min(
                max_width, max(MIN_WIDTH, available.width() - SCREEN_MARGIN)
            )
            max_height = min(
                max_height, max(MIN_HEIGHT, available.height() - SCREEN_MARGIN)
            )
        width = min(width, max_width)

        # Measure at the width the browser really gets after every cap, less
        # its frame and vertical scrollbar, then add the document margin the
        # browser itself draws around the text. Measuring the full width made
        # the height too short and clipped the final line once a scrollbar
        # appeared.
        scrollbar_width = max(
            SCROLLBAR_ALLOWANCE,
            self._browser.verticalScrollBar().sizeHint().width(),
        )
        chrome_width = 2 * self._browser.frameWidth() + scrollbar_width
        viewport_width = max(1, width - margins.left() - margins.right() - chrome_width)
        document.setTextWidth(viewport_width)
        content_height = math.ceil(document.size().height())
        content_height += math.ceil(self._browser.document().documentMargin() * 2)
        # A pixel or two of layout rounding must not hide the final line.
        content_height += 2

        # Only the widgets that are actually visible add a gap between them.
        gaps = 2 if related_visible else 1
        height = (
            content_height
            + margins.top()
            + margins.bottom()
            + button_height
            + related_height
            + self.layout().spacing() * gaps
        )
        height = max(MIN_HEIGHT, height)
        height = min(height, max_height)

        was_visible = self.isVisible()
        old_center = self.frameGeometry().center() if was_visible else None
        self.resize(width, height)
        if was_visible and old_center is not None:
            frame = self.frameGeometry()
            frame.moveCenter(old_center)
            self.move(frame.topLeft())

    def _present(self):
        first_show = not self.isVisible()
        if self.isMinimized():
            self.showNormal()
        elif first_show:
            self.show()
        if first_show:
            self._center_on_parent()
        self.raise_()
        self.activateWindow()
        self._browser.setFocus()

    def _center_on_parent(self):
        parent = self.parentWidget()
        target = parent.window() if parent is not None else None
        screen = self.screen() or QApplication.primaryScreen()
        frame = self.frameGeometry()
        if target is not None and target.isVisible():
            frame.moveCenter(target.frameGeometry().center())
        elif screen is not None:
            frame.moveCenter(screen.availableGeometry().center())

        if screen is not None:
            available = screen.availableGeometry()
            x = min(
                max(frame.left(), available.left()),
                available.right() - frame.width() + 1,
            )
            y = min(
                max(frame.top(), available.top()),
                available.bottom() - frame.height() + 1,
            )
            frame.moveTopLeft(QPoint(x, y))
        self.move(frame.topLeft())

    def _follow_topic(self, topic_id):
        topic = _REFERENCE_TOPICS.get(topic_id)
        if topic is None:
            return
        if self._current_topic is not None:
            self._history.append(self._current_topic)
        self._set_content(
            translate(topic[0]),
            translate(topic[1]),
            topic_id=topic_id,
            related=_RELATED_TOPICS.get(topic_id, ()),
        )
        self._present()

    def _go_back(self):
        if not self._history:
            return
        title, text, topic_id, related = self._history.pop()
        self._set_content(title, text, topic_id=topic_id, related=related)
        self._present()


_fallback_window = None


def _help_window_for(host):
    global _fallback_window
    if host is None:
        if _fallback_window is None:
            _fallback_window = HelpWindow()
        return _fallback_window

    window = getattr(host, "_help_window", None)
    if not isinstance(window, HelpWindow):
        parent = host if isinstance(host, QWidget) else None
        window = HelpWindow(parent)
        try:
            host._help_window = window
        except Exception:
            # A deliberately unusual test double can refuse attributes. The
            # returned window still works for that call.
            pass
    return window


def show_help(host, title, text, topic_id=None, related=()):
    """Show *title*/*text* in the help window owned by *host*.

    The host is normally the main window, so the Creator and Settings tabs
    share one window and can hot-swap topics.
    """
    window = _help_window_for(host)
    window.show_topic(title, text, topic_id=topic_id, related=related)
    return window
