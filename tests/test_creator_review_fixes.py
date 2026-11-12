"""Regression tests for the defects found in the code review.

Each test names the review item it pins (A1, A2, ...) so the reason it exists
survives the next refactor of this page.
"""

from datetime import datetime
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd

CREATOR_URL = "https://kemono.cr/patreon/user/42"


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


def test_A1_post_stamps_come_from_the_search_index(qtbot, tmp_path):
    """{post_date}/{post_time} used to be empty: the list holds tuples, not
    post dicts, so the maps were always built from nothing."""
    tab = make_tab(qtbot, tmp_path)
    tab.post_search_index = {
        "42": {"published": datetime(2024, 3, 4, 9, 5)},
        "43": {"published": None},
    }
    tab.all_detected_posts = [("A post", ("42", None))]

    dates, times = tab._post_stamp_maps()

    assert dates == {"42": "2024-03-04"}
    assert times == {"42": "0905"}


def test_A2_a_retry_keeps_the_original_numbers(qtbot, tmp_path, monkeypatch):
    """Retrying the failures must not renumber them or shrink the post count."""
    recorded = []

    class FakeThread:
        def __init__(self, *args, **kwargs):
            recorded.append(kwargs)
            for signal in (
                "file_progress",
                "file_completed",
                "post_completed",
                "creator_folder_ready",
                "log",
                "finished",
            ):
                setattr(self, signal, SimpleNamespace(connect=lambda *a, **k: None))

        def start(self):
            pass

    monkeypatch.setattr(cd, "CreatorDownloadThread", FakeThread)
    tab = make_tab(qtbot, tmp_path)
    urls = [f"https://kemono.cr/f{i}.jpg" for i in range(1, 4)]
    files_map = {url: "42" for url in urls}

    tab._start_download_thread(urls, files_map, CREATOR_URL)

    assert recorded[-1]["file_numbers"] == {urls[0]: 1, urls[1]: 2, urls[2]: 3}
    assert recorded[-1]["post_file_counts"] == {"42": 3}

    # Only the third file failed, so only it is retried - it keeps its number,
    # while the post still reports its three files (what the skip-post-folder
    # rule reads).
    tab._start_download_thread(
        [urls[2]],
        {urls[2]: "42"},
        CREATOR_URL,
        file_numbers=dict(tab._last_run_file_numbers),
        post_file_counts=dict(tab._last_run_post_file_counts),
    )

    assert recorded[-1]["file_numbers"] == {urls[0]: 1, urls[1]: 2, urls[2]: 3}
    assert recorded[-1]["post_file_counts"] == {"42": 3}


def test_A6_a_run_that_never_started_still_signals_finished():
    """Without the signal the tab never runs its cleanup and stays busy."""
    emitted = []
    fake = SimpleNamespace(
        is_running=False,
        finished=SimpleNamespace(emit=lambda: emitted.append(True)),
    )

    cd.CreatorDownloadThread.run(fake)

    assert emitted == [True]


def test_A10_a_zero_upper_bound_is_a_real_bound():
    filters = cd.PostFilters(file_count_max=0)

    assert cd.file_count_out_of_range({"file_count": 3}, filters) is True
    assert cd.file_count_out_of_range({"file_count": 0}, filters) is False


def test_A11_check_all_covers_posts_that_share_a_title(qtbot, tmp_path, monkeypatch):
    """Rows carry their own post id, so same-title posts are all toggled."""
    captured = {}

    class FakeToggleThread:
        def __init__(self, visible_posts, checked_urls, state):
            captured["posts"] = visible_posts
            self.finished = SimpleNamespace(connect=lambda *a, **k: None)
            self.log = SimpleNamespace(connect=lambda *a, **k: None)

        def start(self):
            pass

    monkeypatch.setattr(cd, "CheckboxToggleThread", FakeToggleThread)
    tab = make_tab(qtbot, tmp_path)
    key = "Same title (2024-01-01)"
    tab.post_url_map = {key: ("2", None)}
    tab.add_list_item(key, "https://kemono.cr/p/2", False)
    tab.add_list_item(key, "https://kemono.cr/p/1", False)
    # The second row shares the key; its widget still knows its own id.
    tab.creator_post_list.itemWidget(tab.creator_post_list.item(1)).post_id = "1"

    tab.toggle_check_all(2)

    assert sorted(pid for _title, (pid, _thumb) in captured["posts"]) == ["1", "2"]


def test_A13_a_stopped_fetch_thread_is_held_until_it_ends(qtbot, tmp_path):
    """Dropping the last reference to a running QThread crashes Qt."""
    tab = make_tab(qtbot, tmp_path)

    class FakeThread:
        running = True

        def isRunning(self):
            return self.running

        def deleteLater(self):
            pass

    thread = FakeThread()
    tab.post_detection_thread = thread
    tab.active_threads = [thread]

    tab.cleanup_post_detection_thread()

    assert tab.post_detection_thread is None
    assert thread not in tab.active_threads
    assert thread in tab._lingering_threads

    thread.running = False
    tab._reap_lingering_threads()
    assert tab._lingering_threads == []


def test_A18_refetching_a_creator_does_not_duplicate_the_cached_posts(
    qtbot, tmp_path, monkeypatch
):
    class FakeDetectionThread:
        def __init__(self, *args, **kwargs):
            for signal in ("finished", "posts_batch", "log", "error"):
                setattr(self, signal, SimpleNamespace(connect=lambda *a, **k: None))

        def start(self):
            pass

        def isRunning(self):
            return False

    monkeypatch.setattr(cd, "PostDetectionThread", FakeDetectionThread)
    tab = make_tab(qtbot, tmp_path)
    tab.all_files_map[CREATOR_URL] = [("Old", ("1", None))]

    tab.check_creator_from_queue(CREATOR_URL)
    tab.on_posts_batch_received([("New", ("2", None))])

    assert tab.all_files_map[CREATOR_URL] == [("New", ("2", None))]


def test_A22_the_page_clamps_instead_of_jumping_to_the_first(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.posts_per_page = 10
    tab.current_page = 99
    posts = [(f"T{i}", str(i), None, False) for i in range(25)]

    tab.on_filter_finished(posts)

    assert tab.total_pages == 3
    assert tab.current_page == 3


def test_A23_a_language_change_keeps_the_ticked_count(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.posts_to_download = ["1", "2"]

    tab.update_ui_text()

    assert "2" in tab.creator_post_count_label.text()


def test_A9_one_extension_helper_for_every_source():
    """The fetch used to take content-image extensions from the raw URL."""
    assert cd.detect_extension("https://h/x.jpg?f=x.jpg") == ".jpg"
    assert cd.detect_extension("https://h/x.jpeg") == ".jpg"  # folded to jpg
    assert cd.detect_extension("cover.PNG") == ".png"
    assert cd.detect_extension("no-extension") == ""
    assert cd.detect_extension("") == ""


def test_A8_a_plain_name_keeps_its_url_byte_for_byte():
    """Re-encoding must not change the URLs that already worked.

    The URL is the hash database's identity for a file, so an unnecessary
    change would make every existing copy look new.
    """
    assert cd.filename_query_value("example.png") == "example.png"
    assert cd.filename_query_value("cover (1).png") == "cover (1).png"
    assert cd.filename_query_value("日本語.png") == "日本語.png"


def test_A8_query_characters_are_encoded_and_decoded():
    encoded = cd.filename_query_value("a & b#c+d?e%f.png")

    assert "&" not in encoded and "#" not in encoded and "?" not in encoded
    assert cd.filename_from_query(f"https://h/x.jpg?f={encoded}") == "a & b#c+d?e%f.png"


def test_A8_the_f_value_stops_at_the_next_parameter():
    url = "https://h/x.jpg?f=cover.png&token=abc"

    assert cd.filename_from_query(url) == "cover.png"
    assert cd.filename_from_query("https://h/x.jpg") == ""
    assert cd.filename_from_query("https://h/x.jpg?f=cover%20(1).png") == "cover (1).png"


