import os
from types import SimpleNamespace

from PyQt6.QtWidgets import QWidget

from kemonodownloader import creator_downloader as cd


class DummySignal:
    def connect(self, fn):
        self._fn = fn


def make_parent(tmp_path):
    parent = QWidget()
    parent.cache_folder = str(tmp_path / "cache")
    parent.other_files_folder = str(tmp_path / "other")
    parent.download_folder = str(tmp_path / "downloads")
    os.makedirs(parent.cache_folder, exist_ok=True)
    os.makedirs(parent.other_files_folder, exist_ok=True)
    os.makedirs(parent.download_folder, exist_ok=True)

    st = SimpleNamespace()
    st.get_creator_posts_max_attempts = lambda: 1
    st.get_post_data_max_retries = lambda: 1
    st.get_file_download_max_retries = lambda: 1
    st.get_api_request_max_retries = lambda: 1
    st.get_simultaneous_downloads = lambda: 1
    st.get_creator_filename_template = lambda: None
    st.get_creator_folder_strategy = lambda: "per_post"
    st.settings_applied = SimpleNamespace(connect=lambda f: None)
    st.language_changed = SimpleNamespace(connect=lambda f: None)
    parent.settings_tab = st

    class Tabs:
        def __init__(self):
            self._count = 3

        def count(self):
            return self._count

        def currentIndex(self):
            return 0

        def setTabEnabled(self, i, v):
            pass

    parent.tabs = Tabs()
    parent.status_label = SimpleNamespace(
        setText=lambda s: setattr(parent, "_status", s)
    )
    parent.animate_button = lambda b, v: None
    parent.creator_console = SimpleNamespace(
        toHtml=lambda: "<b>log</b>",
        clear=lambda: None,
        append=lambda html: None,
    )
    parent.append_log_to_console = lambda *a, **k: None
    return parent


def make_tab(tmp_path):
    return cd.CreatorDownloaderTab(make_parent(tmp_path))


def test_start_creator_download_prepares_only_current_creator(tmp_path):
    """Download must not re-fetch posts or walk the creator queue."""
    tab = make_tab(tmp_path)
    tab.creator_queue = [("https://kemono.cr/fanbox/user/1", True)]
    tab.current_creator_url = "https://kemono.cr/fanbox/user/1"
    tab.posts_to_download = ["101"]

    refetched = []
    prepared = []
    tab.check_creator_from_queue = lambda url: refetched.append(url)
    tab.prepare_files_for_download = lambda urls: prepared.append(urls)

    tab.start_creator_download()

    assert refetched == []
    assert prepared == [["https://kemono.cr/fanbox/user/1"]]


def test_prepare_files_for_download_starts_thread(tmp_path, monkeypatch):
    tab = make_tab(tmp_path)
    tab.current_creator_url = "https://kemono.cr/fanbox/user/1"
    tab.posts_to_download = ["101"]
    tab.all_files_map = {
        tab.current_creator_url: [("Post", ("101", None))],
    }

    class FakeFilePreparationThread:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.started = False
            self.progress = DummySignal()
            self.finished = DummySignal()
            self.log = DummySignal()
            self.error = DummySignal()

        def start(self):
            self.started = True

        def isRunning(self):
            return False

        def deleteLater(self):
            pass

    monkeypatch.setattr(cd, "FilePreparationThread", FakeFilePreparationThread)

    tab.prepare_files_for_download([tab.current_creator_url])

    assert tab.file_preparation_thread is not None
    assert tab.file_preparation_thread.started is True
    assert tab.file_preparation_thread in tab.active_threads


def test_on_file_preparation_finished_starts_download_thread_and_strips_query(
    tmp_path, monkeypatch
):
    tab = make_tab(tmp_path)
    tab.posts_to_download = ["101"]
    tab.total_posts_to_download = 1

    created = {}

    class FakeCreatorDownloadThread:
        def __init__(
            self,
            service,
            creator_id,
            download_folder,
            selected_posts,
            files_to_download,
            files_to_posts_map,
            console,
            other_files_dir,
            post_titles_map,
            auto_rename_enabled,
            settings,
            max_concurrent,
            download_text=False,
            **kwargs,
        ):
            created["service"] = service
            created["creator_id"] = creator_id
            created["download_folder"] = download_folder
            created["files"] = files_to_download
            self.file_progress = DummySignal()
            self.file_completed = DummySignal()
            self.post_completed = DummySignal()
            self.log = DummySignal()
            self.finished = DummySignal()
            self.started = False

        def start(self):
            self.started = True
            created["started"] = True

    monkeypatch.setattr(cd, "CreatorDownloadThread", FakeCreatorDownloadThread)

    tab.on_file_preparation_finished(
        ["https://kemono.cr/fanbox/user/42?q=abc"],
        ["https://kemono.cr/files/a.jpg"],
        {"https://kemono.cr/files/a.jpg": "101"},
    )

    assert created["service"] == "fanbox"
    assert created["creator_id"] == "42"
    assert created["started"] is True


def test_cleanup_thread_waiting_branch_keeps_running_state(tmp_path):
    tab = make_tab(tmp_path)

    class FakeThread:
        def __init__(self):
            self.failed_files = None

        def isRunning(self):
            return False

        def wait(self, *args, **kwargs):
            return None

        def deleteLater(self):
            return None

    thread = FakeThread()
    other_thread = FakeThread()
    tab.active_threads = [thread, other_thread]
    tab.total_files_to_download = 5
    tab.completed_files = {"one"}
    tab.failed_files = {}

    called = []
    tab.creator_download_finished = lambda: called.append("finished")

    tab.cleanup_thread(thread)

    # Files are still outstanding and another thread is active -> keep waiting.
    assert called == []
    assert other_thread in tab.active_threads


def test_cleanup_thread_finishes_when_all_files_attempted(tmp_path):
    tab = make_tab(tmp_path)

    class FakeThread:
        def __init__(self):
            self.failed_files = None

        def isRunning(self):
            return False

        def wait(self, *args, **kwargs):
            return None

        def deleteLater(self):
            return None

    thread = FakeThread()
    tab.active_threads = [thread]
    tab.total_files_to_download = 2
    tab.completed_files = {"one", "two"}
    tab.failed_files = {}

    called = []
    tab.creator_download_finished = lambda: called.append("finished")

    tab.cleanup_thread(thread)

    assert called == ["finished"]


def test_cancel_creator_download_starts_cancellation_thread(tmp_path, monkeypatch):
    tab = make_tab(tmp_path)
    tab.active_threads = [SimpleNamespace()]
    tab.post_detection_thread = None

    class FakeCancellationThread:
        def __init__(self, threads):
            self.threads = threads
            self.finished = DummySignal()
            self.log = DummySignal()
            self.started = False

        def start(self):
            self.started = True

    monkeypatch.setattr(cd, "CancellationThread", FakeCancellationThread)

    tab.cancel_creator_download()

    assert tab._cancellation_thread is not None
    assert tab._cancellation_thread.started is True


def test_on_cancellation_finished_runtimeerror_branch(tmp_path):
    tab = make_tab(tmp_path)

    class BadDeleteThread:
        def isRunning(self):
            return False

        def wait(self, *args, **kwargs):
            return None

        def deleteLater(self):
            raise RuntimeError("already deleted")

    class CancelThread:
        def wait(self, *args, **kwargs):
            return None

        def deleteLater(self):
            return None

    tab.active_threads = [BadDeleteThread()]
    tab._cancellation_thread = CancelThread()
    tab.downloading = True
    tab.total_files_to_download = 2
    tab.completed_files = {"a"}
    tab.failed_files = {"b": "err"}
    tab.completed_posts = {"p"}

    tab.on_cancellation_finished()

    assert tab._cancellation_thread is None
    assert tab.downloading is False
    assert tab.creator_queue == []
