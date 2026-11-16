"""Creator Queue input row: commit keys, auto-load modes and double-click."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from kemonodownloader import creator_downloader as cd


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
    tab.check_creator_from_queue = lambda url: tab.set_fetching_ui_state(True)

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
