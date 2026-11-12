"""Tests for the full log window's incremental updates.

``LogsWindow`` used to call ``setHtml()`` on a 500 ms timer, which rebuilt the
document and threw the view back to the top on every tick. It now appends only
the lines it has not drawn yet, so the scroll position survives.
"""

from PyQt6.QtWidgets import QWidget

from kemonodownloader.creator_downloader import LogsWindow


class StoreParent(QWidget):
    """Minimal parent exposing the shared log store API."""

    def __init__(self, lines=None):
        super().__init__()
        self._lines = list(lines or [])

    def log_lines_from(self, index):
        return self._lines[index:]

    def log_next_index(self):
        return len(self._lines)

    def add_lines(self, count, prefix="line"):
        for i in range(count):
            self._lines.append((f"{prefix} {len(self._lines)}", "green"))

    @property
    def line_count(self):
        return len(self._lines)


def make_window(qtbot, parent):
    window = LogsWindow(parent)
    qtbot.addWidget(window)
    window.resize(320, 120)
    window.show()
    qtbot.wait(20)
    return window


def test_new_lines_are_appended_without_losing_the_scroll_position(qtbot):
    parent = StoreParent()
    parent.add_lines(200)
    window = make_window(qtbot, parent)

    window.needs_update = True
    window._do_update()
    bar = window.logs_display.verticalScrollBar()
    assert bar.maximum() > 0

    bar.setValue(bar.maximum() // 2)
    middle = bar.value()
    assert middle > 0

    parent.add_lines(5, prefix="extra")
    window.needs_update = True
    window._do_update()

    assert bar.value() == middle
    assert "extra 200" in window.logs_display.toPlainText()

    window.close()


def test_view_follows_the_bottom_when_it_was_already_there(qtbot):
    parent = StoreParent()
    parent.add_lines(200)
    window = make_window(qtbot, parent)

    window.needs_update = True
    window._do_update()
    bar = window.logs_display.verticalScrollBar()
    bar.setValue(bar.maximum())

    parent.add_lines(3, prefix="tail")
    window.needs_update = True
    window._do_update()

    assert bar.value() == bar.maximum()
    assert "tail 202" in window.logs_display.toPlainText()

    window.close()


def test_each_update_only_draws_the_new_lines(qtbot):
    parent = StoreParent()
    parent.add_lines(3)
    window = make_window(qtbot, parent)

    window.needs_update = True
    window._do_update()
    assert window._shown == 3

    parent.add_lines(2, prefix="later")
    window.needs_update = True
    window._do_update()

    assert window._shown == 5
    text = window.logs_display.toPlainText()
    assert text.count("line 0") == 1  # nothing duplicated
    assert "later 3" in text

    window.close()

