"""Tests for the minimised Creator-tab log panel.

The log used to be a permanently visible QTextEdit that grew with every
message, which made resizing the window crawl. It now minimises by default,
holds its lines in a plain list, and only touches the widget while open.
"""

from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


def make_parent(tmp_path):
    class FakeTabs:
        def count(self):
            return 1

        def currentIndex(self):
            return 0

        def setTabEnabled(self, i, enabled):
            pass

    settings_tab = SimpleNamespace(
        settings_applied=SimpleNamespace(connect=lambda cb: None),
        language_changed=SimpleNamespace(connect=lambda cb: None),
        get_creator_posts_max_attempts=lambda: 1,
        get_post_data_max_retries=lambda: 1,
        get_file_download_max_retries=lambda: 1,
        get_api_request_max_retries=lambda: 1,
        get_simultaneous_downloads=lambda: 1,
    )
    return SimpleNamespace(
        cache_folder=str(tmp_path / "cache"),
        other_files_folder=str(tmp_path / "other"),
        download_folder=str(tmp_path / "download"),
        settings_tab=settings_tab,
        tabs=FakeTabs(),
        status_label=SimpleNamespace(setText=lambda s: None),
        animate_button=lambda *a, **k: None,
    )


def make_tab(qtbot, tmp_path):
    tab = cd.CreatorDownloaderTab(make_parent(tmp_path))
    qtbot.addWidget(tab)
    return tab


def test_log_panel_is_minimised_by_default(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.creator_console.isVisibleTo(tab) is False
    assert tab.creator_log_toggle_btn.isChecked() is False
    assert tab.creator_log_toggle_btn.text() == "Log"


def test_log_panel_sits_under_the_right_side_progress_bar(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    right_layout = tab.background_task_progress.parentWidget().layout()
    assert tab.creator_console.parentWidget() is tab.background_task_progress.parentWidget()
    assert right_layout.indexOf(tab.creator_console) > right_layout.indexOf(
        tab.background_task_progress
    )


def test_appending_while_minimised_never_touches_the_document(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    for i in range(300):
        tab.append_log_to_console(f"line {i}", "INFO")

    assert tab.creator_console.toPlainText() == ""
    assert tab.log_line_count() == 300
    assert tab.log_next_index() == 300

    tab._update_log_toggle_text()
    assert tab.creator_log_toggle_btn.text() == "Log (300)"


def test_opening_the_panel_replays_the_buffer_in_order(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.append_log_to_console("first", "INFO")
    tab.append_log_to_console("second", "WARNING")
    tab.append_log_to_console("third", "ERROR")

    tab.set_log_panel_visible(True)

    text = tab.creator_console.toPlainText()
    assert tab.creator_console.isVisibleTo(tab) is True
    assert text.index("first") < text.index("second") < text.index("third")
    html = tab.creator_console.toHtml()
    assert "#ffff00" in html and "#ff0000" in html


def test_appending_while_open_shows_up_immediately(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.set_log_panel_visible(True)

    tab.append_log_to_console("live line", "INFO")

    assert "live line" in tab.creator_console.toPlainText()


def test_open_panel_does_not_rewrite_the_toggle_label_per_line(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.append_log_to_console("seed", "INFO")
    tab.set_log_panel_visible(True)
    label_when_opened = tab.creator_log_toggle_btn.text()

    tab.append_log_to_console("live", "INFO")

    # The counter only matters while the panel is closed; rewriting it (and
    # its icon) per line was pure layout churn.
    assert tab.creator_log_toggle_btn.text() == label_when_opened
    assert "live" in tab.creator_console.toPlainText()


def test_closing_the_panel_resumes_buffering(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.set_log_panel_visible(True)
    tab.append_log_to_console("visible line", "INFO")

    tab.set_log_panel_visible(False)
    tab.append_log_to_console("buffered line", "INFO")

    assert "buffered line" not in tab.creator_console.toPlainText()
    assert tab.log_line_count() == 2


def test_log_store_is_capped(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._log_line_limit = 5

    for i in range(8):
        tab.append_log_to_console(f"line {i}", "INFO")

    remaining = [message for message, _ in tab.log_lines_from(0)]
    assert remaining == ["line 3", "line 4", "line 5", "line 6", "line 7"]
    assert tab.log_first_index() == 3
    assert tab.log_next_index() == 8


def test_views_keep_advancing_after_the_store_drops_lines(qtbot, tmp_path):
    """A view that fell behind must not freeze once old lines are trimmed."""
    tab = make_tab(qtbot, tmp_path)
    tab._log_line_limit = 3
    behind = tab.log_next_index()

    for i in range(5):
        tab.append_log_to_console(f"line {i}", "INFO")

    assert [m for m, _ in tab.log_lines_from(behind)] == [
        "line 2",
        "line 3",
        "line 4",
    ]
    assert tab.log_next_index() == 5


def test_expand_logs_window_shows_buffered_lines(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.append_log_to_console("buffered for the window", "INFO")

    tab.expand_logs()
    tab.logs_window._do_update()

    assert "buffered for the window" in tab.logs_window.logs_display.toPlainText()
    tab.logs_window.close()
    tab.logs_window.deleteLater()


def test_toggle_button_reopens_and_closes_the_panel(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    tab.toggle_log_panel()
    assert tab.creator_console.isVisibleTo(tab) is True

    tab.toggle_log_panel()
    assert tab.creator_console.isVisibleTo(tab) is False


def test_expand_logs_button_sits_beside_the_log_toggle(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    right_layout = tab.background_task_progress.parentWidget().layout()

    header = None
    for i in range(right_layout.count()):
        row = right_layout.itemAt(i).layout()
        if row is not None and row.indexOf(tab.creator_log_toggle_btn) >= 0:
            header = row
            break

    assert header is not None
    assert header.indexOf(tab.creator_expand_logs_btn) > header.indexOf(
        tab.creator_log_toggle_btn
    )
    # Same styling, so both buttons share the same height.
    assert (
        tab.creator_expand_logs_btn.styleSheet()
        == tab.creator_log_toggle_btn.styleSheet()
    )


def test_expand_logs_button_is_no_longer_with_the_run_controls(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.creator_expand_logs_btn.parentWidget() is not (
        tab.creator_download_btn.parentWidget()
    )


def test_log_panel_keys_translated_in_all_languages():
    from kemonodownloader.kd_language import language_manager, translate

    keys = [
        "log_panel_toggle",
        "log_panel_toggle_count",
        "log_panel_tooltip_show",
        "log_panel_tooltip_hide",
    ]
    original = language_manager.current_language
    try:
        for language in language_manager.get_available_languages():
            language_manager.set_language(language)
            for key in keys:
                assert translate(key, 1) not in ("", key)
    finally:
        language_manager.set_language(original)
