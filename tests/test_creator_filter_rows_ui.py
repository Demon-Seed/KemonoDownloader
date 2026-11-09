"""UI tests for the Creator tab's new filter rows and download option.

Covers the "Search by" row, the "File Count From" filter (with its Keep
Archives toggle) and the "Skip Images if Compressed" download option.
"""

from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


class FakeFilterThread:
    """Stands in for the real QThread so toggling never starts one."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.finished = SimpleNamespace(connect=lambda cb: None)
        FakeFilterThread.instances.append(self)

    def start(self):
        pass

    def isRunning(self):
        return False


class FakeDetectionThread:
    """Stands in for the detection thread so fetching never hits the API."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.finished = SimpleNamespace(connect=lambda cb: None)
        self.posts_batch = SimpleNamespace(connect=lambda cb: None)
        self.log = SimpleNamespace(connect=lambda cb: None)
        self.error = SimpleNamespace(connect=lambda cb: None)
        FakeDetectionThread.instances.append(self)

    def start(self):
        pass


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


def _patch_filter_thread(monkeypatch):
    FakeFilterThread.instances = []
    monkeypatch.setattr(cd, "FilterThread", FakeFilterThread)
    return FakeFilterThread.instances


def _patch_detection_thread(monkeypatch):
    FakeDetectionThread.instances = []
    monkeypatch.setattr(cd, "PostDetectionThread", FakeDetectionThread)
    return FakeDetectionThread.instances


def _row_index_holding(tab, widget, group=None):
    """Index of the row (a QHBoxLayout) inside a group box.

    Defaults to the post list group; pass ``group=tab.filters_group`` for rows
    that live in the Filters box above it.
    """
    layout = (group if group is not None else tab.post_list_group).layout()
    for i in range(layout.count()):
        row = layout.itemAt(i).layout()
        if row is not None and row.indexOf(widget) >= 0:
            return i
    return -1


def _widget_index(tab, widget):
    return tab.post_list_group.layout().indexOf(widget)


def _options_index_holding(tab, widget):
    """Index of the row (a QHBoxLayout) inside the Download Options group."""
    layout = tab.creator_options_group.layout()
    for i in range(layout.count()):
        row = layout.itemAt(i).layout()
        if row is not None and row.indexOf(widget) >= 0:
            return i
    return -1


# ---------------------------------------------------------------------------
# "Search by" row
# ---------------------------------------------------------------------------


def test_search_scope_row_defaults_to_title(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert set(tab.search_scope_checkboxes) == {
        "title",
        "filenames",
        "description",
        "tags",
    }
    assert tab.search_scope_checkboxes["title"].isChecked()
    assert not any(
        checkbox.isChecked()
        for scope, checkbox in tab.search_scope_checkboxes.items()
        if scope != "title"
    )
    assert tab.search_scope_label.text() == "Search by"


def test_search_scope_checkboxes_have_no_info_button(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert not hasattr(tab, "search_scope_help_btn")


def test_search_scope_row_sits_above_the_search_box(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    row = _row_index_holding(tab, tab.search_scope_label)
    assert row >= 0
    assert row < _widget_index(tab, tab.creator_search_input)


def test_selected_scopes_reflect_the_checkboxes(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    _patch_filter_thread(monkeypatch)

    assert tab._selected_search_scopes() == {"title"}
    tab.search_scope_checkboxes["filenames"].setChecked(True)
    tab.search_scope_checkboxes["tags"].setChecked(True)
    assert tab._selected_search_scopes() == {"title", "filenames", "tags"}

    tab.search_scope_checkboxes["title"].setChecked(False)
    assert tab._selected_search_scopes() == {"filenames", "tags"}

    tab.search_scope_checkboxes["filenames"].setChecked(False)
    tab.search_scope_checkboxes["tags"].setChecked(False)
    assert tab._selected_search_scopes() == {"title"}


def test_filter_items_passes_scopes_and_index(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    instances = _patch_filter_thread(monkeypatch)
    tab.post_search_index = {"1": {"filenames": "a", "description": "", "tags": ""}}
    tab.all_detected_posts = [("Alien Comic", ("1", None))]

    tab.search_scope_checkboxes["filenames"].setChecked(True)
    tab.creator_search_input.setText("bonus")
    tab.filter_items()

    thread = instances[-1]
    assert thread.args[2] == "bonus"
    assert thread.kwargs["search_scopes"] == {"title", "filenames"}
    assert thread.kwargs["post_search_index"] == tab.post_search_index


def test_incremental_filtering_uses_the_selected_scopes(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    _patch_filter_thread(monkeypatch)
    tab.post_search_index = {
        "1": {"filenames": "bonus.zip", "description": "", "tags": ""},
        "2": {"filenames": "other.zip", "description": "", "tags": ""},
    }
    tab.checked_urls = {"1": False, "2": False}

    tab.search_scope_checkboxes["filenames"].setChecked(True)
    tab.creator_search_input.setText("bonus")
    tab.filtered_posts = []
    tab.filter_items_incremental(
        [("Alien Comic", ("1", None)), ("Second", ("2", None))]
    )

    assert [row[1] for row in tab.filtered_posts] == ["1"]


# ---------------------------------------------------------------------------
# "File Count From" row
# ---------------------------------------------------------------------------


def test_file_count_row_sits_below_the_date_range_row(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    date_row = _row_index_holding(tab, tab.date_from_label, tab.filters_group)
    count_row = _row_index_holding(
        tab, tab.file_count_label, tab.filters_group
    )
    assert date_row >= 0 and count_row > date_row


def test_file_count_widgets_default_to_empty(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.file_count_label.text() == "File Count From"
    assert tab.file_count_from_edit.text() == ""
    assert tab.file_count_to_edit.text() == ""
    assert tab.file_count_keep_compressed_check.isChecked() is False
    assert tab.file_count_keep_compressed_check.text() == "Keep Archives"


def test_file_count_help_dialog_explains_the_filter(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    captured = {}

    def fake_information(parent, title, text, *args, **kwargs):
        captured["title"] = title
        captured["text"] = text

    monkeypatch.setattr(cd.QMessageBox, "information", fake_information)
    tab.file_count_help_btn.click()

    assert captured["title"] == tab.file_count_help_btn.toolTip()
    assert "Keep Archives" in captured["text"]
    assert "eye icon" in captured["text"]


# ---------------------------------------------------------------------------
# "Skip Images if Compressed" toggle
# ---------------------------------------------------------------------------


def test_skip_images_toggle_sits_above_the_file_extensions_box(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    layout = tab.creator_options_group.layout()

    row = _options_index_holding(tab, tab.creator_skip_images_check)
    assert row >= 0
    assert row < layout.indexOf(tab.creator_ext_group)


def test_skip_images_toggle_defaults_to_off(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.creator_skip_images_check.isChecked() is False
    assert tab.creator_skip_images_check.text() == "Skip Images if Compressed"


def test_skip_images_help_dialog_is_reachable(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    captured = {}

    def fake_information(parent, title, text, *args, **kwargs):
        captured["title"] = title
        captured["text"] = text

    monkeypatch.setattr(cd.QMessageBox, "information", fake_information)
    tab.creator_skip_images_info_btn.click()

    assert captured["title"] == tab.creator_skip_images_info_btn.toolTip()
    assert "ZIP" in captured["text"]


def test_new_info_buttons_share_the_small_icon_style(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    for button in (tab.file_count_help_btn, tab.creator_skip_images_info_btn):
        assert button.text() == "", "info buttons carry an icon, not text"
        assert not button.icon().isNull()
        assert (button.minimumWidth(), button.maximumWidth()) == (26, 26)
        assert "border-radius: 5px" in button.styleSheet()
        assert button.toolTip()


# ---------------------------------------------------------------------------
# Fetch wiring
# ---------------------------------------------------------------------------


def test_fetch_passes_file_count_bounds_and_swaps_them(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    instances = _patch_detection_thread(monkeypatch)
    tab.file_count_from_edit.setText("9")
    tab.file_count_to_edit.setText("4")
    tab.file_count_keep_compressed_check.setChecked(True)

    tab.check_creator_from_queue("https://kemono.cr/patreon/user/1")

    kwargs = instances[-1].kwargs
    assert kwargs["file_count_min"] == 4
    assert kwargs["file_count_max"] == 9
    assert kwargs["file_count_keep_compressed"] is True
    assert kwargs["post_search_index"] is tab.post_search_index


def test_fetch_rejects_junk_file_counts(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    instances = _patch_detection_thread(monkeypatch)
    messages = []
    monkeypatch.setattr(
        tab,
        "append_log_to_console",
        lambda message, level="INFO": messages.append((message, level)),
    )
    tab.file_count_from_edit.setText("lots")

    tab.check_creator_from_queue("https://kemono.cr/patreon/user/1")

    kwargs = instances[-1].kwargs
    assert kwargs["file_count_min"] is None
    assert kwargs["file_count_max"] is None
    assert any(level == "WARNING" for _, level in messages)


def test_new_creator_view_clears_the_search_index(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    _patch_detection_thread(monkeypatch)
    tab.post_search_index = {"old": {"filenames": "x", "description": "", "tags": ""}}

    tab.check_creator_from_queue("https://kemono.cr/patreon/user/2")

    assert tab.post_search_index == {}


# ---------------------------------------------------------------------------
# Deferred filtering (a toggle clicked while a pass is still running)
# ---------------------------------------------------------------------------


def test_deferred_filter_change_is_reapplied(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    instances = _patch_filter_thread(monkeypatch)
    monkeypatch.setattr(tab, "append_log_to_console", lambda *a, **k: None)

    class RunningThread(FakeFilterThread):
        def isRunning(self):
            return True

    tab.filter_thread = RunningThread([], {}, "")
    tab.filter_items()
    assert tab._filter_refresh_pending is True
    started = len(instances)

    # The in-flight pass finishes; the deferred change must be applied now.
    tab.filter_thread = None
    tab.cleanup_filter_thread()

    assert tab._filter_refresh_pending is False
    assert len(instances) > started
