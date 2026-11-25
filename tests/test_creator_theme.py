"""Theme checks for the Creator tab: actions, console panels and progress bars."""

from PyQt6.QtCore import Qt
from tests.factories import make_tab_parent

from kemonodownloader import creator_downloader as cd, kd_theme


def _make_tab(qtbot, tmp_path):
    tab = cd.CreatorDownloaderTab(make_tab_parent(tmp_path))
    qtbot.addWidget(tab)
    return tab


def test_download_is_the_bold_accent_button():
    style = cd._PRIMARY_BUTTON_STYLE

    assert kd_theme.ACCENT in style
    assert "font-weight: bold" in style
    assert kd_theme.ACCENT_HOVER in style
    assert kd_theme.ACCENT_PRESSED in style


def test_cancel_uses_danger_and_grays_out_when_disabled(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)

    style = tab.creator_cancel_btn.styleSheet()
    assert kd_theme.DANGER in style
    assert "QPushButton:disabled" in style
    assert kd_theme.DISABLED_BG in style
    assert tab.creator_cancel_btn.isEnabled() is False


def test_posts_progress_bar_shows_a_centered_percentage(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)

    for bar in (tab.creator_file_progress, tab.creator_overall_progress):
        assert bar.format() == "%p%"
        assert bar.isTextVisible() is True
        assert (
            bar.alignment() & Qt.AlignmentFlag.AlignCenter
        ) == Qt.AlignmentFlag.AlignCenter


def test_eye_and_deselect_buttons_carry_hover_states(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)

    for button in (tab.creator_queue_input_btn, tab.creator_deselect_btn):
        assert "QPushButton:hover" in button.styleSheet()
        assert "QPushButton:pressed" in button.styleSheet()


def test_console_panels_use_the_darker_console_colour(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)

    assert kd_theme.CONSOLE in tab.creator_queue_list.styleSheet()
    assert kd_theme.CONSOLE in tab.creator_post_list.styleSheet()

    window = cd.LogsWindow(tab)
    qtbot.addWidget(window)
    assert kd_theme.CONSOLE in window.logs_display.styleSheet()
    window.close()
