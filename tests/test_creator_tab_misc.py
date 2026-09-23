from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


def make_parent(tmp_path):
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path / "cache")
    parent.other_files_folder = str(tmp_path / "other")
    parent.download_folder = str(tmp_path / "dl")
    st = SimpleNamespace()
    st.settings_applied = SimpleNamespace(connect=lambda cb: None)
    st.language_changed = SimpleNamespace(connect=lambda cb: None)
    st.get_creator_posts_max_attempts = lambda: 1
    st.get_post_data_max_retries = lambda: 1
    st.get_file_download_max_retries = lambda: 1
    st.get_api_request_max_retries = lambda: 1
    st.get_simultaneous_downloads = lambda: 1
    parent.settings_tab = st
    parent.ensure_folders_exist = lambda: None
    parent.post_tab = SimpleNamespace()
    parent.creator_tab = SimpleNamespace()
    return parent


def test_update_pagination_controls(tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    tab.total_pages = 3
    tab.current_page = 2
    tab.downloading = True
    tab.update_pagination_controls()
    assert not tab.prev_page_btn.isEnabled()
    assert not tab.next_page_btn.isEnabled()

    tab.downloading = False
    tab.update_pagination_controls()
    assert tab.prev_page_btn.isEnabled()
    assert tab.next_page_btn.isEnabled()


def test_display_current_page_populates_list(tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)
    # prepare 3 filtered posts and set posts_per_page to 2
    tab.filtered_posts = [
        ("T1", "1", "thumb1", False),
        ("T2", "2", "thumb2", True),
        ("T3", "3", "thumb3", False),
    ]
    tab.posts_per_page = 2
    tab.current_page = 1
    tab.post_dates_map = {"1": "2024-01-02", "2": "2024-01-03"}
    tab.display_current_page()
    # Should display two items on page 1
    assert tab.creator_post_list.count() == 2
    # post_url_map keys are the unique titles (post title + post date)
    assert any("T1 (2024-01-02)" in k for k in tab.post_url_map.keys())


def test_on_post_detection_error_uses_cached_posts(monkeypatch, tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)
    tab.current_creator_url = "https://kemono.cr/user/1"
    cached = [("T1", ("1", "thumb1"))]
    tab.all_files_map = {tab.current_creator_url: cached}

    called = {}

    def fake_start(posts):
        called["started"] = posts

    tab.start_population_thread = fake_start
    tab.on_post_detection_error("error")
    assert "started" in called
    assert called["started"] == cached


def test_cleanup_thread_transfers_failed_files(tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    class FakeThread:
        def __init__(self):
            self.failed_files = {"u1": "err"}
            self._deleted = False

        def isRunning(self):
            return False

        def deleteLater(self):
            self._deleted = True

        def __repr__(self):
            return "FakeThread"

    th = FakeThread()
    keep_alive = FakeThread()
    keep_alive.failed_files = None
    tab.active_threads = [th, keep_alive]
    # Files are still outstanding, so this cleanup must not end the run
    # (ending it logs the failures and clears the set).
    tab.total_files_to_download = 5
    tab.completed_files = set()

    tab.cleanup_thread(th)

    assert "u1" in tab.failed_files
    assert th._deleted is True
    assert keep_alive in tab.active_threads
