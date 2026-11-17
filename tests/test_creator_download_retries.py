"""Retry, cancellation and run-loop behaviour of the download thread."""

import asyncio
import hashlib
import os
import types
from types import MethodType, SimpleNamespace

import requests
from tests.factories import (
    AlwaysFailingSession,
    RecordingSignal,
    make_settings,
    make_thread,
)

from kemonodownloader import creator_downloader as cd
from kemonodownloader.creator_downloader import CreatorDownloadThread
from kemonodownloader.retry_policy import DOWNLOAD_RETRY_MAX_DELAY, RETRY_AFTER_CAP


def test_creator_download_run_processes_queue(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "run_d")
    other_files_dir = str(tmp_path / "run_o")

    files = [f"https://kemono.cr/files/{i}.png" for i in range(3)]

    settings = make_settings(simultaneous_downloads=2)

    thread = CreatorDownloadThread(
        service="svc",
        creator_id="c",
        download_folder=download_folder,
        selected_posts=[str(i) for i in range(1, 4)],
        files_to_download=files,
        files_to_posts_map={u: str(i) for i, u in enumerate(files, start=1)},
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Prevent network calls in fetch_creator_and_post_info
    thread.fetch_creator_and_post_info = lambda: None

    async def fake_download_file(
        file_url, folder, file_index, total_files, page_number
    ):
        # mark as completed
        thread.completed_files.add(file_url)

    # Bind coroutine to instance
    thread.download_file = types.MethodType(
        lambda self, *a, **k: fake_download_file(*a, **k), thread
    )

    # Run the thread.run() which should process the queue and finish
    thread.run()

    # All files should have been processed (added to completed_files)
    for u in files:
        assert u in thread.completed_files


class FakeSessionAlwaysError:
    def get(self, *args, **kwargs):
        raise requests.RequestException("network failure")


def test_hash_db_size_mismatch_triggers_redownload(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "downloads_h")
    other_files_dir = str(tmp_path / "other_h")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/mismatch.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "9"}

    settings = make_settings(file_download_max_retries=2)

    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creatorH",
        download_folder=download_folder,
        selected_posts=["9"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Create an existing file with a size that doesn't match the expected
    existing_path = os.path.join(other_files_dir, "existing.png")
    with open(existing_path, "wb") as f:
        f.write(b"short")

    # Store an entry in the hash DB with an expected size different from actual
    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    # Provide a file_hash (md5) and an expected file_size that is incorrect
    thread.hash_db.store(
        url_hash, existing_path, hashlib.md5(b"short").hexdigest(), file_url, 9999
    )

    # Monkeypatch get_session to always raise so download attempts fail
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSessionAlwaysError(),
    )

    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    # Because download failed after retries, it should be recorded as failed
    assert file_url in thread.failed_files


class FakeResponseMismatch:
    def __init__(self, chunks, header_size):
        self._chunks = chunks
        self.status_code = 200
        self.headers = {"content-length": str(header_size)}

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c

    def raise_for_status(self):
        return None

    def close(self):
        return None


class FakeSessionMismatch:
    def __init__(self, chunks, header_size):
        self._chunks = chunks
        self._header_size = header_size

    def get(self, *args, **kwargs):
        return FakeResponseMismatch(self._chunks, self._header_size)


class FakeResponseCancel:
    def __init__(self, chunks, thread_ref):
        self._chunks = chunks
        self.status_code = 200
        self.headers = {"content-length": str(sum(len(c) for c in chunks))}
        self._thread_ref = thread_ref

    def iter_content(self, chunk_size=8192):
        first = True
        for c in self._chunks:
            if first:
                first = False
                yield c
            else:
                # Simulate user cancellation just before next chunk is processed
                try:
                    self._thread_ref.stop()
                except Exception:
                    pass
                yield c

    def raise_for_status(self):
        return None

    def close(self):
        return None


class FakeSessionCancel:
    def __init__(self, chunks, thread_ref):
        self._chunks = chunks
        self._thread_ref = thread_ref

    def get(self, *args, **kwargs):
        return FakeResponseCancel(self._chunks, self._thread_ref)


def test_size_mismatch_deletes_incomplete_and_records_failure(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "d_mismatch")
    other_files_dir = str(tmp_path / "other_mismatch")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/partial.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Chunks smaller than header indicates → triggers size-mismatch path
    chunks = [b"abc"]
    header_size = 10

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSessionMismatch(chunks, header_size),
    )

    settings = make_settings()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creator123", "1"): "MyPost"},
        settings=settings,
        download_text=False,
    )

    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    assert file_url not in thread.completed_files
    assert file_url in thread.failed_files
    msg = thread.failed_files[file_url]
    assert "size mismatch" in msg.lower()

    # Ensure no file artifacts remain under download_folder
    found_files = []
    for root, dirs, files in os.walk(download_folder):
        for f in files:
            found_files.append(os.path.join(root, f))
    assert len(found_files) == 0


def test_cancellation_during_streaming_deletes_incomplete_and_records_failure(
    monkeypatch, tmp_path
):
    download_folder = str(tmp_path / "d_cancel")
    other_files_dir = str(tmp_path / "other_cancel")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/cancel.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    chunks = [b"first", b"second"]

    settings = make_settings()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creator123", "1"): "MyPost"},
        settings=settings,
        download_text=False,
    )

    # Monkeypatch get_session AFTER thread is created so the FakeSessionCancel
    # can call thread.stop() during iteration.
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSessionCancel(chunks, thread),
    )

    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    # Cancelling is not a failure: nothing completed, nothing to retry, and
    # no half-written artifact left behind.
    assert file_url not in thread.completed_files
    assert file_url not in thread.failed_files

    # Ensure no file artifacts remain under download_folder
    found_files = []
    for root, dirs, files in os.walk(download_folder):
        for f in files:
            found_files.append(os.path.join(root, f))
    assert len(found_files) == 0


def test_download_file_retries_records_failure(monkeypatch, tmp_path):
    """If all download attempts raise RequestException, the file should be recorded as failed."""
    download_folder = str(tmp_path / "downloads")
    other_files_dir = str(tmp_path / "other")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/1.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    settings = make_settings()

    # Monkeypatch get_session to return a session that always errors
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: AlwaysFailingSession(),
    )

    thread = CreatorDownloadThread(
        service="kemono",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Run the async download_file coroutine; it should exhaust retries and record a failure
    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    assert file_url in thread.failed_files
    # Ensure no completed files were recorded
    assert file_url not in thread.completed_files


def test_run_returns_immediately_when_stopped(tmp_path):
    """Calling stop() before run() should cause run() to exit without performing work."""
    download_folder = str(tmp_path / "downloads2")
    other_files_dir = str(tmp_path / "other2")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/2.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "2"}

    settings = make_settings()

    thread = CreatorDownloadThread(
        service="kemono",
        creator_id="creator456",
        download_folder=download_folder,
        selected_posts=["2"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Stop before running; run() should return quickly and not create folders or files
    thread.stop()
    thread.run()

    # No files should be marked completed or failed
    assert not thread.completed_files
    assert not thread.failed_files


def test_creator_download_thread_run_loop(monkeypatch, tmp_path):
    class DummySettings:
        file_download_max_retries = 1
        settings_tab = None
        simultaneous_downloads = 1

    file_url = "https://kemono.cr/files/a.jpg"
    thread = cd.CreatorDownloadThread(
        service="fanbox",
        creator_id="123",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        settings=DummySettings(),
        max_concurrent=1,
    )

    # Prevent network calls in fetch_creator_and_post_info
    thread.fetch_creator_and_post_info = lambda: None

    # Fake async worker that consumes one queue item and returns
    async def fake_worker(self, queue, folder, total_files):
        file_index, file_url, page_number = await queue.get()
        queue.task_done()

    # Bind the coroutine to the instance
    thread.download_worker = MethodType(fake_worker, thread)

    # Replace finished signal to capture emission
    finished = RecordingSignal()
    thread.finished = finished

    # Run the thread's run() synchronously
    thread.run()

    assert finished.emitted is True


def _make_thread_for_runloop(tmp_path):
    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)
    t = cd.CreatorDownloadThread(
        service="kemono",
        creator_id="1",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[],
        files_to_posts_map={},
        console=SimpleNamespace(),
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={("kemono", "1", "1"): "Title"},
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )
    # Stub signals so emit calls don't fail
    t.log = SimpleNamespace(emit=lambda *a, **k: None)
    t.file_progress = SimpleNamespace(emit=lambda *a, **k: None)
    t.file_completed = SimpleNamespace(emit=lambda *a, **k: None)
    t.post_completed = SimpleNamespace(emit=lambda *a, **k: None)
    t.finished = SimpleNamespace(emit=lambda *a, **k: None)
    return t


def test_download_worker_times_out_and_exits(tmp_path):
    t = _make_thread_for_runloop(tmp_path)

    async def runner():
        q = asyncio.Queue()
        # Start worker
        task = asyncio.create_task(t.download_worker(q, str(tmp_path), 0))
        # Give it a short moment, then stop the thread so it exits after timeout
        await asyncio.sleep(0.2)
        t.is_running = False
        await asyncio.wait_for(task, timeout=2.0)
        assert task.done()

    asyncio.run(runner())


def test_run_no_files_logs_warning(tmp_path):
    t = _make_thread_for_runloop(tmp_path)
    # Keep the test offline and on the branch it names.
    t.fetch_creator_and_post_info = lambda: None
    emitted = []
    t.log = SimpleNamespace(emit=lambda *args, **kwargs: emitted.append(args))
    # Ensure no files to download
    t.files_to_download = []
    # Run should not raise, and must say why it did nothing
    t.run()

    warning = cd.translate(
        "log_warning", cd.translate("no_files_selected_for_download")
    )
    assert any(warning in str(args) for args in emitted)


# ---------------------------------------------------------------------------
# Reactive backoff caps
# ---------------------------------------------------------------------------


class _StatusSession:
    """Session that always fails with an HTTP status attached to the error."""

    def __init__(self, status_code, retry_after=None):
        self._status_code = status_code
        self._retry_after = retry_after

    def get(self, *args, **kwargs):
        headers = (
            {} if self._retry_after is None else {"Retry-After": self._retry_after}
        )
        response = SimpleNamespace(
            status_code=self._status_code, headers=headers, text=""
        )
        raise requests.HTTPError(f"{self._status_code} error", response=response)


def _record_backoff_delays(monkeypatch, tmp_path, session, retries=6):
    """Run one failing download and return the delays it slept for.

    A non-Pawchive URL keeps the request gate out of the measurement.
    """
    file_url = "https://n1.kemono.cr/data/ab/cd/x.png"
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(cd, "get_session", lambda *a, **k: session)

    thread = make_thread(tmp_path, file_url, settings_retries=retries)
    thread.domain_config = {
        "base_url": "https://n1.kemono.cr",
        "api_base": "https://n1.kemono.cr/api",
        "referer": "https://n1.kemono.cr/",
        "file_base_url": "https://n1.kemono.cr",
    }
    thread.generate_filename_and_folder = lambda *a, **k: (str(tmp_path), "x.png")

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))
    return delays, thread


def test_backoff_is_capped_at_ten_seconds(monkeypatch, tmp_path):
    delays, thread = _record_backoff_delays(monkeypatch, tmp_path, _StatusSession(500))

    assert delays, "a failing download must back off between attempts"
    assert max(delays) <= DOWNLOAD_RETRY_MAX_DELAY
    assert thread.files_to_download[0] in thread.failed_files


def test_a_rate_limited_file_keeps_a_five_second_floor(monkeypatch, tmp_path):
    delays, _thread = _record_backoff_delays(monkeypatch, tmp_path, _StatusSession(429))

    assert delays
    # 429 is a rate-limit signal: retrying fast keeps the block alive.
    assert min(delays) >= 5
    assert max(delays) <= DOWNLOAD_RETRY_MAX_DELAY


def test_a_forbidden_file_gives_up_after_three_403s(monkeypatch, tmp_path):
    delays, thread = _record_backoff_delays(
        monkeypatch, tmp_path, _StatusSession(403), retries=10
    )

    # Three attempts and two backoffs: the third 403 ends the file.
    assert len(delays) == 2
    assert thread.rate_limit_hits[403] == 3
    assert thread.files_to_download[0] in thread.failed_files


def test_the_retry_budget_stops_the_sleeping(monkeypatch, tmp_path):
    monkeypatch.setattr(cd, "DOWNLOAD_RETRY_BUDGET_SECONDS", 12.0)

    delays, thread = _record_backoff_delays(
        monkeypatch, tmp_path, _StatusSession(500), retries=10
    )

    # 1 + 2 + 4 = 7 s of retries; the next 8 s wait would pass the 12 s budget.
    assert delays == [1, 2, 4]
    assert thread.files_to_download[0] in thread.failed_files


def test_a_bogus_retry_after_cannot_stall_a_worker(monkeypatch, tmp_path):
    delays, _thread = _record_backoff_delays(
        monkeypatch, tmp_path, _StatusSession(503, retry_after="9999")
    )

    assert delays
    # The server's wait wins, but only up to the shared cap.
    assert max(delays) == RETRY_AFTER_CAP


def test_the_run_summary_reports_the_403_and_429_counts():
    thread = cd.CreatorDownloadThread.__new__(cd.CreatorDownloadThread)
    thread._destroyed = False
    thread.rate_limit_hits = {403: 4, 429: 2}
    logs = []
    thread.log = SimpleNamespace(emit=lambda message, level: logs.append(message))

    thread._log_rate_limit_summary()

    assert len(logs) == 1
    assert "4" in logs[0]
    assert "2" in logs[0]


def test_a_clean_run_logs_no_rate_limit_summary():
    thread = cd.CreatorDownloadThread.__new__(cd.CreatorDownloadThread)
    thread._destroyed = False
    thread.rate_limit_hits = {}
    logs = []
    thread.log = SimpleNamespace(emit=lambda message, level: logs.append(message))

    thread._log_rate_limit_summary()

    assert logs == []


def test_the_run_summary_reports_preparation_rate_limits():
    """Preparation runs before the download thread, so it reports separately.

    Its counts live in download_utils; the summary folds them in and clears
    them, so the next run does not inherit them.
    """
    from kemonodownloader import download_utils as du

    du.note_rate_limit(429)
    du.note_rate_limit(429)
    du.note_rate_limit(403)

    thread = cd.CreatorDownloadThread.__new__(cd.CreatorDownloadThread)
    thread._destroyed = False
    thread.rate_limit_hits = {}
    logs = []
    thread.log = SimpleNamespace(emit=lambda message, level: logs.append(message))

    thread._log_rate_limit_summary()

    assert len(logs) == 1
    assert "Preparing files" in logs[0]
    assert "2" in logs[0]
    assert "1" in logs[0]
    assert du.rate_limit_counts() == {}
