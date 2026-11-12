"""Shared factories for the test suite.

Tests used to carry their own copy of each helper; after the file
consolidation several ended up with a merged-module suffix. One factory per
shape lives here instead, and tests import them. Keep these behaviour-
compatible with the copies they replaced: a test that silently gets a
different stub is not testing what it thinks it is.
"""

from types import SimpleNamespace

import requests
from PyQt6.QtWidgets import QWidget

from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


class Signal:
    """Minimal Qt-signal stand-in; a slot taking fewer args is called bare."""

    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            try:
                callback(*args)
            except TypeError:
                callback()


class RecordingSignal:
    """Signal stand-in that records whether and with what it was emitted."""

    def __init__(self):
        self.emitted = False
        self.last_args = None

    def emit(self, *args):
        self.emitted = True
        self.last_args = args


class FakeTabs:
    """The QTabWidget surface the Creator tab touches while fetching."""

    def count(self):
        return 1

    def currentIndex(self):
        return 0

    def setTabEnabled(self, index, enabled):
        return None


class StreamingResponse:
    """Response with iter_content(); content-length defaults to the chunks."""

    def __init__(self, chunks, headers=None, status_code=200):
        self._chunks = list(chunks)
        self.status_code = status_code
        if headers is None:
            headers = {"content-length": str(sum(len(chunk) for chunk in self._chunks))}
        self.headers = headers

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def raise_for_status(self):
        return None

    def close(self):
        return None


class JsonResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


class SessionReturning:
    """Session whose get() always returns the same response."""

    def __init__(self, response):
        self._response = response

    def get(self, *args, **kwargs):
        return self._response


class AlwaysFailingSession:
    def get(self, *args, **kwargs):
        raise requests.RequestException("network failure")


class LogStoreParent(QWidget):
    """Parent exposing the shared log-store API the LogsWindow reads."""

    def __init__(self, lines=()):
        super().__init__()
        self._lines = list(lines)
        self.clear_calls = 0
        self.logged = []

    def log_lines_from(self, index):
        return self._lines[index:]

    def log_next_index(self):
        return len(self._lines)

    def clear_log(self):
        self.clear_calls += 1
        self._lines.clear()

    def append_log_to_console(self, message, level=None):
        self.logged.append((message, level))


def make_settings_stub(template=None):
    """The getters and signals CreatorDownloaderTab expects from SettingsTab."""
    return SimpleNamespace(
        settings_applied=Signal(),
        language_changed=Signal(),
        get_creator_posts_max_attempts=lambda: 1,
        get_post_data_max_retries=lambda: 1,
        get_file_download_max_retries=lambda: 1,
        get_api_request_max_retries=lambda: 1,
        get_simultaneous_downloads=lambda: 1,
        get_creator_filename_template=lambda: template,
        get_creator_folder_strategy=lambda: "per_post",
        get_proxy_settings=lambda: None,
    )


def make_tab_parent(tmp_path, *, window=False):
    """MainWindow stand-in as CreatorDownloaderTab sees it.

    ``window=True`` adds the tab-switching/status surface the fetching paths
    touch; the plain shape is enough for queue, dialog and update tests.
    """
    parent = SimpleNamespace(
        cache_folder=str(tmp_path / "cache"),
        other_files_folder=str(tmp_path / "other"),
        download_folder=str(tmp_path / "download"),
        settings_tab=make_settings_stub(),
        ensure_folders_exist=lambda: None,
        post_tab=SimpleNamespace(),
        creator_tab=SimpleNamespace(),
        log=lambda *args, **kwargs: None,
    )
    if window:
        parent.tabs = FakeTabs()
        parent.status_label = SimpleNamespace(setText=lambda text: None)
        parent.animate_button = lambda *args, **kwargs: None
    return parent


def make_settings(template=None, **overrides):
    """ThreadSettings with a stub settings tab; every number defaults to 1."""
    numbers = {
        "creator_posts_max_attempts": 1,
        "post_data_max_retries": 1,
        "file_download_max_retries": 1,
        "api_request_max_retries": 1,
        "simultaneous_downloads": 1,
    }
    numbers.update(overrides)
    return ThreadSettings(**numbers, settings_tab=make_settings_stub(template))


def make_thread(tmp_path, file_url, other_dir=None, settings_retries=2):
    """CreatorDownloadThread wired for one file, without touching the network."""
    return CreatorDownloadThread(
        "kemono",
        "9",
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        None,
        other_dir or str(tmp_path / "other"),
        {},
        make_settings(file_download_max_retries=settings_retries),
        max_concurrent=1,
        download_text=False,
    )
