"""Single-file download behaviour: names, sizes, streaming and the hash DB."""

import asyncio
import hashlib
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests
from tests.factories import (
    SessionReturning,
    StreamingResponse,
    make_settings,
    make_thread,
)

from kemonodownloader import creator_downloader as cd
from kemonodownloader.creator_downloader import CreatorDownloadThread


def test_download_file_short_circuit_with_hash(tmp_path):
    service = "kemono"
    creator_id = "8"
    other_dir = str(tmp_path / "hdb")
    settings = SimpleNamespace(settings_tab=None)

    file_url = "https://kemono.cr/media/file.bin"
    thread = cd.CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        None,
        other_dir,
        {},
        settings,
        max_concurrent=1,
        download_text=False,
    )

    # create an existing file and register it in the hash DB
    existing = tmp_path / "existing.bin"
    existing.write_bytes(b"hello world")
    file_hash = hashlib.md5(existing.read_bytes()).hexdigest()
    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    thread.hash_db.store(
        url_hash, str(existing), file_hash, file_url, existing.stat().st_size
    )

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))
    assert file_url in thread.completed_files


class FakeResp:
    status_code = 200

    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c

    def close(self):
        return None


def test_download_size_mismatch_marks_failed(tmp_path, monkeypatch):
    file_url = "https://kemono.cr/media/big.bin"
    t = make_thread(tmp_path, file_url, settings_retries=1)

    # Response reports 100 bytes but yields only 50
    chunks = [b"a" * 50]
    headers = {"content-length": "100"}

    class FS:
        def get(self, *a, **k):
            return FakeResp(chunks, headers=headers)

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: FS())

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1, page_number=1))
    assert file_url in t.failed_files
    assert file_url not in t.completed_files


def test_download_retries_on_request_exception_then_succeeds(tmp_path, monkeypatch):
    file_url = "https://kemono.cr/media/retry.bin"
    t = make_thread(tmp_path, file_url, settings_retries=3)

    # First two calls raise RequestException, third returns a valid response
    class FS2:
        def __init__(self):
            self.calls = 0

        def get(self, *a, **k):
            self.calls += 1
            if self.calls < 3:
                raise requests.RequestException("network")
            # return 20 bytes in two chunks
            return FakeResp([b"x" * 10, b"x" * 10], headers={"content-length": "20"})

    fs = FS2()
    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: fs)

    # Speed up sleeps during retry
    async def nosleep(_):
        return None

    monkeypatch.setattr(cd.asyncio, "sleep", nosleep)

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1, page_number=1))
    assert file_url in t.completed_files


def make_thread_for_download(tmp_path, settings=None):
    dl = tmp_path / "dl"
    other = tmp_path / "other"
    dl.mkdir(exist_ok=True)
    other.mkdir(exist_ok=True)
    t = cd.CreatorDownloadThread(
        "svc",
        "42",
        str(dl),
        ["p1"],
        [],
        {},
        MagicMock(),
        str(other),
        {("svc", "42", "p1"): "Title"},
        settings,
        max_concurrent=1,
    )
    return t


def test_download_file_makedirs_failure(tmp_path, monkeypatch):
    settings = SimpleNamespace(file_download_max_retries=1, settings_tab=None)
    t = make_thread_for_download(tmp_path, settings=settings)
    file_url = "https://kemono.cr/media/1.png?f=file.png"
    t.files_to_download = [file_url]
    t.files_to_posts_map = {file_url: "p1"}
    t.post_files_map = {"p1": [file_url]}

    def bad_makedirs(*args, **kwargs):
        raise OSError("no space")

    monkeypatch.setattr(cd.os, "makedirs", bad_makedirs)

    asyncio.run(t.download_file(file_url, str(tmp_path / "dl"), 0, 1, page_number=1))

    assert file_url in t.failed_files


def test_download_file_requests_exception(monkeypatch, tmp_path):
    settings = SimpleNamespace(file_download_max_retries=1, settings_tab=None)
    t = make_thread_for_download(tmp_path, settings=settings)
    file_url = "https://kemono.cr/media/2.png?f=file2.png"
    t.files_to_download = [file_url]
    t.files_to_posts_map = {file_url: "p1"}
    t.post_files_map = {"p1": [file_url]}

    class S:
        def get(self, *a, **k):
            raise requests.RequestException("network")

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    asyncio.run(t.download_file(file_url, str(tmp_path / "dl"), 0, 1, page_number=1))

    assert file_url in t.failed_files


def test_check_post_completion_triggers_post_completed(tmp_path):
    download_folder = str(tmp_path / "pc_d")
    other_files_dir = str(tmp_path / "pc_o")

    u1 = "https://kemono.cr/files/a.png"
    u2 = "https://kemono.cr/files/b.png"
    files = [u1, u2]
    files_map = {u1: "post1", u2: "post1"}

    settings = make_settings()

    thread = CreatorDownloadThread(
        service="svc",
        creator_id="c1",
        download_folder=download_folder,
        selected_posts=["post1"],
        files_to_download=files,
        files_to_posts_map=files_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    called = []

    def on_post_completed(post_id):
        called.append(post_id)

    thread.post_completed.connect(on_post_completed)

    # Simulate both files completed
    thread.completed_files.add(u1)
    thread.completed_files.add(u2)

    # Trigger check for one file; should emit post_completed
    thread.check_post_completion(u1)

    assert called == ["post1"]


def test_download_size_mismatch_deletion_raises(monkeypatch, tmp_path):
    # Prepare a CreatorDownloadThread with minimal config
    file_url = "https://kemono.cr/files/f.jpg"
    download_folder = str(tmp_path / "dl")
    other_dir = str(tmp_path / "other")
    os.makedirs(other_dir, exist_ok=True)

    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)

    thread = cd.CreatorDownloadThread(
        service="kemono",
        creator_id="1",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=SimpleNamespace(),
        other_files_dir=other_dir,
        post_titles_map={},
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )

    # Stub signals to avoid PyQt interactions
    thread.file_progress = SimpleNamespace(emit=lambda *a, **k: None)
    thread.file_completed = SimpleNamespace(emit=lambda *a, **k: None)
    thread.post_completed = SimpleNamespace(emit=lambda *a, **k: None)
    thread.log = SimpleNamespace(emit=lambda *a, **k: None)

    # Force filename generation to a known path
    target_folder = str(tmp_path / "dl")
    os.makedirs(target_folder, exist_ok=True)
    thread.generate_filename_and_folder = lambda *a, **k: (target_folder, "f.jpg")

    # Fake response: reports content-length 10 but only yields 5 bytes
    class Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        @property
        def headers(self):
            return {"content-length": "10"}

        def iter_content(self, chunk_size=8192):
            yield b"12345"

        def close(self):
            return None

    class Sess:
        def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr(cd, "get_session", lambda st=None: Sess())

    # Make os.remove raise OSError when called to hit the deletion-failure branch
    def fake_remove(path):
        raise OSError("cannot delete")

    monkeypatch.setattr(os, "remove", fake_remove)

    # Run the async download
    asyncio.run(
        thread.download_file(file_url, target_folder, 0, total_files=1, page_number=1)
    )

    # The thread should have recorded a failure for this file
    assert file_url in thread.failed_files
    assert (
        "Size mismatch" in thread.failed_files[file_url]
        or "downloaded" in thread.failed_files[file_url]
    )


class FakeResponse:
    def __init__(self, chunks, headers=None):
        self._chunks = list(chunks)
        self.status_code = 200
        self.headers = headers or {
            "content-length": str(sum(len(c) for c in self._chunks))
        }

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c

    def raise_for_status(self):
        return None

    def close(self):
        return None


class FakeSession:
    def __init__(self, response):
        self._response = response

    def get(self, *args, **kwargs):
        return self._response


def test_download_file_success_writes_and_stores(tmp_path, monkeypatch):
    # Prepare fake file content split into chunks
    chunks = [b"hello", b" ", b"world"]
    fake_resp = FakeResponse(chunks)
    fake_session = FakeSession(fake_resp)
    monkeypatch.setattr(cd, "get_session", lambda settings_tab: fake_session)

    stored = {}

    class FakeHashDB:
        def lookup(self, h):
            return None

        def store(self, url_hash, file_path, file_hash, file_url, file_size):
            stored.update(
                {
                    "url_hash": url_hash,
                    "file_path": file_path,
                    "file_hash": file_hash,
                    "file_url": file_url,
                    "file_size": file_size,
                }
            )

    file_url = "https://kemono.cr/files/hi.txt"
    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)
    t = cd.CreatorDownloadThread(
        "service",
        "creator",
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        None,
        str(tmp_path),
        {},
        settings,
    )
    t.hash_db = FakeHashDB()
    t.domain_config = {
        "base_url": "https://kemono.cr",
        "api_base": "https://kemono.cr/api",
        "referer": "https://kemono.cr",
    }

    dest_folder = tmp_path / "out"
    dest_folder.mkdir()

    asyncio.run(t.download_file(file_url, str(dest_folder), 0, 1, 1))

    # File should exist and hash should have been stored
    assert stored
    assert os.path.exists(stored["file_path"]) is True
    # Validate stored file hash matches file contents
    with open(stored["file_path"], "rb") as f:
        data = f.read()
    assert hashlib.md5(data).hexdigest() == stored["file_hash"]


def test_cleanup_thread_transfers_failed_files(tmp_path):
    settings_tab = SimpleNamespace(
        settings_applied=SimpleNamespace(connect=lambda cb: None),
        language_changed=SimpleNamespace(connect=lambda cb: None),
    )
    parent = SimpleNamespace(
        cache_folder=str(tmp_path / "c"),
        other_files_folder=str(tmp_path / "o"),
        download_folder=str(tmp_path / "d"),
        settings_tab=settings_tab,
        tabs=SimpleNamespace(
            count=lambda: 1, currentIndex=lambda: 0, setTabEnabled=lambda i, e: None
        ),
        status_label=SimpleNamespace(setText=lambda s: None),
        animate_button=lambda *a, **k: None,
    )
    tab = cd.CreatorDownloaderTab(parent)

    class FakeThread:
        def __init__(self, failed):
            self.failed_files = failed

        def isRunning(self):
            return False

        def deleteLater(self):
            pass

    # Keep another thread active and files outstanding so cleanup_thread does
    # not reach the "run finished" path, which logs the failures and clears
    # the set (that clearing is by design, not a lost transfer).
    keep_alive = FakeThread(None)
    tab.active_threads = [keep_alive]
    tab.total_files_to_download = 5

    ft = FakeThread({"u": "err"})
    tab.cleanup_thread(ft)
    assert "u" in tab.failed_files

    # Also test when thread is in active_threads
    ft2 = FakeThread({"v": "err2"})
    tab.active_threads.append(ft2)
    tab.cleanup_thread(ft2)
    assert "v" in tab.failed_files


def test_streamed_download_writes_file_and_updates_hashdb(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "dstream")
    other_files_dir = str(tmp_path / "otherstream")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/streamed.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Small content in two chunks
    chunks = [b"abc", b"def"]

    # Monkeypatch get_session to return our fake session
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: SessionReturning(StreamingResponse(chunks)),
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

    # Run the async download
    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    # Confirm the file was marked completed
    assert file_url in thread.completed_files

    # Compute url_hash and check HashDB entry exists and file exists on disk
    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    entry = thread.hash_db.lookup(url_hash)
    assert entry is not None
    assert (
        os.path.exists(entry["file_path"])
        if isinstance(entry, dict)
        else os.path.exists(entry["file_path"])
    )  # defensive
