"""Creator Queue input row: commit keys, auto-load modes and double-click."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from kemonodownloader import creator_downloader as cd

# The suite's autouse fixture replaces cd.CreatorNameLookupThread with an
# offline no-op; keep the real class for the worker's own tests.
_REAL_CREATOR_NAME_LOOKUP = cd.CreatorNameLookupThread


def make_parent(tmp_path, behavior="default"):
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
        get_queue_input_behavior=lambda: behavior,
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


@pytest.fixture
def make_tab(qapp, tmp_path):
    created = []

    def factory(behavior="default"):
        tab = cd.CreatorDownloaderTab(make_parent(tmp_path, behavior))
        created.append(tab)
        return tab

    yield factory
    for tab in created:
        tab.deleteLater()


def _record_loads(tab):
    """Replace the fetch entry point so tests can see what gets opened."""
    loaded = []
    tab.check_creator_from_queue = lambda url: loaded.append(url)
    return loaded


def test_enter_commits_and_clears_but_does_not_load(make_tab):
    tab = make_tab("default")
    loaded = _record_loads(tab)

    tab.creator_queue_input.setText("https://kemono.cr/fanbox/user/1")
    tab.creator_queue_input.returnPressed.emit()

    assert [url for url, _ in tab.creator_queue] == ["https://kemono.cr/fanbox/user/1"]
    assert tab.creator_queue_input.text() == ""
    assert loaded == []


def test_space_commits_instead_of_typing(make_tab, qtbot):
    tab = make_tab("default")
    loaded = _record_loads(tab)

    tab.creator_queue_input.setText("https://kemono.cr/fanbox/user/2")
    qtbot.keyClick(tab.creator_queue_input, Qt.Key.Key_Space)

    assert len(tab.creator_queue) == 1
    assert tab.creator_queue_input.text() == ""
    assert loaded == []


def test_eye_adds_and_loads(make_tab):
    tab = make_tab("default")
    loaded = _record_loads(tab)

    tab.creator_queue_input.setText("https://kemono.cr/fanbox/user/3")
    tab.add_creator_and_load()

    assert len(tab.creator_queue) == 1
    assert loaded == ["https://kemono.cr/fanbox/user/3"]


def test_eye_loads_a_creator_that_was_already_queued(make_tab):
    tab = make_tab("default")
    loaded = _record_loads(tab)
    url = "https://kemono.cr/fanbox/user/4"

    tab.creator_queue_input.setText(url)
    tab.add_creator_to_queue()
    loaded.clear()
    tab.creator_queue_input.setText(url)
    tab.add_creator_and_load()

    assert loaded == [url]


def test_default_mode_never_loads(make_tab):
    tab = make_tab("default")
    loaded = _record_loads(tab)

    for user_id in ("5", "6"):
        tab.creator_queue_input.setText(f"https://kemono.cr/fanbox/user/{user_id}")
        tab.add_creator_to_queue()

    assert len(tab.creator_queue) == 2
    assert loaded == []


def test_load_first_opens_only_the_first_creator(make_tab):
    tab = make_tab("load_first")
    loaded = _record_loads(tab)

    tab.creator_queue_input.setText("https://kemono.cr/fanbox/user/7")
    tab.add_creator_to_queue()
    # The fetch normally sets this; stand in for a creator already open.
    tab.current_creator_url = "https://kemono.cr/fanbox/user/7"
    tab.creator_queue_input.setText("https://kemono.cr/fanbox/user/8")
    tab.add_creator_to_queue()

    assert loaded == ["https://kemono.cr/fanbox/user/7"]
    assert len(tab.creator_queue) == 2


def test_load_every_opens_each_creator(make_tab):
    tab = make_tab("load_every")
    loaded = _record_loads(tab)

    for user_id in ("9", "10"):
        tab.creator_queue_input.setText(f"https://kemono.cr/fanbox/user/{user_id}")
        tab.add_creator_to_queue()

    assert loaded == [
        "https://kemono.cr/fanbox/user/9",
        "https://kemono.cr/fanbox/user/10",
    ]


def test_eye_in_load_every_mode_loads_only_once(make_tab):
    """The eye opens the creator itself; the mode must not fetch a second time."""
    tab = make_tab("load_every")
    loaded = _record_loads(tab)

    tab.creator_queue_input.setText("https://kemono.cr/fanbox/user/13")
    tab.add_creator_and_load()

    assert loaded == ["https://kemono.cr/fanbox/user/13"]


def test_focus_returns_to_the_input_after_an_auto_load(make_tab):
    tab = make_tab("load_every")

    def fake_open(url):
        tab.set_fetching_ui_state(True)
        return True

    tab.check_creator_from_queue = fake_open

    tab.creator_queue_input.setText("https://kemono.cr/fanbox/user/14")
    tab.add_creator_to_queue()
    assert tab._restore_queue_input_focus is True
    assert tab.creator_queue_input.isEnabled() is False

    tab.set_fetching_ui_state(False)
    assert tab._restore_queue_input_focus is False
    assert tab.creator_queue_input.isEnabled() is True


def test_double_click_on_a_queue_row_loads_the_creator(make_tab):
    tab = make_tab("default")
    url = "https://kemono.cr/fanbox/user/11"
    tab.creator_queue = [(url, False)]
    tab.update_creator_queue_list()

    loaded = _record_loads(tab)
    row = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0))
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(5, 5),
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    row.mouseDoubleClickEvent(event)

    assert loaded == [url]


def test_queue_labels_let_double_clicks_reach_the_row(make_tab):
    tab = make_tab("default")
    tab.creator_queue = [("https://kemono.cr/fanbox/user/12", False)]
    tab.update_creator_queue_list()

    row = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0))
    assert row.label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_queue_input_is_locked_while_fetching_and_downloading(make_tab):
    tab = make_tab("default")

    tab.set_fetching_ui_state(True)
    assert tab.creator_queue_input.isEnabled() is False
    tab.set_fetching_ui_state(False)
    assert tab.creator_queue_input.isEnabled() is True

    tab.set_downloading_ui_state(True)
    assert tab.creator_queue_input.isEnabled() is False
    tab.set_downloading_ui_state(False)
    assert tab.creator_queue_input.isEnabled() is True


def test_creator_name_is_bolded_after_the_link(make_tab):
    tab = make_tab("default")
    url = "https://kemono.cr/fanbox/user/20"
    tab.creator_queue = [(url, False)]
    tab._creator_names[url] = "Cool Artist"

    tab.update_creator_queue_list()

    row = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0))
    assert row.label.textFormat() == Qt.TextFormat.RichText
    assert row.label.text() == f"{url} <b>[Cool Artist]</b>"


def test_queue_row_stays_plain_without_a_creator_name(make_tab):
    tab = make_tab("default")
    url = "https://kemono.cr/fanbox/user/21"
    tab.creator_queue = [(url, False)]

    tab.update_creator_queue_list()

    row = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0))
    assert row.label.textFormat() == Qt.TextFormat.PlainText
    assert row.label.text() == url


def test_creator_name_found_refreshes_the_queue_row(make_tab):
    tab = make_tab("default")
    url = "https://kemono.cr/fanbox/user/22"
    tab.creator_queue = [(url, False)]
    tab.update_creator_queue_list()

    tab.on_creator_name_found(url + "/", "  Artist Name  ")

    assert tab._creator_names[url] == "Artist Name"
    row = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0))
    assert "Artist Name" in row.label.text()


def test_copy_link_puts_the_url_on_the_clipboard(make_tab):
    from PyQt6.QtWidgets import QApplication

    tab = make_tab("default")
    url = "https://kemono.cr/fanbox/user/23"

    tab._copy_queue_link(url)

    assert QApplication.clipboard().text() == url
    QApplication.clipboard().clear()


def test_context_menu_offers_copy_link_for_a_row(make_tab, monkeypatch, qapp):
    from PyQt6.QtWidgets import QMenu

    tab = make_tab("default")
    url = "https://kemono.cr/fanbox/user/24"
    tab.creator_queue = [(url, False)]
    tab.update_creator_queue_list()

    captured = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: captured.append(self))
    item = tab.creator_queue_list.item(0)
    monkeypatch.setattr(tab.creator_queue_list, "itemAt", lambda pos: item)

    tab._show_queue_context_menu(tab.creator_queue_list.rect().center())

    menu = captured[0]
    texts = [action.text() for action in menu.actions()]
    assert "Copy Link" in texts
    assert "Import from TXT File" in texts
    assert menu.styleSheet() == cd.MENU_STYLE

    # The menu is parented to the list; without deleteLater() every right-click
    # would leave one behind.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert menu not in tab.creator_queue_list.findChildren(QMenu)


def test_context_menu_without_a_row_only_imports(make_tab, monkeypatch):
    from PyQt6.QtWidgets import QMenu

    tab = make_tab("default")

    captured = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: captured.append(self))
    monkeypatch.setattr(tab.creator_queue_list, "itemAt", lambda pos: None)

    tab._show_queue_context_menu(tab.creator_queue_list.rect().center())

    menu = captured[0]
    texts = [action.text() for action in menu.actions() if action.text()]
    assert texts == ["Import from TXT File"]
    assert menu.styleSheet() == cd.MENU_STYLE


def test_queue_rows_keep_the_highlight_visible_behind_the_label(make_tab):
    tab = make_tab("default")
    url = "https://kemono.cr/fanbox/user/25"
    tab.creator_queue = [(url, False)]

    tab.update_creator_queue_list()

    row = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0))
    # The window stylesheet paints descendants; the label must opt out or it
    # draws a dark band over the row's low-opacity selection highlight.
    assert "background: transparent" in row.label.styleSheet()


def test_queue_input_context_menu_uses_the_shared_style(make_tab, monkeypatch, qapp):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QMenu

    tab = make_tab("default")
    menu = QMenu(tab)
    menu.addAction("Copy")
    monkeypatch.setattr(
        tab.creator_queue_input, "createStandardContextMenu", lambda: menu
    )
    captured = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: captured.append(self))
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, QPoint(1, 1), QPoint(10, 10)
    )

    tab.creator_queue_input.contextMenuEvent(event)

    assert captured == [menu]
    assert menu.styleSheet() == cd.MENU_STYLE

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert menu not in tab.creator_queue_input.findChildren(QMenu)


def test_name_lookup_worker_reports_the_profile_name(monkeypatch):
    url = "https://kemono.cr/fanbox/user/77"
    requested = []
    captured = []

    def fake_get_session(_settings_tab=None):
        def get(request_url, *_a, **_k):
            requested.append(request_url)
            return SimpleNamespace(
                status_code=200, json=lambda: {"name": "  HanaDraws  "}
            )

        return SimpleNamespace(get=get)

    monkeypatch.setattr(cd, "get_session", fake_get_session)
    thread = _REAL_CREATOR_NAME_LOOKUP(url, None)
    thread.found = SimpleNamespace(emit=lambda u, n: captured.append((u, n)))

    thread.run()

    assert requested == ["https://kemono.cr/api/v1/fanbox/user/77/profile"]
    assert captured == [(url, "HanaDraws")]


def test_name_lookup_worker_ignores_a_failed_profile(monkeypatch):
    captured = []

    def fake_get_session(_settings_tab=None):
        def get(_request_url, *_a, **_k):
            return SimpleNamespace(status_code=404, json=lambda: {"name": "x"})

        return SimpleNamespace(get=get)

    monkeypatch.setattr(cd, "get_session", fake_get_session)
    thread = _REAL_CREATOR_NAME_LOOKUP("https://kemono.cr/fanbox/user/78", None)
    thread.found = SimpleNamespace(emit=lambda u, n: captured.append((u, n)))

    thread.run()

    assert captured == []


def test_adding_a_creator_requests_its_name(make_tab, monkeypatch):
    tab = make_tab("default")
    started = []
    monkeypatch.setattr(tab, "_start_name_lookups", lambda: started.append(True))
    url = "https://kemono.cr/fanbox/user/79"

    tab.creator_queue_input.setText(url)
    tab.add_creator_to_queue(auto_load=False)

    assert tab._name_lookup_pending == [url]
    assert started == [True]

    # Asking again (or for a name already known) must not queue a second hit.
    tab._request_creator_name(url)
    assert tab._name_lookup_pending == [url]

    tab._name_lookup_pending.clear()
    tab._name_lookup_wanted.clear()
    tab._creator_names[url] = "HanaDraws"
    tab._request_creator_name(url)
    assert tab._name_lookup_pending == []


def test_name_lookups_respect_the_concurrency_cap(make_tab, monkeypatch):
    tab = make_tab("default")
    started = []

    class FakeLookup:
        def __init__(self, creator_url, _settings):
            self.creator_url = creator_url
            self.found = SimpleNamespace(connect=lambda cb: None)
            self.finished = SimpleNamespace(connect=lambda cb: None)

        def start(self):
            started.append(self.creator_url)

    monkeypatch.setattr(cd, "CreatorNameLookupThread", FakeLookup)
    urls = [f"https://kemono.cr/fanbox/user/{i}" for i in range(80, 86)]
    tab._name_lookup_pending = list(urls)
    tab._name_lookup_wanted = set(urls)

    tab._start_name_lookups()

    cap = cd.CREATOR_NAME_LOOKUP_CONCURRENCY
    assert started == urls[:cap]
    assert tab._name_lookup_pending == urls[cap:]
    assert len(tab._name_lookup_threads) == cap


def test_filter_finish_keeps_the_post_list_scroll_position(make_tab, monkeypatch):
    tab = make_tab("default")
    calls = []
    tab.display_current_page = (
        lambda preserve_scroll=False, scroll_value=None: calls.append(
            (preserve_scroll, scroll_value)
        )
    )

    tab.on_filter_finished([])

    assert calls == [(True, None)]


def test_filter_finish_applies_a_search_s_scroll_target(make_tab, monkeypatch):
    tab = make_tab("default")
    calls = []
    tab.display_current_page = (
        lambda preserve_scroll=False, scroll_value=None: calls.append(
            (preserve_scroll, scroll_value)
        )
    )
    tab._pending_filter_scroll = 0

    tab.on_filter_finished([])

    # A search start/clear knows exactly where the viewport belongs, and the
    # override is used once, not left behind for the next filter pass.
    assert calls == [(True, 0)]
    assert tab._pending_filter_scroll is None


class _Bar:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


def test_a_new_search_starts_on_page_one_and_clearing_restores_the_view(
    make_tab, monkeypatch
):
    tab = make_tab("default")
    monkeypatch.setattr(tab, "filter_items", lambda: None)
    monkeypatch.setattr(tab.creator_post_list, "verticalScrollBar", lambda: _Bar(7))
    tab.current_page = 4

    tab.creator_search_input.setText("cat")

    assert tab.current_page == 1
    assert tab._search_return_position == (4, 7)
    assert tab._pending_filter_scroll == 0

    tab.creator_search_input.clear()

    assert tab.current_page == 4
    assert tab._search_return_position is None
    assert tab._pending_filter_scroll == 7


def test_changing_a_search_does_not_re_remember_the_view(make_tab, monkeypatch):
    tab = make_tab("default")
    monkeypatch.setattr(tab, "filter_items", lambda: None)
    monkeypatch.setattr(tab.creator_post_list, "verticalScrollBar", lambda: _Bar(3))
    tab.current_page = 2

    tab.creator_search_input.setText("c")
    tab.creator_search_input.setText("ca")

    # Still the position from before the search, not page 1 / 0 from mid-search.
    assert tab._search_return_position == (2, 3)


def test_loading_another_creator_forgets_the_search_position(make_tab, monkeypatch):
    tab = make_tab("default")
    tab._search_return_position = (3, 5)
    tab._pending_filter_scroll = 5

    class FakeDetection:
        def __init__(self, *a, **k):
            self.finished = SimpleNamespace(connect=lambda cb: None)
            self.posts_batch = SimpleNamespace(connect=lambda cb: None)
            self.creator_name_found = SimpleNamespace(connect=lambda cb: None)
            self.log = SimpleNamespace(connect=lambda cb: None)
            self.error = SimpleNamespace(connect=lambda cb: None)

        def start(self):
            pass

    monkeypatch.setattr(cd, "PostDetectionThread", FakeDetection)
    monkeypatch.setattr(tab, "set_fetching_ui_state", lambda *a, **k: None)
    monkeypatch.setattr(tab, "_create_thread_settings", lambda: object())

    started = tab.check_creator_from_queue("https://kemono.cr/fanbox/user/9")

    assert started is True
    assert tab._search_return_position is None
    assert tab._pending_filter_scroll is None


def test_a_name_updates_only_its_own_row(make_tab):
    tab = make_tab("default")
    url = "https://kemono.cr/fanbox/user/30"
    other = "https://kemono.cr/fanbox/user/31"
    tab.creator_queue = [(url, False), (other, False)]
    tab.update_creator_queue_list()

    first = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0))
    second = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(1))

    tab.on_creator_name_found(url, "Hana")

    # The row is refreshed in place: a rebuild would replace both widgets and
    # reset the queue's selection.
    assert tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0)) is first
    assert tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(1)) is second
    assert "[Hana]" in first.label.text()
    assert "[Hana]" not in second.label.text()


def test_stop_name_lookups_stops_threads_and_clears_the_queue(make_tab):
    tab = make_tab("default")
    stopped = []

    class FakeThread:
        def stop(self):
            stopped.append(True)

    tab._name_lookup_threads = {"u1": FakeThread(), "u2": FakeThread()}
    tab._name_lookup_pending = ["u3"]
    tab._name_lookup_wanted = {"u1", "u2", "u3"}

    tab.stop_name_lookups()

    assert stopped == [True, True]
    assert tab._name_lookup_pending == []
    assert tab._name_lookup_wanted == set()


def test_check_creator_from_queue_reports_a_running_fetch(make_tab):
    tab = make_tab("default")
    tab.post_detection_thread = SimpleNamespace(isRunning=lambda: True)

    assert tab.check_creator_from_queue("https://kemono.cr/fanbox/user/33") is False


def test_load_mode_focus_flag_follows_the_fetch_result(make_tab, monkeypatch):
    tab = make_tab("load_every")
    tab.creator_queue = [("https://kemono.cr/fanbox/user/34", False)]

    monkeypatch.setattr(tab, "check_creator_from_queue", lambda url: False)
    tab._auto_load_queued_link("https://kemono.cr/fanbox/user/34")
    assert tab._restore_queue_input_focus is False

    monkeypatch.setattr(tab, "check_creator_from_queue", lambda url: True)
    tab._auto_load_queued_link("https://kemono.cr/fanbox/user/34")
    assert tab._restore_queue_input_focus is True


def _capture_detection(monkeypatch, tab):
    captured = {}

    class FakeDetection:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.finished = SimpleNamespace(connect=lambda cb: None)
            self.posts_batch = SimpleNamespace(connect=lambda cb: None)
            self.creator_name_found = SimpleNamespace(connect=lambda cb: None)
            self.log = SimpleNamespace(connect=lambda cb: None)
            self.error = SimpleNamespace(connect=lambda cb: None)

        def start(self):
            pass

    monkeypatch.setattr(cd, "PostDetectionThread", FakeDetection)
    monkeypatch.setattr(tab, "set_fetching_ui_state", lambda *a, **k: None)
    monkeypatch.setattr(tab, "_create_thread_settings", lambda: object())
    return captured


def test_creator_and_post_links_get_separate_rows(make_tab):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/40"
    post_one = f"{creator}/post/1"
    post_two = f"{creator}/post/2"

    for link in (creator, post_one, post_two):
        tab.creator_queue_input.setText(link)
        tab.add_creator_to_queue()

    assert [link for link, _checked in tab.creator_queue] == [creator, post_one]
    assert tab._batch_post_ids[creator] == {"1", "2"}
    text, _rich = tab._queue_row_text(post_one)
    assert "+1 more" in text
    tooltip = tab._queue_row_tooltip(post_one)
    assert post_one in tooltip and post_two in tooltip

    creator_row = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0))
    post_row = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(1))
    assert creator_row.full_creator_button is None
    assert post_row.full_creator_button is not None
    assert creator_row.toolTip() == creator
    assert post_one in post_row.toolTip()
    assert post_two in post_row.toolTip()


def test_duplicate_post_link_is_not_added_twice(make_tab):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/41"
    post_link = f"{creator}/post/9"

    tab.creator_queue_input.setText(post_link)
    assert tab.add_creator_to_queue() == "added"
    tab.creator_queue_input.setText(post_link)
    assert tab.add_creator_to_queue() == "duplicate"

    assert len(tab.creator_queue) == 1
    assert tab._batch_post_ids[creator] == {"9"}


def test_post_row_eye_fetches_only_its_linked_posts(make_tab, monkeypatch):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/42"
    post_link = f"{creator}/post/1"
    tab.creator_queue_input.setText(post_link)
    tab.add_creator_to_queue()
    tab.creator_queue_input.setText(f"{creator}/post/2")
    tab.add_creator_to_queue()

    captured = _capture_detection(monkeypatch, tab)
    assert tab.check_creator_from_queue(post_link) is True

    assert captured["kwargs"]["post_ids"] == ["1", "2"]
    assert tab._view_kind == "posts"
    assert tab._fetch_post_ids == {"1", "2"}
    assert tab._requested_post_ids == {"1", "2"}


def test_creator_row_eye_fetches_the_full_creator(make_tab, monkeypatch):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/43"
    tab.creator_queue_input.setText(creator)
    tab.add_creator_to_queue()

    captured = _capture_detection(monkeypatch, tab)
    assert tab.check_creator_from_queue(creator) is True

    assert captured["kwargs"]["post_ids"] is None
    assert tab._view_kind == "creator"
    assert tab._fetch_post_ids == set()
    assert tab._requested_post_ids == set()


def test_full_creator_button_folds_the_post_row_into_a_creator_session(
    make_tab, monkeypatch
):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/44"
    post_link = f"{creator}/post/1"
    tab.creator_queue_input.setText(post_link)
    tab.add_creator_to_queue()
    tab.creator_queue_input.setText(f"{creator}/post/2")
    tab.add_creator_to_queue()

    captured = _capture_detection(monkeypatch, tab)
    tab._load_full_creator_from_post_row(post_link)

    assert tab._queue_creator_row(creator) == creator
    assert captured["kwargs"]["post_ids"] is None
    assert tab.current_queue_link == creator
    assert tab._view_kind == "creator"
    assert tab._requested_post_ids == {"1", "2"}


def test_adding_a_post_link_updates_an_open_post_session_live(make_tab, monkeypatch):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/45"
    post_link = f"{creator}/post/1"
    tab.creator_queue_input.setText(post_link)
    tab.add_creator_to_queue()
    tab.current_creator_url = creator
    tab.current_queue_link = post_link
    tab._view_kind = "posts"
    tab._batch_post_ids[creator] = {"1"}

    live = []
    reloads = []
    monkeypatch.setattr(
        tab,
        "_live_append_linked_posts",
        lambda url, ids: live.append((url, set(ids))),
    )
    monkeypatch.setattr(
        tab, "_auto_load_queued_link", lambda link: reloads.append(link)
    )

    tab.creator_queue_input.setText(f"{creator}/post/2")
    assert tab.add_creator_to_queue() == "updated"

    assert live == [(creator, {"2"})]
    assert reloads == []


def test_adding_a_post_link_in_a_creator_session_uses_the_setting(
    make_tab, monkeypatch
):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/46"
    post_link = f"{creator}/post/1"
    tab.creator_queue_input.setText(post_link)
    tab.add_creator_to_queue()
    tab.current_creator_url = creator
    tab.current_queue_link = creator
    tab._view_kind = "creator"
    tab._batch_post_ids[creator] = {"1"}

    live = []
    reloads = []
    monkeypatch.setattr(
        tab,
        "_live_append_linked_posts",
        lambda url, ids: live.append((url, set(ids))),
    )
    monkeypatch.setattr(
        tab, "_auto_load_queued_link", lambda link: reloads.append(link)
    )

    tab.creator_queue_input.setText(f"{creator}/post/2")
    tab.add_creator_to_queue()

    assert live == []
    assert reloads == [post_link]


def test_a_name_refreshes_both_rows_for_a_creator(make_tab):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/47"
    post_link = f"{creator}/post/1"
    tab.creator_queue_input.setText(creator)
    tab.add_creator_to_queue()
    tab.creator_queue_input.setText(post_link)
    tab.add_creator_to_queue()

    tab.on_creator_name_found(creator, "Artist")

    first = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(0))
    second = tab.creator_queue_list.itemWidget(tab.creator_queue_list.item(1))
    assert "[Artist]" in first.label.text()
    assert "[Artist]" in second.label.text()


def test_queue_title_and_input_placeholder(make_tab):
    tab = make_tab("default")

    assert tab.creator_queue_group.title() == "Queue"
    assert tab.creator_queue_input.placeholderText() == "Enter Creator / Post"


def test_live_append_keeps_existing_posts_and_fetches_only_new(make_tab, monkeypatch):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/48"
    post_row = f"{creator}/post/1"
    tab.creator_queue = [(post_row, False)]
    tab._batch_post_ids = {creator: {"1", "2"}}
    tab.current_creator_url = creator
    tab.current_queue_link = post_row
    tab._view_kind = "posts"
    tab.all_detected_posts = [("One", ("1", None))]
    tab.filtered_posts = [("One", "1", None, True)]
    tab.all_files_map[creator] = [("One", ("1", None))]
    tab.checked_urls = {"1": True}

    captured = _capture_detection(monkeypatch, tab)
    tab._start_live_append(creator, {"2"})

    assert captured["kwargs"]["post_ids"] == ["2"]
    assert tab.all_detected_posts == [("One", ("1", None))]
    assert tab._requested_post_ids == {"1", "2"}
    assert tab._fetch_post_ids == {"2"}
    assert tab._fetch_batches_started is True
    assert tab.current_queue_link == post_row


def test_full_creator_button_reuses_an_already_loaded_creator_list(
    make_tab, monkeypatch
):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/49"
    post_row = f"{creator}/post/1"
    tab.creator_queue = [(post_row, False), (creator, False)]
    tab._batch_post_ids = {creator: {"1"}}
    tab.current_creator_url = creator
    tab.current_queue_link = creator
    tab._view_kind = "creator"
    tab.all_detected_posts = [("One", ("1", None)), ("Two", ("2", None))]
    tab.filtered_posts = [
        ("One", "1", None, False),
        ("Two", "2", None, False),
    ]
    tab.checked_urls = {"1": False, "2": False}
    monkeypatch.setattr(
        tab,
        "check_creator_from_queue",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("refetched")),
    )

    tab._load_full_creator_from_post_row(post_row)

    assert tab.current_queue_link == creator
    assert tab._requested_post_ids == {"1"}
    assert tab.checked_urls["1"] is True


def test_removal_confirmation_counts_the_grouped_post_links(make_tab, monkeypatch):
    tab = make_tab("default")
    creator = "https://kemono.cr/fanbox/user/50"
    post_row = f"{creator}/post/1"
    tab.creator_queue = [(post_row, False)]
    tab._batch_post_ids = {creator: {"1", "2"}}
    seen = []

    monkeypatch.setattr(
        cd.QMessageBox,
        "question",
        lambda _parent, _title, text, *args, **kwargs: (
            seen.append(text) or cd.QMessageBox.StandardButton.No
        ),
    )

    tab.create_remove_handler(post_row)()

    assert seen == ["Are you sure you want to remove 2 post links from the queue?"]

