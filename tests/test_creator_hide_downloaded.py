"""Tests for the Creator tab's selection header and Hide Downloaded filter."""

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from tests.factories import make_tab_parent

from kemonodownloader import creator_downloader as cd
from kemonodownloader.kd_language import translate

CREATOR_URL = "https://kemono.cr/patreon/user/123"


def make_tab(qtbot, tmp_path):
    tab = cd.CreatorDownloaderTab(make_tab_parent(tmp_path, window=True))
    qtbot.addWidget(tab)
    tab.current_creator_url = CREATOR_URL
    return tab


def add_row(tab, key, post_id):
    tab.post_url_map[key] = (post_id, "thumb")
    tab.add_list_item(key, "thumb", False)
    return tab.post_widget_cache[key][1]


def set_posts(tab, post_ids):
    """Make *post_ids* the loaded, listed and ticked posts of the view."""
    posts = [
        (f"Post {post_id} (2024-01-0{index + 1})", (post_id, "thumb"))
        for index, post_id in enumerate(post_ids)
    ]
    tab.all_detected_posts = posts
    tab.filtered_posts = [
        (title, post_id, thumb, True) for title, (post_id, thumb) in posts
    ]
    tab.checked_urls = {post_id: True for post_id in post_ids}
    for title, (post_id, _thumb) in posts:
        add_row(tab, title, post_id)


class FakeToggleThread:
    """Stands in for CheckboxToggleThread and records what it was handed."""

    last_posts = None
    last_state = None

    def __init__(self, visible_posts, checked_urls, state):
        self.visible_posts = list(visible_posts)
        self.checked_urls = checked_urls.copy()
        self.state = state
        self.finished = SimpleNamespace(connect=lambda *a, **k: None)
        self.log = SimpleNamespace(connect=lambda *a, **k: None)

    def isRunning(self):
        return False

    def start(self):
        FakeToggleThread.last_posts = self.visible_posts
        FakeToggleThread.last_state = self.state

    def deleteLater(self):
        pass


class FakeFilterThread:
    """Captures the arguments of a filter pass without running one."""

    calls = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        FakeFilterThread.calls.append(kwargs)
        self.finished = SimpleNamespace(connect=lambda *a, **k: None)
        self.log = SimpleNamespace(connect=lambda *a, **k: None)

    def isRunning(self):
        return False

    def start(self):
        pass

    def deleteLater(self):
        pass


def capture_toggle(monkeypatch):
    monkeypatch.setattr(cd, "CheckboxToggleThread", FakeToggleThread)
    FakeToggleThread.last_posts = None
    FakeToggleThread.last_state = None
    return FakeToggleThread


def capture_filter(monkeypatch):
    monkeypatch.setattr(cd, "FilterThread", FakeFilterThread)
    FakeFilterThread.calls = []
    return FakeFilterThread


# ---------------------------------------------------------------------------
# Hide Downloaded
# ---------------------------------------------------------------------------


def test_filter_thread_drops_hidden_posts_before_other_rules():
    posts = [("A", ("1", None)), ("B", ("2", None))]
    out = {}
    thread = cd.FilterThread(
        posts, {"1": True, "2": False}, "", hidden_post_ids={"1"}
    )
    thread.finished = SimpleNamespace(
        emit=lambda data: out.setdefault("finished", data)
    )

    thread.run()

    assert [post_id for _t, post_id, _u, _c in out["finished"]] == ["2"]
    assert thread.download_hidden_count == 1


def test_hidden_posts_do_not_count_as_keyword_skips():
    posts = [("Cat video", ("1", None))]
    out = {}
    thread = cd.FilterThread(
        posts,
        {},
        "",
        post_filters=cd.PostFilters(skip_keywords=("cat",)),
        hidden_post_ids={"1"},
    )
    thread.finished = SimpleNamespace(
        emit=lambda data: out.setdefault("finished", data)
    )

    thread.run()

    assert out["finished"] == []
    assert thread.keyword_skipped_count == 0, "hidden is not skipped"
    assert thread.download_hidden_count == 1


def test_filter_items_passes_the_hidden_ids_while_ticked(qtbot, tmp_path, monkeypatch):
    passes = capture_filter(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    tab.all_detected_posts = [("A", ("1", "thumb"))]
    tab._post_history_cache = {"1": "2026-01-02"}

    tab.creator_hide_downloaded_check.setChecked(True)
    assert set(passes.calls[-1]["hidden_post_ids"]) == {"1"}

    tab.creator_hide_downloaded_check.setChecked(False)
    assert passes.calls[-1]["hidden_post_ids"] == ()


def test_toggling_hide_downloaded_runs_no_pass_without_posts(qtbot, tmp_path, monkeypatch):
    passes = capture_filter(monkeypatch)
    tab = make_tab(qtbot, tmp_path)

    tab.creator_hide_downloaded_check.setChecked(True)

    assert passes.calls == []


def test_hidden_posts_stay_out_of_the_download_set(qtbot, tmp_path, monkeypatch):
    capture_filter(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    # A stale list still holding the post must not make it downloadable.
    tab.filtered_posts = [("A", "1", None, True), ("B", "2", None, True)]
    tab.checked_urls = {"1": True, "2": True}
    tab._post_history_cache = {"1": "2026-01-02"}
    tab.creator_hide_downloaded_check.setChecked(True)

    tab.update_checked_posts()

    assert tab.posts_to_download == ["2"]


def test_check_all_all_skips_hidden_downloads(qtbot, tmp_path, monkeypatch):
    thread = capture_toggle(monkeypatch)
    capture_filter(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    tab._post_history_cache = {"2": "2026-01-02"}
    tab.all_detected_posts = [
        ("A (2024-01-01)", ("1", "thumb")),
        ("B (2024-01-02)", ("2", "thumb")),
    ]
    tab.creator_hide_downloaded_check.setChecked(True)

    tab.toggle_check_all_all(Qt.CheckState.Checked.value)

    assert [post_id for _title, (post_id, _thumb) in thread.last_posts] == ["1"]


def test_batch_arrival_does_not_tick_a_hidden_download(qtbot, tmp_path, monkeypatch):
    capture_filter(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    tab.filter_items_incremental = lambda batch: None
    tab.all_detected_posts = []
    tab._fetch_batches_started = True
    tab._requested_post_ids = {"1", "2"}
    tab._post_history_cache = {"1": "2026-01-02"}
    tab.creator_hide_downloaded_check.setChecked(True)

    tab.on_posts_batch_received([("A", ("1", None)), ("B", ("2", None))])

    assert tab.checked_urls["1"] is False
    assert tab.checked_urls["2"] is True


def test_refresh_history_hides_new_downloads_only_while_ticked(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    passes = []
    tab.filter_items = lambda: passes.append(True)

    tab.refresh_download_history_ui()
    assert passes == []

    tab.creator_hide_downloaded_check.setChecked(True)  # no posts, so no pass
    tab.refresh_download_history_ui()
    assert passes == [True]


def test_incremental_batch_skips_hidden_downloads(qtbot, tmp_path, monkeypatch):
    capture_filter(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    tab._post_history_cache = {"1": "2026-01-02"}
    tab.creator_hide_downloaded_check.setChecked(True)

    tab.filter_items_incremental([("A", ("1", "thumb")), ("B", ("2", "thumb"))])

    assert [post_id for _t, post_id, _u, _c in tab.filtered_posts] == ["2"]
    assert tab.creator_post_list.count() == 1


def test_empty_list_names_the_download_filter(qtbot, tmp_path, monkeypatch):
    capture_filter(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    tab._post_history_cache = {"1": "2026-01-02"}
    tab.all_detected_posts = [("A (2024-01-01)", ("1", "thumb"))]
    tab.filtered_posts = []
    tab.creator_hide_downloaded_check.setChecked(True)

    tab._update_post_list_empty_state()

    assert tab.creator_post_empty_label.text() == translate(
        "all_posts_hidden_downloaded"
    )
    assert tab.creator_post_empty_label.isHidden() is False


def test_hide_downloaded_round_trips_through_a_config_profile(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.creator_hide_downloaded_check.setChecked(True)

    assert tab._config_snapshot()["filters"]["hide_downloaded"] is True

    tab.creator_hide_downloaded_check.setChecked(False)
    tab._apply_config({"filters": {"hide_downloaded": True}})

    assert tab.creator_hide_downloaded_check.isChecked() is True


# ---------------------------------------------------------------------------
# Tri-state masters + Deselect menu
# ---------------------------------------------------------------------------


def test_master_boxes_show_none_part_and_all(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    set_posts(tab, ["1", "2"])

    tab.update_check_all_state()
    assert tab.creator_check_all.checkState() == Qt.CheckState.Checked
    assert tab.creator_check_all_all.checkState() == Qt.CheckState.Checked

    tab.checked_urls["2"] = False
    tab.update_check_all_state()
    assert tab.creator_check_all.checkState() == Qt.CheckState.PartiallyChecked
    assert tab.creator_check_all_all.checkState() == Qt.CheckState.PartiallyChecked

    tab.checked_urls["1"] = False
    tab.update_check_all_state()
    assert tab.creator_check_all.checkState() == Qt.CheckState.Unchecked
    assert tab.creator_check_all_all.checkState() == Qt.CheckState.Unchecked


def test_clicking_a_partial_master_ticks_the_rest(qtbot, tmp_path, monkeypatch):
    thread = capture_toggle(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    set_posts(tab, ["1", "2"])
    tab.checked_urls["2"] = False
    tab.update_check_all_state()
    assert tab.creator_check_all.checkState() == Qt.CheckState.PartiallyChecked

    tab._on_check_page_clicked()

    assert thread.last_state == Qt.CheckState.Checked.value
    assert sorted(pid for _t, (pid, _u) in thread.last_posts) == ["1", "2"]


def test_clicking_a_checked_master_clears_it(qtbot, tmp_path, monkeypatch):
    thread = capture_toggle(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    set_posts(tab, ["1", "2"])
    tab.update_check_all_state()

    tab._on_check_page_clicked()

    assert thread.last_state == Qt.CheckState.Unchecked.value


def test_masters_stay_unchecked_when_every_post_is_hidden(
    qtbot, tmp_path, monkeypatch
):
    thread = capture_toggle(monkeypatch)
    capture_filter(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    tab._post_history_cache = {"1": "2026-01-02"}
    tab.all_detected_posts = [("A (2024-01-01)", ("1", "thumb"))]
    tab.creator_hide_downloaded_check.setChecked(True)

    tab.update_check_all_state()
    assert tab.creator_check_all.checkState() == Qt.CheckState.Unchecked
    assert tab.creator_check_all_all.checkState() == Qt.CheckState.Unchecked

    tab._on_check_page_clicked()
    assert thread.last_posts is None, "nothing may be handed to the toggle thread"


def test_deselect_page_clears_only_the_listed_rows(qtbot, tmp_path, monkeypatch):
    thread = capture_toggle(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    add_row(tab, "A (2024-01-01)", "1")
    tab.checked_urls = {"1": True, "2": True}

    tab.deselect_page()

    assert thread.last_state == Qt.CheckState.Unchecked.value
    assert [pid for _t, (pid, _u) in thread.last_posts] == ["1"]


def test_deselect_all_covers_posts_on_other_pages(qtbot, tmp_path, monkeypatch):
    thread = capture_toggle(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    tab.all_detected_posts = [
        ("A (2024-01-01)", ("1", "thumb")),
        ("B (2024-01-02)", ("2", "thumb")),
        ("C (2024-01-03)", ("3", "thumb")),
    ]
    add_row(tab, "A (2024-01-01)", "1")
    tab.checked_urls = {"1": True, "2": True, "3": True}

    tab.deselect_all_posts()

    assert thread.last_state == Qt.CheckState.Unchecked.value
    assert sorted(pid for _t, (pid, _u) in thread.last_posts) == ["1", "2", "3"]


def test_deselect_with_nothing_ticked_starts_no_pass(qtbot, tmp_path, monkeypatch):
    thread = capture_toggle(monkeypatch)
    tab = make_tab(qtbot, tmp_path)
    add_row(tab, "A (2024-01-01)", "1")
    tab.checked_urls = {"1": False}

    tab.deselect_page()
    tab.deselect_all_posts()

    assert thread.last_posts is None


def test_selection_tools_have_translations(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    for key in (
        "check_all",
        "check_all_all",
        "check_page_tooltip",
        "check_all_tooltip",
        "deselect",
        "deselect_page",
        "deselect_all",
        "deselect_tooltip",
        "hide_downloaded",
        "hide_downloaded_tooltip",
        "hide_downloaded_excluded",
        "hide_downloaded_hidden",
        "no_selectable_posts_to_toggle",
    ):
        assert translate(key) and translate(key) != key

    assert tab.creator_deselect_btn.text() == translate("deselect")
    assert tab.creator_hide_downloaded_check.text() == translate("hide_downloaded")
