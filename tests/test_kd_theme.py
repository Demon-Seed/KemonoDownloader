"""Tests for the shared theme: checkbox glyphs and button hover states."""

import os
import re

from kemonodownloader import kd_theme


def test_checkbox_style_has_a_check_and_a_partial_glyph():
    style = kd_theme.checkbox_style()

    assert "width: 16px" in style
    assert "height: 16px" in style
    assert "border-radius: 4px" in style
    assert "QCheckBox::indicator:hover" in style
    assert "QCheckBox::indicator:checked" in style
    assert "QCheckBox::indicator:indeterminate" in style
    assert "QCheckBox::indicator:disabled" in style
    assert "check_f2f3f5.png" in style
    assert "minus_f2f3f5.png" in style

    paths = re.findall(r"image: url\('([^']+)'\)", style)
    assert len(paths) == 2
    assert all(os.path.isfile(path) for path in paths)


def test_checkbox_style_recovers_a_deleted_glyph():
    first = kd_theme.checkbox_style()
    assert first == kd_theme.checkbox_style()

    path = re.search(r"image: url\('([^']+check[^']+)'\)", first).group(1)
    os.remove(path)
    second = kd_theme.checkbox_style()

    rebuilt = re.search(r"image: url\('([^']+check[^']+)'\)", second).group(1)
    assert "check_f2f3f5.png" in second
    assert os.path.isfile(rebuilt)


def test_button_states_cover_hover_pressed_and_disabled():
    style = kd_theme.button_states()

    assert "QPushButton:hover" in style
    assert "QPushButton:pressed" in style
    assert "QPushButton:disabled" in style

    coloured = kd_theme.button_states("#111111", "#222222")
    assert "#111111" in coloured
    assert "#222222" in coloured


def test_theme_stylesheet_covers_inputs_lists_progress_and_tabs():
    style = kd_theme.theme_stylesheet()

    assert "QLineEdit" in style
    assert "QLineEdit:focus" in style
    assert kd_theme.FOCUS in style
    assert "QComboBox::down-arrow" in style
    assert "QListWidget" in style
    assert "QProgressBar" in style
    assert "text-align: center" in style
    assert "QTabBar::tab:selected" in style
    assert "QPushButton:hover" in style
    assert "QCheckBox::indicator:checked" in style
