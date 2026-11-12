"""Tests for the Creator-tab "Retry Failed Downloads" action.

A finished or cancelled run keeps its failures, and the retry button starts a
download thread for exactly those files - no re-fetch, no re-preparation.
"""

from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd

CREATOR_URL = "https://kemono.cr/patreon/user/42"

def log_text(tab):
    """Return the tab's log lines as plain text (there is no console)."""
    return "\n".join(message for message, _colour in tab.log_lines_from(0))




class FakeDownloadThread:
    """Stands in for the real QThread so retrying never downloads."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.failed_files = {}
        self.file_progress = SimpleNamespace(connect=lambda cb: None)
        self.file_completed = SimpleNamespace(connect=lambda cb: None)
        self.post_completed = SimpleNamespace(connect=lambda cb: None)
        self.creator_folder_ready = SimpleNamespace(connect=lambda cb: None)
        self.log = SimpleNamespace(connect=lambda cb: None)
        self.finished = SimpleNamespace(connect=lambda cb: None)
        FakeDownloadThread.instances.append(self)

    def start(self):
        pass

    def isRunning(self):
        return False


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


def make_tab(qtbot, tmp_path, monkeypatch):
    FakeDownloadThread.instances = []
    monkeypatch.setattr(cd, "CreatorDownloadThread", FakeDownloadThread)
    tab = cd.CreatorDownloaderTab(make_parent(tmp_path))
    qtbot.addWidget(tab)
    tab.current_creator_url = CREATOR_URL
    return tab


def _seed_failures(tab):
    tab._last_run_creator_url = CREATOR_URL
    tab._last_run_failed_files = {
        "https://n1/one.jpg": "timed out",
        "https://n1/two.zip": "404",
    }
    tab._last_run_files_to_posts_map = {
        "https://n1/one.jpg": "post-1",
        "https://n1/two.zip": "post-2",
    }
    tab._last_run_post_ids = ["post-1", "post-2"]
    tab._refresh_retry_button()


def test_retry_downloads_only_the_failed_files(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path, monkeypatch)
    _seed_failures(tab)

    tab.retry_failed_downloads()

    assert len(FakeDownloadThread.instances) == 1
    thread = FakeDownloadThread.instances[0]
    service, creator_id, _folder, post_ids, files, files_map = thread.args[:6]
    assert service == "patreon"
    assert creator_id == "42"
    assert sorted(files) == ["https://n1/one.jpg", "https://n1/two.zip"]
    assert files_map == tab._last_run_files_to_posts_map
    assert sorted(post_ids) == ["post-1", "post-2"]


def test_retry_resets_the_run_state(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path, monkeypatch)
    _seed_failures(tab)
    tab.completed_files = {"stale"}
    tab.failed_files = {"stale": "stale"}

    tab.retry_failed_downloads()

    assert tab.downloading is True
    assert tab.total_files_to_download == 2
    assert tab.total_posts_to_download == 2
    assert tab.completed_files == set()
    assert tab.failed_files == {}
    assert tab.creator_retry_failed_btn.isVisibleTo(tab) is True
    assert tab.creator_retry_failed_btn.isEnabled() is False
    assert "Retrying 2 failed file(s)" in log_text(tab)


def test_retry_without_failures_only_warns(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path, monkeypatch)

    tab.retry_failed_downloads()

    assert FakeDownloadThread.instances == []
    assert tab.downloading is False
    assert "Nothing to retry" in log_text(tab)


def test_retry_is_refused_while_a_download_runs(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path, monkeypatch)
    _seed_failures(tab)
    tab.downloading = True

    tab.retry_failed_downloads()

    assert FakeDownloadThread.instances == []
    assert "A download is already running" in log_text(tab)


def test_retry_keeps_failures_the_map_cannot_place(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path, monkeypatch)
    tab._last_run_creator_url = CREATOR_URL
    tab._last_run_failed_files = {"https://n1/orphan.jpg": "boom"}
    tab._last_run_files_to_posts_map = {}

    tab.retry_failed_downloads()

    assert FakeDownloadThread.instances == []
    assert "Nothing to retry" in log_text(tab)
    assert tab.creator_retry_failed_btn.isEnabled() is False


def test_retry_keys_translated_in_all_languages():
    from kemonodownloader.kd_language import language_manager, translate

    keys = [
        "retry_failed_downloads",
        "retry_failed_downloads_tooltip",
        "retrying_failed_files",
        "retry_unavailable",
        "retry_already_downloading",
    ]
    original = language_manager.current_language
    try:
        for language in language_manager.get_available_languages():
            language_manager.set_language(language)
            for key in keys:
                assert translate(key, 1) not in ("", key)
    finally:
        language_manager.set_language(original)


class FinishedThreadStand:
    """A thread that already stopped but is still listed as active."""

    def isRunning(self):
        return False


class RunningThreadStand:
    def isRunning(self):
        return True


def test_retry_ignores_finished_threads_left_in_active_threads(
    qtbot, tmp_path, monkeypatch
):
    """Regression: stale bookkeeping must not block the retry action."""
    tab = make_tab(qtbot, tmp_path, monkeypatch)
    _seed_failures(tab)
    tab.active_threads.append(FinishedThreadStand())

    tab.retry_failed_downloads()

    assert len(FakeDownloadThread.instances) == 1
    assert "A download is already running" not in log_text(tab)


def test_retry_is_refused_while_the_download_thread_still_runs(
    qtbot, tmp_path, monkeypatch
):
    tab = make_tab(qtbot, tmp_path, monkeypatch)
    _seed_failures(tab)
    tab.downloading = False
    tab._download_thread = RunningThreadStand()

    tab.retry_failed_downloads()

    assert FakeDownloadThread.instances == []
    assert "A download is already running" in log_text(tab)
