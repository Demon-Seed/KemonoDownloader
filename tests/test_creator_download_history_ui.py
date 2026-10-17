"""Tests for the Creator tab's "last downloaded" tracking and its info button."""

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from kemonodownloader import creator_downloader as cd
from kemonodownloader.download_history import (
    DownloadHistoryDB,
    iso_to_local_date,
)
from kemonodownloader.kd_language import language_manager, translate

STAMP = "2026-01-02T03:04:05+00:00"
STAMP_DATE = iso_to_local_date(STAMP)
CREATOR_URL = "https://kemono.cr/patreon/user/123"


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
    """Build a Creator tab; returns it plus its history directory."""
    tab = cd.CreatorDownloaderTab(make_parent(tmp_path))
    qtbot.addWidget(tab)
    return tab, str(tmp_path / "other")


def row_holding(tab, widget):
    """Return the footer row (a QHBoxLayout) of the group holding *widget*."""
    group_layout = tab.post_list_group.layout()
    for i in range(group_layout.count()):
        layout = group_layout.itemAt(i).layout()
        if layout is not None and layout.indexOf(widget) >= 0:
            return layout
    return None


def bottom_row(tab):
    """The counters row: post count plus 'Last Downloaded from Creator'."""
    return row_holding(tab, tab.creator_post_count_label)


def controls_row(tab):
    """The lower row: page indicator, arrows, thumbnail viewer, info button."""
    return row_holding(tab, tab.prev_page_btn)


def row_order(tab, layout):
    """Index of *layout* in the group's vertical layout, i.e. top-to-bottom."""
    group_layout = tab.post_list_group.layout()
    for i in range(group_layout.count()):
        if group_layout.itemAt(i).layout() is layout:
            return i
    return -1


def add_post_row(tab, key, post_id, thumbnail="thumb"):
    tab.post_url_map[key] = (post_id, thumbnail)
    tab.add_list_item(key, thumbnail, False)
    return tab.post_widget_cache[key][1]


# ---------------------------------------------------------------------------
# Creator-level label
# ---------------------------------------------------------------------------


def test_last_download_label_is_centred_and_clear_of_the_post_count(qtbot, tmp_path):
    tab, _ = make_tab(qtbot, tmp_path)

    row = bottom_row(tab)
    assert row is not None
    count_index = row.indexOf(tab.creator_post_count_label)
    label_index = row.indexOf(tab.creator_last_download_label)
    assert count_index >= 0 and label_index > count_index

    # An expanding spacer sits between the two, and another closes the row, so
    # the label is centred in the space to the right of the count.
    assert row.itemAt(count_index + 1).spacerItem() is not None
    assert row.itemAt(row.count() - 1).spacerItem() is not None
    assert tab.creator_last_download_label.alignment() == Qt.AlignmentFlag.AlignCenter


def test_box_info_button_is_right_aligned_outside_the_list(qtbot, tmp_path):
    tab, _ = make_tab(qtbot, tmp_path)

    # It lives in the Check All row, which is outside the post list widget but
    # still inside the group.
    row = row_holding(tab, tab.creator_check_all)
    assert row is not None
    assert row.indexOf(tab.creator_check_all_all) > row.indexOf(tab.creator_check_all)
    assert row.indexOf(tab.creator_box_info_btn) == row.count() - 1
    assert row.itemAt(row.count() - 2).spacerItem() is not None

    # ...and not in either of the rows below the list.
    assert bottom_row(tab).indexOf(tab.creator_box_info_btn) == -1
    assert controls_row(tab).indexOf(tab.creator_box_info_btn) == -1
    assert row_order(tab, row) < row_order(tab, controls_row(tab))


def test_eye_button_and_its_state_are_gone(qtbot, tmp_path):
    tab, _ = make_tab(qtbot, tmp_path)

    assert not hasattr(tab, "creator_view_button")
    assert not hasattr(tab, "current_preview_url")
    assert not hasattr(tab, "update_current_preview_url")


def make_modal_recorder(monkeypatch, opened):
    """Patch ImageModal with a recorder; returns nothing."""

    class FakeModal:
        def __init__(self, url, cache_dir, parent=None, settings_tab=None):
            opened.append(("open", url))

        def exec(self):
            opened.append(("exec", None))

    monkeypatch.setattr(cd, "ImageModal", FakeModal)


class RecordingEvent:
    """Stands in for the Qt mouse event passed to mouseDoubleClickEvent."""

    def __init__(self):
        self.accepted = False

    def accept(self):
        self.accepted = True


def test_row_double_click_previews_the_thumbnail(qtbot, tmp_path, monkeypatch):
    tab, _ = make_tab(qtbot, tmp_path)
    opened = []
    make_modal_recorder(monkeypatch, opened)
    widget = add_post_row(
        tab, "Title (2024-01-01)", "1", thumbnail="https://kemono.cr/t.jpg"
    )
    event = RecordingEvent()

    widget.mouseDoubleClickEvent(event)

    assert event.accepted is True
    assert opened == [("open", "https://kemono.cr/t.jpg"), ("exec", None)]


def test_list_double_click_signal_previews_too(qtbot, tmp_path, monkeypatch):
    tab, _ = make_tab(qtbot, tmp_path)
    opened = []
    make_modal_recorder(monkeypatch, opened)
    add_post_row(tab, "Title (2024-01-01)", "1", thumbnail="https://kemono.cr/t.jpg")
    item = tab.post_widget_cache["Title (2024-01-01)"][0]

    tab.creator_post_list.itemDoubleClicked.emit(item)

    assert opened == [("open", "https://kemono.cr/t.jpg"), ("exec", None)]


def test_double_click_without_a_thumbnail_does_nothing(qtbot, tmp_path, monkeypatch):
    tab, _ = make_tab(qtbot, tmp_path)
    opened = []
    make_modal_recorder(monkeypatch, opened)
    widget = add_post_row(tab, "Title (2024-01-01)", "1", thumbnail="")

    widget.mouseDoubleClickEvent(RecordingEvent())

    assert opened == []


def test_double_click_on_an_unsupported_link_only_warns(qtbot, tmp_path, monkeypatch):
    tab, _ = make_tab(qtbot, tmp_path)
    opened = []
    logged = []
    make_modal_recorder(monkeypatch, opened)
    monkeypatch.setattr(
        tab, "append_log_to_console", lambda msg, level="INFO": logged.append(level)
    )
    widget = add_post_row(
        tab, "Title (2024-01-01)", "1", thumbnail="https://kemono.cr/f.zip"
    )

    widget.mouseDoubleClickEvent(RecordingEvent())

    assert opened == []
    assert logged == ["WARNING"]


def test_pagination_arrows_sit_on_the_row_below_the_counters(qtbot, tmp_path):
    tab, _ = make_tab(qtbot, tmp_path)

    counters = bottom_row(tab)
    controls = controls_row(tab)
    assert counters is not None and controls is not None
    assert counters is not controls

    # The arrows (and the page indicator that labels them) left the counters
    # row entirely.
    for widget in (tab.prev_page_btn, tab.next_page_btn, tab.page_label):
        assert counters.indexOf(widget) == -1
        assert controls.indexOf(widget) >= 0
    assert row_order(tab, controls) > row_order(tab, counters)


def test_label_is_always_visible_showing_na_without_a_creator(qtbot, tmp_path):
    tab, _ = make_tab(qtbot, tmp_path)

    assert tab.creator_last_download_label.isHidden() is False
    assert tab.creator_last_download_label.text() == translate(
        "last_downloaded_creator", translate("not_available")
    )

    tab.current_creator_url = CREATOR_URL
    tab._load_creator_history()

    assert tab.creator_last_download_label.isHidden() is False
    assert tab.creator_last_download_label.text() == translate(
        "last_downloaded_creator", translate("never_downloaded")
    )


def test_label_shows_the_recorded_date(qtbot, tmp_path):
    tab, other_dir = make_tab(qtbot, tmp_path)
    DownloadHistoryDB(other_dir).record_post("patreon", "123", "1", STAMP)

    tab.current_creator_url = CREATOR_URL
    tab._load_creator_history()

    assert tab.creator_last_download_label.text() == translate(
        "last_downloaded_creator", STAMP_DATE
    )
    assert STAMP_DATE in tab.creator_last_download_label.text()


def test_label_uses_the_newest_post_date(qtbot, tmp_path):
    tab, other_dir = make_tab(qtbot, tmp_path)
    db = DownloadHistoryDB(other_dir)
    db.record_post("patreon", "123", "1", STAMP)
    db.record_post("patreon", "123", "2", "2026-08-09T10:11:12+00:00")

    tab.current_creator_url = CREATOR_URL
    tab._load_creator_history()

    assert tab.creator_last_download_label.text() == translate(
        "last_downloaded_creator", iso_to_local_date("2026-08-09T10:11:12+00:00")
    )


def test_label_ignores_another_creators_history(qtbot, tmp_path):
    tab, other_dir = make_tab(qtbot, tmp_path)
    DownloadHistoryDB(other_dir).record_post("patreon", "999", "1", STAMP)

    tab.current_creator_url = CREATOR_URL
    tab._load_creator_history()

    assert tab.creator_last_download_label.text() == translate(
        "last_downloaded_creator", translate("never_downloaded")
    )


# ---------------------------------------------------------------------------
# Per-post row label
# ---------------------------------------------------------------------------


def test_row_label_appends_the_date_in_brackets(qtbot, tmp_path):
    tab, _ = make_tab(qtbot, tmp_path)
    tab._post_history_cache = {"1": "2026-10-16"}

    widget = add_post_row(tab, "Title (2024-01-01)", "1")

    assert widget.label.text() == "Title (2024-01-01) [2026-10-16]"
    # The undecorated key is preserved for the maps.
    assert widget.post_key == "Title (2024-01-01)"


def test_row_label_is_untouched_without_history(qtbot, tmp_path):
    tab, _ = make_tab(qtbot, tmp_path)

    widget = add_post_row(tab, "Title (2024-01-01)", "1")

    assert widget.label.text() == "Title (2024-01-01)"
    assert widget.post_key == "Title (2024-01-01)"


def test_refresh_restamps_visible_rows_and_label(qtbot, tmp_path):
    tab, other_dir = make_tab(qtbot, tmp_path)
    tab.current_creator_url = CREATOR_URL
    widget = add_post_row(tab, "Title (2024-01-01)", "1")
    assert widget.label.text() == "Title (2024-01-01)"

    DownloadHistoryDB(other_dir).record_post("patreon", "123", "1", STAMP)
    tab.refresh_download_history_ui()

    assert widget.label.text() == f"Title (2024-01-01) [{STAMP_DATE}]"
    assert tab.creator_last_download_label.text() == translate(
        "last_downloaded_creator", STAMP_DATE
    )


def test_checkbox_toggle_resolves_the_post_behind_a_dated_label(qtbot, tmp_path):
    tab, _ = make_tab(qtbot, tmp_path)
    tab._post_history_cache = {"1": "2026-10-16"}
    widget = add_post_row(tab, "Title (2024-01-01)", "1")
    assert widget.label.text() != widget.post_key

    # Mirrors the checkbox lambda: the row hands over its stable key.
    tab.toggle_checkbox_state(widget.post_key)

    assert tab.checked_urls.get("1") is True
    assert widget.check_box.isChecked() is True


def test_loading_post_history_is_scoped_to_the_viewed_creator(qtbot, tmp_path):
    tab, other_dir = make_tab(qtbot, tmp_path)
    db = DownloadHistoryDB(other_dir)
    db.record_post("patreon", "123", "1", STAMP)
    db.record_post("patreon", "999", "2", STAMP)

    tab.current_creator_url = CREATOR_URL
    tab._load_post_history()

    assert tab._post_history_cache == {"1": STAMP_DATE}


# ---------------------------------------------------------------------------
# Thread-side stamping
# ---------------------------------------------------------------------------


def make_settings():
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: None,
        get_creator_folder_strategy=lambda: "per_post",
        get_proxy_settings=lambda: None,
    )
    return cd.ThreadSettings(
        creator_posts_max_attempts=1,
        post_data_max_retries=1,
        file_download_max_retries=1,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def make_thread(tmp_path):
    return cd.CreatorDownloadThread(
        service="patreon",
        creator_id="123",
        download_folder=str(tmp_path / "download"),
        selected_posts=["1", "2"],
        files_to_download=["https://kemono.cr/files/a.png"],
        files_to_posts_map={"https://kemono.cr/files/a.png": "1"},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        auto_rename_enabled=False,
        settings=make_settings(),
        download_text=False,
    )


def test_fresh_download_stamps_the_post(tmp_path):
    thread = make_thread(tmp_path)

    thread._record_post_download("1")

    assert thread.history_db.get_post_times("patreon", "123")["1"]


def test_each_post_is_stamped_once_per_run(tmp_path, monkeypatch):
    thread = make_thread(tmp_path)
    calls = []
    monkeypatch.setattr(
        thread.history_db, "record_post", lambda *a, **k: calls.append(a)
    )

    thread._record_post_download("1")
    thread._record_post_download("1")
    thread._record_post_download("2")

    assert [call[2] for call in calls] == ["1", "2"]


def test_split_creator_url():
    assert cd.split_creator_url("https://kemono.cr/patreon/user/123") == (
        "patreon",
        "123",
    )
    assert cd.split_creator_url("https://kemono.cr/fanbox/user/abc/") == (
        "fanbox",
        "abc",
    )
    assert cd.split_creator_url("https://kemono.cr/patreon/user/123?o=50") == (
        "patreon",
        "123",
    )
    assert cd.split_creator_url(None) == ("unknown_service", "unknown_creator")


# ---------------------------------------------------------------------------
# Info icons and the dialog
# ---------------------------------------------------------------------------


def test_creator_info_buttons_share_the_small_icon_style(qtbot, tmp_path):
    tab, _ = make_tab(qtbot, tmp_path)

    buttons = [
        tab.skip_keywords_help_btn,
        tab.file_skip_keywords_help_btn,
        tab.date_filter_help_btn,
        tab.creator_box_info_btn,
        tab.creator_auto_rename_info_btn,
        tab.creator_skip_folder_info_btn,
    ]
    for button in buttons:
        assert button.text() == "", "info buttons carry an icon, not text"
        assert not button.icon().isNull()
        assert (button.minimumWidth(), button.maximumWidth()) == (26, 26)
        assert "border-radius: 5px" in button.styleSheet()
        assert button.toolTip()


def test_box_info_dialog_shows_only_the_row_format(qtbot, tmp_path, monkeypatch):
    tab, _ = make_tab(qtbot, tmp_path)
    captured = {}

    def fake_information(parent, title, text, *args, **kwargs):
        captured["title"] = title
        captured["text"] = text

    monkeypatch.setattr(cd.QMessageBox, "information", fake_information)
    tab.creator_box_info_btn.click()

    assert captured["title"] == translate("downloader_box_info_title")
    assert captured["title"] == "Downloader Box Help"
    assert captured["title"] == tab.creator_box_info_btn.toolTip()
    assert captured["text"] == translate("downloader_box_info_text")
    assert captured["text"].count("\n") == 1, "two lines"
    assert "Key: Post Title | (Publish Date) | [Last Downloaded Date]" in captured["text"]
    assert "and Double Click to view a posts thumbnail." in captured["text"]


def test_new_translation_keys_exist_in_every_language():
    original = language_manager.get_current_language()
    try:
        for language in language_manager.get_available_languages():
            language_manager.set_language(language)
            for key in (
                "last_downloaded_creator",
                "never_downloaded",
                "not_available",
                "downloader_box_info_title",
                "downloader_box_info_text",
            ):
                value = translate(key)
                assert value and value != key, f"{key} missing for {language}"
            assert "{" in translate("last_downloaded_creator")
    finally:
        language_manager.set_language(original)
