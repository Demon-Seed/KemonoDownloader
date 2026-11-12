"""The mouse wheel scrolls the Settings page; it never changes a value.

Qt hands the wheel to spin boxes, combo boxes and sliders, so scrolling the
page with the cursor over one of them used to change the setting under it.
"""

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from kemonodownloader.kd_settings import SettingsTab


class _Parent:
    download_folder = ""
    cache_folder = ""
    other_files_folder = ""

    def ensure_folders_exist(self):
        pass

    def log(self, message):
        pass


def _wheel(widget, delta=-120):
    """Send one wheel tick to *widget*, as the mouse would."""
    event = QWheelEvent(
        QPointF(5.0, 5.0),
        QPointF(5.0, 5.0),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_the_wheel_does_not_change_a_number(qapp):
    tab = SettingsTab(_Parent())
    try:
        tab.download_spinbox.setValue(7)
        tab.download_slider.setValue(7)

        _wheel(tab.download_spinbox)
        _wheel(tab.download_slider)

        assert tab.download_spinbox.value() == 7
        assert tab.download_slider.value() == 7
        assert tab.temp_settings["simultaneous_downloads"] == 7
    finally:
        tab.deleteLater()


def test_the_wheel_does_not_change_a_dropdown(qapp):
    tab = SettingsTab(_Parent())
    try:
        combo = tab.creator_unique_filenames_combo
        before = combo.currentIndex()

        _wheel(combo)

        assert combo.currentIndex() == before
        assert tab.temp_settings["creator_unique_filenames"] == "both"
    finally:
        tab.deleteLater()


def test_the_wheel_still_scrolls_the_page(qapp):
    tab = SettingsTab(_Parent())
    try:
        tab.resize(900, 300)
        tab.show()
        QApplication.processEvents()
        bar = tab.scroll_area.verticalScrollBar()
        if bar.maximum() == 0:
            pytest.skip("the settings page fits this viewport")
        bar.setValue(0)

        # Over a spin box: no value moves, the page scrolls instead.
        _wheel(tab.download_spinbox)
        QApplication.processEvents()

        assert bar.value() > 0
    finally:
        tab.close()
        tab.deleteLater()
