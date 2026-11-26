"""Tests for the shared theme: checkbox glyphs and button hover states."""

import os
import re

from kemonodownloader import kd_theme


def test_checkbox_style_has_a_complete_image_for_every_state():
    style = kd_theme.checkbox_style()

    assert "width: 16px" in style
    assert "height: 16px" in style
    assert "QCheckBox::indicator:hover" in style
    assert "QCheckBox::indicator:checked" in style
    assert "QCheckBox::indicator:indeterminate" in style
    assert "QCheckBox::indicator:disabled" in style
    assert "checkbox_unchecked_2b2d31.png" in style
    assert "checkbox_unchecked_hover_2b2d31.png" in style
    assert "checkbox_checked_4863b8.png" in style
    assert "checkbox_minus_4863b8.png" in style
    assert "checkbox_disabled_323439.png" in style
    assert "checkbox_disabled_checked_323439.png" in style
    assert "checkbox_disabled_minus_323439.png" in style

    paths = re.findall(r"image: url\('([^']+)'\)", style)
    assert len(paths) == 7
    assert all(os.path.isfile(path) for path in paths)


def test_checkbox_style_recovers_a_deleted_image():
    first = kd_theme.checkbox_style()
    assert first == kd_theme.checkbox_style()

    path = re.search(r"image: url\('([^']+checkbox_checked[^']+)'\)", first).group(1)
    os.remove(path)
    second = kd_theme.checkbox_style()

    rebuilt = re.search(r"image: url\('([^']+checkbox_checked[^']+)'\)", second).group(
        1
    )
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
