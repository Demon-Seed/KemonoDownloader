"""UI tests for the Creator tab Filters box and filetype discovery.

The filters used to be stacked inside the "Posts to Download" group, which
left the post list very little height once a type picker was added. They now
live in their own "Filters" box above it, and the Creator tab learns which
filetypes a creator actually has (and how many files of each type) so the
extension boxes can be limited to them.
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


class FakeSettingsTab(SimpleNamespace):
    """Settings tab stub; the filetype filter mode can be set per test."""

    def get_show_only_found_filetypes(self):
        return getattr(self, "found_filetypes_mode", "off")


def make_parent(tmp_path):
    class FakeTabs:
        def count(self):
            return 1

        def currentIndex(self):
            return 0

        def setTabEnabled(self, i, enabled):
            pass

    settings_tab = FakeSettingsTab(
        settings_applied=SimpleNamespace(connect=lambda cb: None),
        language_changed=SimpleNamespace(connect=lambda cb: None),
        get_creator_posts_max_attempts=lambda: 1,
        get_post_data_max_retries=lambda: 1,
        get_file_download_max_retries=lambda: 1,
        get_api_request_max_retries=lambda: 1,
        get_simultaneous_downloads=lambda: 1,
        found_filetypes_mode="off",
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


def _right_layout(tab):
    """The layout that stacks the Filters box above the Posts box."""
    return tab.post_list_group.parentWidget().layout()


def _visible_extensions(tab):
    return [
        ext for ext, box in tab.creator_ext_checks.items() if not box.isHidden()
    ]


# ---------------------------------------------------------------------------
# The box itself
# ---------------------------------------------------------------------------


def test_filters_group_sits_above_the_posts_group(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    layout = _right_layout(tab)

    filters_row = layout.indexOf(tab.filters_group)
    posts_row = layout.indexOf(tab.post_list_group)

    assert filters_row >= 0 and posts_row >= 0
    assert filters_row < posts_row


def test_filters_group_is_labelled_filters(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.filters_group.title() == "Filters"


def test_filter_rows_live_in_the_filters_box(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    for widget in (
        tab.skip_keywords_label,
        tab.skip_scope_label,
        tab.file_skip_keywords_label,
        tab.date_from_label,
        tab.file_count_label,
    ):
        assert tab.filters_group.isAncestorOf(widget)


def test_post_group_keeps_search_rows_and_the_list(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    for widget in (
        tab.search_scope_label,
        tab.creator_search_input,
        tab.creator_post_list,
    ):
        assert tab.post_list_group.isAncestorOf(widget)
        assert not tab.filters_group.isAncestorOf(widget)


# ---------------------------------------------------------------------------
# What the creator actually contains
# ---------------------------------------------------------------------------


def test_analyze_post_reports_every_extension():
    post = {
        "id": "1",
        "file": {"name": "cover.PNG", "path": "/data/ab/cd/hash.png"},
        "attachments": [
            {"name": "notes.pdf", "path": "/data/ee/ff/hash"},
            {"name": "art.psd"},
        ],
        "content": (
            "<p>hi</p>"
            "<img src='https://file.test/data/aa/bb/hash.jpg?f=pic.jpg'>"
        ),
        "tags": [],
    }

    analysis = cd.analyze_post(post)

    assert analysis["extensions"] == [".jpg", ".pdf", ".png", ".psd"]
    assert analysis["extension_counts"] == {
        ".png": 1,
        ".pdf": 1,
        ".psd": 1,
        ".jpg": 1,
    }


def test_analyze_post_counts_files_of_the_same_type():
    post = {
        "id": "2",
        "attachments": [
            {"name": "a.png"},
            {"name": "b.png"},
            {"name": "c.psd"},
        ],
    }

    assert cd.analyze_post(post)["extension_counts"] == {
        ".png": 2,
        ".psd": 1,
    }


def test_detection_tally_sums_file_counts():
    found = {}
    thread = cd.PostDetectionThread(
        "https://kemono.cr/patreon/user/1",
        {},
        SimpleNamespace(),
        found_extensions=found,
    )

    thread._record_found_extensions({"extension_counts": {".png": 3}})
    thread._record_found_extensions({"extension_counts": {".png": 2, ".psd": 1}})

    assert found == {".png": 5, ".psd": 1}


def test_detection_tally_falls_back_to_the_extension_list():
    found = {}
    thread = cd.PostDetectionThread(
        "https://kemono.cr/patreon/user/1",
        {},
        SimpleNamespace(),
        found_extensions=found,
    )

    thread._record_found_extensions({"extensions": [".png", ".psd"]})

    assert found == {".png": 1, ".psd": 1}


def test_detection_tally_is_optional():
    thread = cd.PostDetectionThread(
        "https://kemono.cr/patreon/user/1", {}, SimpleNamespace()
    )

    thread._record_found_extensions({"extensions": [".png"]})

    assert thread.found_extensions is None


# ---------------------------------------------------------------------------
# "Show only filetypes found in creator"
# ---------------------------------------------------------------------------


def test_mode_off_shows_every_box(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._found_type_counts = {".png": 12}

    tab._refresh_show_only_found_filetypes()

    assert len(_visible_extensions(tab)) == len(tab.creator_ext_checks)


def test_mode_on_hides_types_the_creator_lacks(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._found_type_counts = {".png": 412, ".psd": 12}
    tab._parent.settings_tab.found_filetypes_mode = "on"

    tab._refresh_show_only_found_filetypes()

    assert set(_visible_extensions(tab)) == {".png", ".psd"}


def test_mode_on_leaves_labels_without_counts(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._found_type_counts = {".png": 412}
    tab._parent.settings_tab.found_filetypes_mode = "on"

    tab._refresh_show_only_found_filetypes()

    assert tab.creator_ext_checks[".png"].text() == "PNG"


def test_mode_on_with_filecount_appends_the_count(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._found_type_counts = {".png": 412, ".psd": 12}
    tab._parent.settings_tab.found_filetypes_mode = "on_with_count"

    tab._refresh_show_only_found_filetypes()

    assert tab.creator_ext_checks[".png"].text() == "PNG (412)"
    assert tab.creator_ext_checks[".psd"].text() == "PSD (12)"
    assert set(_visible_extensions(tab)) == {".png", ".psd"}


def test_counts_disappear_when_the_mode_turns_off(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._found_type_counts = {".png": 412}
    tab._parent.settings_tab.found_filetypes_mode = "on_with_count"
    tab._refresh_show_only_found_filetypes()
    assert tab.creator_ext_checks[".png"].text() == "PNG (412)"

    tab._parent.settings_tab.found_filetypes_mode = "off"
    tab._refresh_show_only_found_filetypes()

    assert tab.creator_ext_checks[".png"].text() == "PNG"


def test_a_ticked_type_stays_visible(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "FilterThread", FakeFilterThread)
    tab = make_tab(qtbot, tmp_path)
    tab.creator_ext_checks[".zip"].setChecked(True)
    tab._found_type_counts = {".png": 2}
    tab._parent.settings_tab.found_filetypes_mode = "on"

    tab._refresh_show_only_found_filetypes()

    assert not tab.creator_ext_checks[".zip"].isHidden()
    assert not tab.creator_ext_checks[".png"].isHidden()
    assert tab.creator_ext_checks[".mp4"].isHidden()


def test_enabled_mode_shows_no_boxes_before_a_creator_is_loaded(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._parent.settings_tab.found_filetypes_mode = "on"

    tab._refresh_show_only_found_filetypes()

    assert _visible_extensions(tab) == []
    assert not tab.creator_ext_empty_label.isHidden()
    assert tab.creator_ext_empty_label.text() == "Supported Filetypes Not Present"


def test_filecount_mode_also_shows_no_boxes_without_a_creator(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._parent.settings_tab.found_filetypes_mode = "on_with_count"

    tab._refresh_show_only_found_filetypes()

    assert _visible_extensions(tab) == []
    assert not tab.creator_ext_empty_label.isHidden()


def test_disabled_mode_shows_every_box_without_a_creator(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    tab._refresh_show_only_found_filetypes()

    assert len(_visible_extensions(tab)) == len(tab.creator_ext_checks)
    assert tab.creator_ext_empty_label.isHidden()


def test_a_persisted_on_mode_starts_with_no_boxes(qtbot, tmp_path):
    parent = make_parent(tmp_path)
    parent.settings_tab.found_filetypes_mode = "on"
    tab = cd.CreatorDownloaderTab(parent)
    qtbot.addWidget(tab)

    assert _visible_extensions(tab) == []
    assert not tab.creator_ext_empty_label.isHidden()


def test_the_placeholder_goes_away_once_types_arrive(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._parent.settings_tab.found_filetypes_mode = "on"
    tab._refresh_show_only_found_filetypes()
    assert not tab.creator_ext_empty_label.isHidden()

    tab._found_type_counts = {".png": 3}
    tab._refresh_show_only_found_filetypes()

    assert tab.creator_ext_empty_label.isHidden()
    assert _visible_extensions(tab) == [".png"]


# ---------------------------------------------------------------------------
# Forgetting the previous creator
# ---------------------------------------------------------------------------


def test_reset_forgets_the_previous_creator_types(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._parent.settings_tab.found_filetypes_mode = "on"
    tab._found_type_counts = {".psd": 1}
    tab._refresh_show_only_found_filetypes()
    assert not tab.creator_ext_checks[".psd"].isHidden()
    assert tab.creator_ext_checks[".png"].isHidden()

    tab._reset_found_extensions()

    assert tab._found_type_counts == {}
    assert _visible_extensions(tab) == []


def test_removing_the_last_creator_forgets_its_types(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    url = "https://kemono.cr/patreon/user/1"
    tab.creator_queue = [(url, True)]
    tab._found_type_counts = {".psd": 1}
    monkeypatch.setattr(tab, "append_log_to_console", lambda *a, **k: None)
    monkeypatch.setattr(tab, "filter_items", lambda *a, **k: None)
    monkeypatch.setattr(
        cd.QMessageBox,
        "question",
        lambda *a, **k: cd.QMessageBox.StandardButton.Yes,
    )

    tab.create_remove_handler(url)()

    assert tab._found_type_counts == {}


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_detection_receives_the_shared_type_tally(qtbot, tmp_path, monkeypatch):
    FakeDetectionThread.instances = []
    monkeypatch.setattr(cd, "PostDetectionThread", FakeDetectionThread)
    tab = make_tab(qtbot, tmp_path)

    tab.check_creator_from_queue("https://kemono.cr/patreon/user/1")

    thread = FakeDetectionThread.instances[-1]
    assert thread.kwargs["found_extensions"] is tab._found_type_counts
