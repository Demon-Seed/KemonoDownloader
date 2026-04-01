from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


class FakeSignal:
    def __init__(self):
        self._cbs = []

    def connect(self, cb):
        self._cbs.append(cb)

    def emit(self, *args):
        import inspect

        for cb in list(self._cbs):
            try:
                n = len(inspect.signature(cb).parameters)
            except Exception:
                n = 0
            cb(*args[:n])


class FakePostDetectionThread:
    def __init__(self, url, post_titles_map, settings):
        self.url = url
        self.post_titles_map = post_titles_map
        self.settings = settings
        self.finished = FakeSignal()
        self.posts_batch = FakeSignal()
        self.log = FakeSignal()
        self.error = FakeSignal()

    def start(self):
        # Emit a small batch and a finished list synchronously
        batch = [("Post One", ("1", "https://thumb"))]
        self.posts_batch.emit(batch)
        self.finished.emit(batch)


class FakePostPopulationThread:
    def __init__(self, detected_posts):
        self.detected_posts = detected_posts
        self.finished = FakeSignal()
        self.log = FakeSignal()

    def start(self):
        # Provide a post_url_map and pass through detected posts
        post_url_map = {
            f"{p[0]} (ID: {p[1][0]})": (p[1][0], p[1][1]) for p in self.detected_posts
        }
        self.finished.emit(post_url_map, list(self.detected_posts))


def make_parent(tmp_path):
    class FakeTabs:
        def count(self):
            return 1

        def currentIndex(self):
            return 0

        def setTabEnabled(self, i, enabled):
            pass

    settings_tab = SimpleNamespace(
        settings_applied=FakeSignal(), language_changed=FakeSignal()
    )
    parent = SimpleNamespace(
        cache_folder=str(tmp_path / "cache"),
        other_files_folder=str(tmp_path / "other"),
        download_folder=str(tmp_path / "download"),
        settings_tab=settings_tab,
        tabs=FakeTabs(),
        status_label=SimpleNamespace(setText=lambda s: None),
        animate_button=lambda *a, **k: None,
    )
    return parent


def test_check_creator_from_queue_flow(qtbot, monkeypatch, tmp_path):
    # Monkeypatch thread classes and thread settings helper
    monkeypatch.setattr(cd, "PostDetectionThread", FakePostDetectionThread)
    monkeypatch.setattr(cd, "PostPopulationThread", FakePostPopulationThread)
    monkeypatch.setattr(
        cd.CreatorDownloaderTab,
        "_create_thread_settings",
        lambda self: SimpleNamespace(
            creator_posts_max_attempts=1,
            post_data_max_retries=1,
            file_download_max_retries=1,
            api_request_max_retries=1,
            simultaneous_downloads=1,
            settings_tab=None,
        ),
    )

    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    url = "https://kemono.cr/service/user/creator1"
    tab.creator_queue.append((url, False))

    # Run the flow
    tab.check_creator_from_queue(url)

    # After the fake threads run synchronously, the queue entry should be marked processed
    assert any(item[0] == url and item[1] for item in tab.creator_queue)
    # all_detected_posts should be populated
    assert tab.all_detected_posts
