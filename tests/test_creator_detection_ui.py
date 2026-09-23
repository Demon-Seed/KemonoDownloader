from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


class FakeSignal:
    def __init__(self):
        self._cbs = []

    def connect(self, cb):
        self._cbs.append(cb)

    def emit(self, *args):
        for cb in list(self._cbs):
            try:
                cb(*args)
            except TypeError:
                # Some slots may accept fewer args; fall back to calling without args
                cb()


class FakePostDetectionThread:
    def __init__(self, url, post_titles_map, settings, **kwargs):
        self.finished = FakeSignal()
        self.posts_batch = FakeSignal()
        self.log = FakeSignal()
        self.error = FakeSignal()
        self._started = False

    def start(self):
        # Simulate an incremental batch followed by finished
        sample = [("TitleX", ("1", "thumb"))]
        self.posts_batch.emit(sample)
        self.finished.emit(sample)


def make_parent(tmp_path):
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path / "cache")
    parent.other_files_folder = str(tmp_path / "other")
    parent.download_folder = str(tmp_path / "dl")
    parent.settings_tab = None
    parent.ensure_folders_exist = lambda: None
    parent.post_tab = SimpleNamespace()
    parent.creator_tab = SimpleNamespace()
    # settings_tab must provide a settings_applied signal with connect()
    parent.settings_tab = SimpleNamespace()
    parent.settings_tab.settings_applied = FakeSignal()
    parent.settings_tab.language_changed = FakeSignal()
    # Provide minimal getters used by CreatorDownloaderTab._create_thread_settings
    parent.settings_tab.get_creator_posts_max_attempts = lambda: 1
    parent.settings_tab.get_post_data_max_retries = lambda: 1
    parent.settings_tab.get_file_download_max_retries = lambda: 1
    parent.settings_tab.get_api_request_max_retries = lambda: 1
    parent.settings_tab.get_simultaneous_downloads = lambda: 1
    return parent


def test_check_creator_from_queue_triggers_detection(monkeypatch, tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Prevent modal dialogs
    monkeypatch.setattr(cd.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(cd.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(
        cd.QMessageBox, "question", lambda *a, **k: cd.QMessageBox.StandardButton.Yes
    )

    # Monkeypatch PostDetectionThread to our fake
    monkeypatch.setattr(cd, "PostDetectionThread", FakePostDetectionThread)

    called = {}

    def fake_start_population(posts):
        called["started"] = True

    tab.start_population_thread = fake_start_population

    url = "https://kemono.cr/user/123"
    tab.creator_queue.append((url, False))
    tab.check_creator_from_queue(url)

    # The fake thread will finish immediately; ensure the population start was called
    assert called.get("started") is True
