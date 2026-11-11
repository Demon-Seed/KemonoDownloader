"""The state guards that keep the Creator tab usable mid-operation.

Each of these covers a case where the tab used to discard work it had already
done (a loaded page list, a retry list) or let the download workers read state
that belonged to the GUI thread.
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


def load_posts(tab, posts):
    """Put *posts* in the tab the way a finished filter pass would."""
    tab.current_creator_url = "https://kemono.cr/artist/user/1"
    tab.all_detected_posts = posts
    tab.filtered_posts = [(title, pid, thumb, False) for title, (pid, thumb) in posts]
    tab.all_files_map[tab.current_creator_url] = list(posts)
    tab.total_pages = 1


class FakeDetectionThread:
    """A detection thread that reports itself as running."""

    def __init__(self):
        self.stopped = False

    def isRunning(self):
        return True

    def stop(self):
        self.stopped = True


def test_cancelling_a_fetch_keeps_the_pages_already_loaded(qtbot, tmp_path):
    """Cancel used to prune the list to the ticked posts.

    With nothing ticked that emptied the whole view, so the pages already
    fetched had to be fetched again to get back to where the user was.
    """
    tab = make_tab(qtbot, tmp_path)
    load_posts(
        tab,
        [
            ("Alpha", ("1", None)),
            ("Beta", ("2", None)),
            ("Gamma", ("3", None)),
        ],
    )
    tab.posts_to_download = []  # nothing ticked
    tab.active_threads = [object()]
    detection = FakeDetectionThread()
    tab.post_detection_thread = detection

    tab.cancel_creator_download()

    assert [post[0] for post in tab.all_detected_posts] == ["Alpha", "Beta", "Gamma"]
    assert len(tab.filtered_posts) == 3
    # The tab's own list of what this creator holds stays in step.
    assert len(tab.all_files_map[tab.current_creator_url]) == 3
    assert detection.stopped is True
    assert tab.post_detection_thread is None


def test_viewing_a_creator_while_fetching_changes_nothing(qtbot, tmp_path):
    """The in-progress guard runs before the state reset, not after it."""
    tab = make_tab(qtbot, tmp_path)
    load_posts(tab, [("Alpha", ("1", None))])
    tab.post_detection_thread = FakeDetectionThread()

    tab.check_creator_from_queue("https://kemono.cr/artist/user/2")

    assert tab.current_creator_url == "https://kemono.cr/artist/user/1"
    assert [post[0] for post in tab.all_detected_posts] == ["Alpha"]
    assert tab.post_detection_thread is not None


def test_extension_boxes_are_locked_while_busy(qtbot, tmp_path):
    """The grid and the filetype filter belong to the Filters box."""
    tab = make_tab(qtbot, tmp_path)
    tab.filter_no_selected_filetypes_check.setChecked(True)

    tab.set_fetching_ui_state(True)
    assert all(not box.isEnabled() for box in tab.creator_ext_checks.values())
    assert tab.filter_no_selected_filetypes_check.isEnabled() is False

    tab.set_fetching_ui_state(False)
    assert all(box.isEnabled() for box in tab.creator_ext_checks.values())
    assert tab.filter_no_selected_filetypes_check.isEnabled() is True

    tab.set_downloading_ui_state(True)
    assert all(not box.isEnabled() for box in tab.creator_ext_checks.values())
    assert tab.filter_no_selected_filetypes_check.isEnabled() is False

    tab.set_downloading_ui_state(False)
    assert all(box.isEnabled() for box in tab.creator_ext_checks.values())


def test_extension_tick_only_refilters_when_the_filter_is_on(
    qtbot, tmp_path, monkeypatch
):
    """A tick cannot change the list while the filetype filter is clear."""
    tab = make_tab(qtbot, tmp_path)
    load_posts(tab, [("Alpha", ("1", None))])
    passes = []
    monkeypatch.setattr(tab, "filter_items", lambda: passes.append(1))

    tab.filter_no_selected_filetypes_check.setChecked(False)
    tab.creator_ext_checks[".png"].setChecked(True)
    assert passes == []

    tab.filter_no_selected_filetypes_check.setChecked(True)
    passes.clear()
    tab.creator_ext_checks[".jpg"].setChecked(True)
    assert passes == [1]


def test_selected_extensions_are_snapshotted_for_the_worker(qtbot, tmp_path):
    """The worker gets a plain list taken on the GUI thread."""
    tab = make_tab(qtbot, tmp_path)
    tab.creator_ext_checks[".png"].setChecked(True)
    tab.creator_ext_checks[".zip"].setChecked(True)

    thread = cd.FilePreparationThread(
        ["1"],
        {},
        tab.creator_ext_checks,
        True,
        True,
        True,
        SimpleNamespace(post_data_max_retries=1, settings_tab=None),
        allowed_extensions=tab._selected_extensions(),
    )

    assert sorted(thread.allowed_extensions) == [".png", ".zip"]

    # Changing a box afterwards must not change the run: the snapshot wins.
    tab.creator_ext_checks[".png"].setChecked(False)
    assert sorted(thread.allowed_extensions) == [".png", ".zip"]


def test_posts_page_setting_is_labelled_as_pages():
    """The setting counts pages of posts, so the label says pages."""
    from kemonodownloader.kd_language import translate

    assert "Pages" in translate("creator_posts_max_attempts")


def test_post_text_option_refilters_only_with_the_filetype_filter_on(
    qtbot, tmp_path, monkeypatch
):
    """"Download Post Text" decides whether text-only posts survive."""
    tab = make_tab(qtbot, tmp_path)
    load_posts(tab, [("Alpha", ("1", None))])
    passes = []
    monkeypatch.setattr(tab, "filter_items", lambda: passes.append(1))

    # Filter off: the option cannot change the list, so no rebuild.
    tab.filter_no_selected_filetypes_check.setChecked(False)
    tab.creator_download_text_check.setChecked(True)
    assert passes == []

    # Filter on: the option is one of its inputs.
    tab.filter_no_selected_filetypes_check.setChecked(True)
    passes.clear()
    tab.creator_download_text_check.setChecked(False)
    assert passes == [1]


def test_post_text_option_is_locked_while_fetching(qtbot, tmp_path):
    """The fetch froze its copy of the option, so it is greyed out with it."""
    tab = make_tab(qtbot, tmp_path)

    tab.set_fetching_ui_state(True)
    assert tab.creator_download_text_check.isEnabled() is False

    tab.set_fetching_ui_state(False)
    assert tab.creator_download_text_check.isEnabled() is True


def test_filetype_filter_list_matches_the_file_counts(qtbot, tmp_path):
    """A .webp-only filter used to keep every text post as well.

    One webp post plus six text posts: the extension grid counted one webp
    file, yet all seven posts stayed listed, because an empty extension set
    meant "nothing to compare, keep it".
    """
    tab = make_tab(qtbot, tmp_path)
    posts = [("Webp post", ("w", None))] + [
        (f"Text {i}", (f"t{i}", None)) for i in range(6)
    ]
    index = {
        "w": cd.analyze_post(
            {
                "id": "w",
                "title": "Webp post",
                "attachments": [{"path": "/d/a.webp", "name": "a.webp"}],
            }
        )
    }
    index.update(
        {
            f"t{i}": cd.analyze_post(
                {"id": f"t{i}", "title": f"Text {i}", "content": "words"}
            )
            for i in range(6)
        }
    )
    tab.filter_no_selected_filetypes_check.setChecked(True)
    tab.creator_ext_checks[".webp"].setChecked(True)
    tab.creator_download_text_check.setChecked(False)

    def run_pass():
        filters, _warnings = tab._post_filters_from_widgets()
        thread = cd.FilterThread(
            posts,
            {},
            "",
            post_search_index=index,
            post_filters=filters,
        )
        finished = []
        thread.finished = SimpleNamespace(emit=lambda items: finished.extend(items))
        thread.run()
        return [title for title, _pid, _thumb, _checked in finished]

    assert run_pass() == ["Webp post"]

    # With the description being downloaded, the text posts yield a file again.
    tab.creator_download_text_check.setChecked(True)
    assert sorted(run_pass()) == sorted(title for title, _pid in posts)


def test_filetype_filter_reads_the_post_text_option(qtbot, tmp_path):
    """The tab's filters carry the option, so fetch and live pass agree."""
    tab = make_tab(qtbot, tmp_path)
    tab.filter_no_selected_filetypes_check.setChecked(True)
    tab.creator_ext_checks[".webp"].setChecked(True)

    tab.creator_download_text_check.setChecked(False)
    filters, _warnings = tab._post_filters_from_widgets()
    assert filters.download_post_text is False
    assert filters.required_filetypes == frozenset({".webp"})

    tab.creator_download_text_check.setChecked(True)
    filters, _warnings = tab._post_filters_from_widgets()
    assert filters.download_post_text is True


def test_the_enabled_filetype_filter_shows_nothing_without_types(qtbot, tmp_path):
    """On with nothing ticked: an empty list and a hint saying why."""
    tab = make_tab(qtbot, tmp_path)
    load_posts(tab, [("Alpha", ("1", None)), ("Beta", ("2", None))])
    tab.filter_no_selected_filetypes_check.setChecked(True)

    assert tab._required_filetypes() == frozenset()

    tab.filtered_posts = []
    tab.display_current_page()

    assert tab.creator_post_list.count() == 0
    assert tab.creator_post_empty_label.isVisibleTo(tab) is True
    assert tab.creator_post_empty_label.text() == "Supported Filetypes Not Present"


def test_the_empty_list_hint_goes_back_to_the_generic_message(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    load_posts(tab, [("Alpha", ("1", None))])
    tab.creator_ext_checks[".png"].setChecked(True)
    tab.filter_no_selected_filetypes_check.setChecked(True)

    tab.filtered_posts = []
    tab.display_current_page()

    assert tab.creator_post_empty_label.text() == "No posts match the current filters"


def test_clearing_the_queue_untickes_the_filetypes(qtbot, tmp_path, monkeypatch):
    """A tick left behind after the queue is cleared filters a gone creator."""
    from PyQt6.QtWidgets import QMessageBox

    tab = make_tab(qtbot, tmp_path)
    url = "https://kemono.cr/artist/user/1"
    tab.creator_queue = [(url, True)]
    tab.creator_ext_checks[".png"].setChecked(True)
    tab.filter_no_selected_filetypes_check.setChecked(True)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(tab, "filter_items", lambda: None)

    tab.create_remove_handler(url)()

    assert tab._selected_extensions() == []
    assert all(not box.isChecked() for box in tab.creator_ext_checks.values())
    assert tab.creator_queue == []


def test_download_thread_gets_each_post_once(qtbot, tmp_path, monkeypatch):
    """Concurrent preparation fills the file map out of order.

    The download thread only needs each post once, because file numbering now
    comes from the filename templates rather than from a post's place in the
    selection.
    """
    tab = make_tab(qtbot, tmp_path)
    tab.current_creator_url = "https://kemono.cr/artist/user/1"
    captured = {}

    class FakeSignal:
        def connect(self, *_args):
            return None

    class FakeThread:
        def __init__(self, *args, **_kwargs):
            captured["selected_posts"] = args[3]

        def __getattr__(self, _name):
            return FakeSignal()

        def start(self):
            return None

    monkeypatch.setattr(cd, "CreatorDownloadThread", FakeThread)

    files = {
        "https://n1.kemono.cr/data/three.png": "3",
        "https://n1.kemono.cr/data/one.png": "1",
        "https://n1.kemono.cr/data/two.png": "2",
        "https://n1.kemono.cr/data/three-again.png": "3",
    }
    tab._start_download_thread(
        list(files),
        dict(files),
        tab.current_creator_url,
    )

    assert sorted(captured["selected_posts"]) == ["1", "2", "3"]


def test_a_retry_keeps_its_own_order(qtbot, tmp_path, monkeypatch):
    """Without a preparation order, the file map order is used as before."""
    tab = make_tab(qtbot, tmp_path)
    captured = {}

    class FakeSignal:
        def connect(self, *_args):
            return None

    class FakeThread:
        def __init__(self, *args, **_kwargs):
            captured["selected_posts"] = args[3]

        def __getattr__(self, _name):
            return FakeSignal()

        def start(self):
            return None

    monkeypatch.setattr(cd, "CreatorDownloadThread", FakeThread)

    files = {"https://n1.kemono.cr/data/b.png": "b", "https://n1.kemono.cr/data/a.png": "a"}
    tab._start_download_thread(list(files), dict(files), tab.current_creator_url)

    assert captured["selected_posts"] == ["b", "a"]
