"""Thread bookkeeping for the Creator tab.

The post-population and file-preparation threads were appended to
``active_threads`` and never removed. Because ``retry_failed_downloads()``
refused to start while that list was non-empty, "Retry Failed Downloads" was
dead for the rest of the session after any fetch or download.
"""

from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


class FinishedThread:
    """Minimal stand-in for a QThread that has already stopped."""

    def __init__(self, failed=None):
        self.failed_files = failed
        self.deleted = False

    def isRunning(self):
        return False

    def wait(self, *args, **kwargs):
        return None

    def deleteLater(self):
        self.deleted = True


class RunningThread(FinishedThread):
    """A stand-in for a thread that is still running."""

    def isRunning(self):
        return True


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


def test_cleanup_file_preparation_thread_releases_the_slot(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    thread = FinishedThread()
    tab.file_preparation_thread = thread
    tab.active_threads = [thread]

    tab.cleanup_file_preparation_thread()

    assert tab.active_threads == []
    assert tab.file_preparation_thread is None
    assert thread.deleted is True


def test_cleanup_post_population_thread_releases_the_slot(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    thread = FinishedThread()
    tab.post_population_thread = thread
    tab.active_threads = [thread]

    tab.cleanup_post_population_thread()

    assert tab.active_threads == []
    assert tab.post_population_thread is None
    assert thread.deleted is True


def test_cleanup_post_population_thread_is_a_no_op_without_a_thread(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    tab.cleanup_post_population_thread()

    assert tab.active_threads == []


def test_cleanup_thread_only_finalises_the_run_it_owns(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    finished = []
    tab.creator_download_finished = lambda: finished.append(True)

    stale = FinishedThread()
    owner = RunningThread()
    tab._download_thread = owner
    tab.active_threads = [stale, owner]
    tab.total_files_to_download = 1
    tab.completed_files = {"u"}

    tab.cleanup_thread(stale)

    # A superseded thread that unwinds late must not touch the newer run.
    assert finished == []
    assert stale not in tab.active_threads
    assert tab._download_thread is owner


def test_cleanup_thread_finalises_and_releases_the_owning_thread(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    finished = []
    tab.creator_download_finished = lambda: finished.append(True)

    thread = FinishedThread()
    tab._download_thread = thread
    tab.active_threads = [thread]
    tab.total_files_to_download = 1
    tab.completed_files = {"u"}

    tab.cleanup_thread(thread)

    assert finished == [True]
    assert tab._download_thread is None


def test_download_in_progress_follows_the_thread_not_only_the_flag(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab._download_in_progress() is False

    tab.downloading = True
    assert tab._download_in_progress() is True

    # The run flag is cleared as soon as the last file reports back, while the
    # thread itself may still be unwinding.
    tab.downloading = False
    tab._download_thread = RunningThread()
    assert tab._download_in_progress() is True

    tab._download_thread = FinishedThread()
    assert tab._download_in_progress() is False
