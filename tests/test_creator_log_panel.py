"""Tests for the Creator tab's log button and its full log window.

The inline console is gone. Lines live in a plain list, the ``Log (N)`` button
opens the expanded window, and the only widget logging touches is the button's
label (throttled). The two config buttons share that row.
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


def close_logs_window(tab):
    """Tear the expanded window down so it cannot outlive the test."""
    window = getattr(tab, "logs_window", None)
    if window is not None:
        window.close()
        window.deleteLater()


def test_verbose_logging_follows_the_settings_switch(qtbot, tmp_path):
    """The tab reads the switch on startup and again when settings apply."""
    parent = make_parent(tmp_path)
    switch = {"verbose": True}
    parent.settings_tab.get_verbose_logging = lambda: switch["verbose"]
    tab = cd.CreatorDownloaderTab(parent)
    qtbot.addWidget(tab)

    assert tab._verbose_logging is True

    switch["verbose"] = False
    tab._refresh_verbose_logging()
    assert tab._verbose_logging is False

    tab.append_log_to_console("[DEBUG] now hidden", "DEBUG")
    assert tab.log_line_count() == 0


def test_log_button_is_plain_and_says_log(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.creator_log_btn.isCheckable() is False
    assert tab.creator_log_btn.text() == "Log"
    assert tab.creator_log_btn.toolTip() == cd.translate("open_log_tooltip")
    # It sits in the log/config box, not with the run controls.
    assert tab.creator_log_btn.parentWidget() is tab.log_config_group


def test_append_only_touches_the_button_label(qtbot, tmp_path):
    """Logging must not repaint a widget per line; the label is throttled."""
    tab = make_tab(qtbot, tmp_path)

    for i in range(300):
        tab.append_log_to_console(f"line {i}", "INFO")

    assert tab.log_line_count() == 300
    assert tab.log_next_index() == 300
    # Nothing redrew the label yet: the timer owns that.
    assert tab.creator_log_btn.text() == "Log"

    tab._update_log_button_text()
    assert tab.creator_log_btn.text() == "Log (300)"


def test_log_button_opens_the_window_with_buffered_lines(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.append_log_to_console("first", "INFO")
    tab.append_log_to_console("second", "WARNING")
    tab.append_log_to_console("third", "ERROR")

    tab.open_logs()
    tab.logs_window._do_update()

    text = tab.logs_window.logs_display.toPlainText()
    assert text.index("first") < text.index("second") < text.index("third")
    # Colours come from the shared level palette, so WARNING and ERROR stay
    # distinguishable in the window.
    html = tab.logs_window.logs_display.toHtml().lower()
    assert cd.LOG_LEVEL_COLORS["WARNING"].lower() in html
    assert cd.LOG_LEVEL_COLORS["ERROR"].lower() in html
    close_logs_window(tab)


def test_open_logs_reuses_the_same_window(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.append_log_to_console("only line", "INFO")

    tab.open_logs()
    first = tab.logs_window
    tab.open_logs()

    assert tab.logs_window is first
    first._do_update()
    assert first.logs_display.toPlainText().count("only line") == 1
    close_logs_window(tab)


def test_appending_while_the_window_is_open_reaches_it(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.open_logs()

    tab.append_log_to_console("live line", "INFO")
    tab.logs_window._do_update()

    assert "live line" in tab.logs_window.logs_display.toPlainText()
    close_logs_window(tab)


def test_clear_log_empties_store_window_and_label(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.open_logs()
    tab.append_log_to_console("something", "INFO")
    tab.logs_window._do_update()
    tab._update_log_button_text()
    assert tab.creator_log_btn.text() == "Log (1)"

    tab.clear_log()

    assert tab.log_line_count() == 0
    assert tab.log_next_index() == 0
    assert tab.creator_log_btn.text() == "Log"
    assert tab.logs_window.logs_display.toPlainText() == ""
    close_logs_window(tab)


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


def test_level_to_colour_mapping_covers_every_level_and_unknowns(qtbot, tmp_path):
    """One palette for every level, unknown levels included."""
    tab = make_tab(qtbot, tmp_path)
    tab._verbose_logging = True
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "nonsense", "warning"):
        tab.append_log_to_console(f"{level} line", level)

    assert [colour for _, colour in tab.log_lines_from(0)] == [
        cd.LOG_LEVEL_COLORS["DEBUG"],
        cd.LOG_LEVEL_COLORS["INFO"],
        cd.LOG_LEVEL_COLORS["WARNING"],
        cd.LOG_LEVEL_COLORS["ERROR"],
        cd.LOG_DEFAULT_COLOR,
        cd.LOG_LEVEL_COLORS["WARNING"],  # levels are matched case-insensitively
    ]


def test_debug_lines_stay_out_of_the_log_unless_verbose_is_on(qtbot, tmp_path):
    """DEBUG is dropped by default so it never fills the line cap."""
    tab = make_tab(qtbot, tmp_path)
    tab.append_log_to_console("[DEBUG] internal bookkeeping", "DEBUG")
    tab.append_log_to_console("[INFO] run started", "INFO")
    assert [m for m, _ in tab.log_lines_from(0)] == ["[INFO] run started"]

    tab._verbose_logging = True
    tab.append_log_to_console("[DEBUG] internal bookkeeping", "DEBUG")
    assert [m for m, _ in tab.log_lines_from(0)] == [
        "[INFO] run started",
        "[DEBUG] internal bookkeeping",
    ]


def test_window_escapes_markup_in_log_lines(qtbot, tmp_path):
    """A log line must render literally, markup and all.

    The log carries text straight from the network: the 403 debug line prints
    the response body, and file names come from the server too. An unescaped
    ``<`` was parsed as markup, which swallowed the rest of the line.
    """
    tab = make_tab(qtbot, tmp_path)
    tab.open_logs()

    message = "Body: <b>blocked</b> & <script>alert(1)</script> a<b.png"
    tab.append_log_to_console(message, "INFO")
    tab.logs_window._do_update()

    # The user sees the raw text, not an interpretation of it.
    assert message in tab.logs_window.logs_display.toPlainText()
    # And the widget's own markup holds the escaped form, not the tags.
    rendered = tab.logs_window.logs_display.toHtml()
    assert "&lt;b&gt;blocked&lt;/b&gt;" in rendered
    assert "<b>blocked</b>" not in rendered
    close_logs_window(tab)


def test_log_line_html_escapes_values_it_is_given():
    rendered = cd._log_line_html("a < b & c > d", "#FFF")

    assert rendered == "<span style='color:#FFF'>a &lt; b &amp; c &gt; d</span>"


def test_config_buttons_sit_right_of_the_log_button(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    row = tab.log_config_group.layout()
    assert row.indexOf(tab.creator_log_btn) == 0
    assert row.indexOf(tab.creator_save_config_btn) == 1
    assert row.indexOf(tab.creator_save_creator_config_btn) == 2
    # Same styling, so the three buttons share one height.
    assert (
        tab.creator_save_config_btn.styleSheet()
        == tab.creator_log_btn.styleSheet()
        == tab.creator_save_creator_config_btn.styleSheet()
    )
    # They are not with the run controls any more.
    assert tab.creator_save_config_btn.parentWidget() is not (
        tab.creator_download_btn.parentWidget()
    )


def test_log_and_config_keys_are_translated():
    keys = (
        "log_panel_toggle",
        "log_panel_toggle_count",
        "open_log_tooltip",
        "save_config_btn",
        "save_config_btn_tooltip",
        "config_save_info_title",
        "config_save_info_text",
        "save_creator_config_btn",
        "save_creator_config_btn_tooltip",
    )
    for key in keys:
        assert cd.translate(key, 1) not in ("", key)


def test_the_log_row_is_not_a_group_box(qtbot, tmp_path):
    """The group box's title and border clipped the buttons, so it is a row."""
    from PyQt6.QtWidgets import QGroupBox

    tab = make_tab(qtbot, tmp_path)

    assert not isinstance(tab.log_config_group, QGroupBox)
    assert tab.log_config_group.layout() is not None
    # The old "Log & Config" title is gone with the box.
    assert cd.translate("log_and_config", 1) in ("", "log_and_config")


def test_the_info_box_sits_right_of_the_two_saves(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    row = tab.log_config_group.layout()
    assert row.indexOf(tab.creator_config_info_btn) > row.indexOf(
        tab.creator_save_config_btn
    )
    assert row.indexOf(tab.creator_config_info_btn) > row.indexOf(
        tab.creator_save_creator_config_btn
    )
    assert tab.creator_config_info_btn.toolTip() == cd.translate("config_save_info_title")


def test_the_info_box_explains_both_saves(qtbot, tmp_path, monkeypatch):
    shown = {}
    monkeypatch.setattr(
        cd.QMessageBox,
        "information",
        lambda parent, title, text: shown.update(title=title, text=text),
    )
    tab = make_tab(qtbot, tmp_path)

    tab.show_config_save_help()

    assert shown["title"] == cd.translate("config_save_info_title")
    assert "Save Config" in shown["text"]
    assert "Save Creator Config" in shown["text"]
    assert "creator_configs.db" in shown["text"]

