"""Tests for the Creator-tab run summary block.

The stats of a finished run used to be written into the log only; they now sit
under the progress bars, with a per-filter breakdown of what was skipped.
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


def test_summary_and_retry_are_visible_from_the_start(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    # The stat block is populated at startup (zeros), never blank.
    assert "Downloaded: 0" in tab.creator_download_summary_label.text()
    posts_text = tab.creator_skip_summary_label.text()
    assert "Skipped Posts: 0" in posts_text
    assert "Post keywords 0" in posts_text
    files_text = tab.creator_skip_files_label.text()
    assert "Skipped Files: 0" in files_text
    assert "Archived images 0" in files_text

    # Retry is always on screen, just greyed out until there is work for it.
    assert tab.creator_retry_failed_btn.isVisibleTo(tab) is True
    assert tab.creator_retry_failed_btn.isEnabled() is False


def test_summary_reports_downloaded_and_failed(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.completed_files = {"a", "b", "c"}
    tab.failed_files = {"d": "boom", "e": "boom"}

    tab._update_download_summary()

    text = tab.creator_download_summary_label.text()
    assert "Downloaded: 3" in text
    assert "Failed: 2" in text


def test_skip_breakdown_names_every_filter(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._post_skip_stats = {"keywords": 2, "date": 5, "file_count": 1}
    tab._file_skip_count = 4
    tab._images_skipped_count = 3

    tab._update_download_summary(0, 0, refresh_skips=True)

    text = tab.creator_skip_summary_label.text()
    assert "Skipped Posts: 8" in text  # posts only: 2 + 5 + 1
    assert "Post keywords 2" in text
    assert "Date 5" in text
    assert "File count 1" in text

    files_text = tab.creator_skip_files_label.text()
    assert "Skipped Files: 7" in files_text  # 4 + 3
    assert "File keywords 4" in files_text
    assert "Archived images 3" in files_text


def test_every_filter_is_listed_even_at_zero(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._post_skip_stats = {"keywords": 0, "date": 1, "file_count": 0}

    tab._update_download_summary(0, 0, refresh_skips=True)

    text = tab.creator_skip_summary_label.text()
    assert "Skipped Posts: 1" in text
    assert "Date 1" in text
    assert "Post keywords 0" in text
    assert "File keywords" not in text

    files_text = tab.creator_skip_files_label.text()
    assert "Skipped Files: 0" in files_text
    assert "File keywords 0" in files_text
    assert "Archived images 0" in files_text

    assert tab.creator_skip_summary_label.toolTip() == "No keyword skips"
    # The file row always says when its numbers move.
    assert "download runs" in tab.creator_skip_files_label.toolTip()


def test_skip_tooltip_lists_keywords_with_counts(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._post_keyword_skip_counts = {"AlienComic": 5, "sketch": 2}
    tab._file_keyword_skip_counts = {"JP": 3}

    tab._update_download_summary(0, 0, refresh_skips=True)

    lines = tab.creator_skip_summary_label.toolTip().splitlines()
    assert lines[0] == "Posts skipped by keyword:"
    # Most frequent first.
    assert lines[1] == "  AlienComic: 5"
    assert lines[2] == "  sketch: 2"

    file_lines = tab.creator_skip_files_label.toolTip().splitlines()
    # The keyword part reads exactly like the posts row, note last.
    assert file_lines[0] == "Files skipped by keyword:"
    assert "  JP: 3" in file_lines
    assert file_lines[-1] == (
        "Archived images are counted when a download runs, not from the list."
    )


def test_failed_counter_turns_red_only_after_a_failure(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    tab._update_download_summary(3, 0)
    assert "#E06C75" not in tab.creator_download_summary_label.text()

    tab._update_download_summary(3, 2)
    assert "#E06C75" in tab.creator_download_summary_label.text()

    tab._update_download_summary(3, 0)
    assert "#E06C75" not in tab.creator_download_summary_label.text()


def test_a_late_second_finish_does_not_reset_the_stats(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.creator_queue = ["https://kemono.cr/patreon/user/1"]
    tab.completed_files = {"a", "b"}
    tab.failed_files = {"c": "boom"}
    tab.files_to_posts_map = {"c": "post-1"}

    tab.creator_download_finished()  # finalised by the last file_completed
    tab.creator_download_finished()  # late cleanup_thread pass

    text = tab.creator_download_summary_label.text()
    assert "Downloaded: 2" in text
    assert "Failed: 1" in text
    assert tab.creator_retry_failed_btn.isEnabled() is True


def test_retry_button_sits_with_the_run_controls(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.creator_retry_failed_btn.parentWidget() is (
        tab.creator_download_btn.parentWidget()
    )
    assert tab.creator_retry_failed_btn.parentWidget() is (
        tab.creator_cancel_btn.parentWidget()
    )
    # It lives on the left with the run controls, not next to the log.
    assert tab.creator_retry_failed_btn.parentWidget() is not (
        tab.creator_log_toggle_btn.parentWidget()
    )


def test_stats_survive_the_end_of_the_run(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.creator_queue = ["https://kemono.cr/patreon/user/1"]
    tab.completed_files = {"a", "b"}
    tab.failed_files = {"c": "boom"}
    tab.files_to_posts_map = {"c": "post-1"}

    tab.creator_download_finished()

    assert tab.failed_files == {}  # counters are reset...
    text = tab.creator_download_summary_label.text()
    assert "Downloaded: 2" in text  # ...but the stats stay on screen
    assert "Failed: 1" in text


def test_retry_button_enables_only_with_failures(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.creator_queue = ["https://kemono.cr/patreon/user/1"]
    tab.completed_files = {"a"}
    tab.failed_files = {"c": "boom"}
    tab.files_to_posts_map = {"c": "post-1"}

    tab.creator_download_finished()

    assert tab.creator_retry_failed_btn.isVisibleTo(tab) is True
    assert tab.creator_retry_failed_btn.isEnabled() is True
    assert tab.creator_retry_failed_btn.text() == "Retry Failed Downloads"
    assert set(tab._last_run_failed_files) == {"c"}

    tab._last_run_failed_files = {}
    tab._last_run_files_to_posts_map = {}
    tab._refresh_retry_button()
    assert tab.creator_retry_failed_btn.isVisibleTo(tab) is True
    assert tab.creator_retry_failed_btn.isEnabled() is False


def test_post_filter_counters_feed_the_summary(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    detection_thread = SimpleNamespace(
        keyword_skipped_count=3,
        date_skipped_count=7,
        file_count_skipped_count=2,
    )

    tab._refresh_skip_summary_from_filter(detection_thread)

    text = tab.creator_skip_summary_label.text()
    assert "Post keywords 3" in text
    assert "Date 7" in text
    assert "File count 2" in text
    assert "Skipped Posts: 12" in text


def test_new_run_keeps_post_skips_but_clears_run_stats(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.completed_files = {"a", "b"}
    tab.failed_files = {"c": "boom"}
    tab.files_to_posts_map = {"c": "post-1"}
    tab._post_skip_stats = {"keywords": 4, "date": 0, "file_count": 0}
    tab._update_download_summary(refresh_skips=True)
    tab._last_run_failed_files = {"c": "boom"}
    tab._last_run_files_to_posts_map = {"c": "post-1"}
    tab._refresh_retry_button()

    tab.completed_files.clear()
    tab.failed_files.clear()
    tab._reset_download_summary(keep_post_stats=True)

    text = tab.creator_download_summary_label.text()
    assert "Downloaded: 0" in text and "Failed: 0" in text
    assert "Post keywords 4" in tab.creator_skip_summary_label.text()
    assert tab._last_run_failed_files == {}
    assert tab.creator_retry_failed_btn.isEnabled() is False


def test_skip_tooltip_keys_translated_in_all_languages():
    from kemonodownloader.kd_language import language_manager, translate

    keys = [
        "skip_tooltip_post_keywords",
        "skip_tooltip_file_keywords",
        "skip_tooltip_no_keywords",
    ]
    original = language_manager.current_language
    try:
        for language in language_manager.get_available_languages():
            language_manager.set_language(language)
            for key in keys:
                assert translate(key) not in ("", key)
    finally:
        language_manager.set_language(original)


def test_refresh_ui_resets_the_summary_and_retry(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.downloading = False
    tab._post_skip_stats = {"keywords": 2, "date": 0, "file_count": 0}
    tab._last_run_failed_files = {"https://x/y.jpg": "boom"}
    tab._last_run_files_to_posts_map = {"https://x/y.jpg": "post-1"}
    tab._refresh_retry_button()

    tab.refresh_ui()

    # The block stays populated (zeros) instead of going blank.
    assert "Downloaded: 0" in tab.creator_download_summary_label.text()
    assert "Skipped Posts: 0" in tab.creator_skip_summary_label.text()
    assert tab.creator_retry_failed_btn.isVisibleTo(tab) is True
    assert tab.creator_retry_failed_btn.isEnabled() is False
    assert tab._last_run_failed_files == {}


def test_failed_counter_names_the_post_count(qtbot, tmp_path):
    """Four files failing in one post reads as "4 files (1 post)"."""
    tab = make_tab(qtbot, tmp_path)
    tab.failed_files = {f"https://n/{i}.jpg": "boom" for i in range(4)}
    tab.files_to_posts_map = {f"https://n/{i}.jpg": "post-1" for i in range(4)}

    tab._update_download_summary(0, 4)

    assert "Failed: 4 files (1 post)" in tab.creator_download_summary_label.text()


def test_failed_counter_pluralises_multiple_posts(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.failed_files = {f"https://n/{i}.jpg": "boom" for i in range(3)}
    tab.files_to_posts_map = {
        "https://n/0.jpg": "post-1",
        "https://n/1.jpg": "post-1",
        "https://n/2.jpg": "post-2",
    }

    tab._update_download_summary(0, 3)

    assert "Failed: 3 files (2 posts)" in tab.creator_download_summary_label.text()


def test_failed_counter_falls_back_when_posts_are_unknown(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.failed_files = {"https://n/orphan.jpg": "boom"}
    tab.files_to_posts_map = {}

    tab._update_download_summary(0, 1)

    text = tab.creator_download_summary_label.text()
    assert "Failed: 1" in text
    assert "files (" not in text


def test_failed_counter_falls_back_to_the_last_run_map(qtbot, tmp_path):
    """After finalising, the live map is empty but the snapshot is not."""
    tab = make_tab(qtbot, tmp_path)
    tab.failed_files = {"https://n/a.jpg": "boom", "https://n/b.jpg": "boom"}
    tab.files_to_posts_map = {}
    tab._last_run_files_to_posts_map = {
        "https://n/a.jpg": "post-9",
        "https://n/b.jpg": "post-9",
    }

    tab._update_download_summary(0, 2)

    assert "Failed: 2 files (1 post)" in tab.creator_download_summary_label.text()


def test_progress_and_summary_sit_in_their_own_group(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    for widget in (
        tab.creator_file_progress,
        tab.creator_overall_progress,
        tab.creator_download_summary_label,
        tab.creator_skip_summary_label,
        tab.creator_skip_files_label,
    ):
        assert tab.run_summary_group.isAncestorOf(widget)

    for button in (
        tab.creator_download_btn,
        tab.creator_cancel_btn,
        tab.creator_retry_failed_btn,
    ):
        assert not tab.run_summary_group.isAncestorOf(button)

    assert tab.run_summary_group.title() == "Run Summary"


def test_skip_rows_colour_reflects_the_state(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    # Nothing loaded yet: white, the resting state.
    assert "white" in tab.creator_skip_summary_label.styleSheet()
    assert "white" in tab.creator_skip_files_label.styleSheet()

    # A loaded list with nothing skipped: sand.
    tab.all_detected_posts = [("A post", ("1", None))]
    tab._skip_summary_cache = None
    tab._update_download_summary(0, 0, refresh_skips=True)
    assert "#E5C07B" in tab.creator_skip_summary_label.styleSheet()

    # Something skipped: green, while the file row keeps its own state.
    tab._post_skip_stats = {
        "keywords": 1,
        "date": 0,
        "file_count": 0,
        "filetypes": 0,
    }
    tab._skip_summary_cache = None
    tab._update_download_summary(0, 0, refresh_skips=True)
    assert "#7BD88F" in tab.creator_skip_summary_label.styleSheet()
    assert "#E5C07B" in tab.creator_skip_files_label.styleSheet()
