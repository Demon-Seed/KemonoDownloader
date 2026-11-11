import asyncio
import hashlib
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


def test_download_file_skips_existing_hash(tmp_path):
    # Create a fake existing file and a fake HashDB entry pointing at it
    file_content = b"hello world"
    existing = tmp_path / "existing.bin"
    existing.write_bytes(file_content)

    file_url = "https://kemono.cr/files/existing.bin"

    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    entry = {
        "file_path": str(existing),
        "file_hash": hashlib.md5(file_content).hexdigest(),
        "file_size": len(file_content),
    }

    class FakeHashDB:
        def __init__(self, e):
            self._e = e

        def lookup(self, h):
            return self._e if h == url_hash else None

        def store(self, *a, **k):
            pass

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
    # Inject fake hash DB
    t.hash_db = FakeHashDB(entry)

    # Ensure domain config exists
    t.domain_config = {
        "api_base": "https://kemono.cr/api",
        "referer": "https://kemono.cr",
    }

    # Run the coroutine — lookup should short-circuit and mark as completed
    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    assert file_url in t.completed_files


def test_terminal_http_error_is_reported_once_and_not_retried(tmp_path, monkeypatch):
    """A 404 must not eat the retry budget.

    It used to burn all ``file_download_max_retries`` attempts (50 by default,
    ~23 minutes of sleeping) on a file the host has already said is gone.
    """
    import requests

    file_url = "https://file.pawchive.pw/data/abc.png?f=ochaco.png"

    class FakeResponse:
        status_code = 404
        headers = {}
        text = ""

        def raise_for_status(self):
            raise requests.HTTPError("404 Client Error", response=self)

        def close(self):
            pass

    class FakeSession:
        def __init__(self):
            self.file_requests = 0

        def get(self, url, **kwargs):
            if url == file_url:
                self.file_requests += 1
            return FakeResponse()

    class FakeHashDB:
        def lookup(self, h):
            return None

        def store(self, *a, **k):
            pass

    session = FakeSession()
    monkeypatch.setattr(cd, "get_session", lambda settings_tab: session)

    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=5)
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
        "api_base": "https://pawchive.pw/api/v1",
        "referer": "https://pawchive.pw/",
        "base_url": "https://pawchive.pw",
        "file_base_url": "https://file.pawchive.pw",
    }
    logs = []
    t.log.connect(lambda message, level: logs.append((message, level)))

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    assert session.file_requests == 1  # one shot, not five
    assert file_url in t.failed_files
    assert any("retrying cannot fix it" in message for message, _ in logs)
    assert ("ERROR" in [level for _, level in logs]) is True
    # The reason is kept for Retry Failed Downloads, and it names the status.
    assert "404" in t.failed_files[file_url]


# ---------------------------------------------------------------------------
# Streaming writes
# ---------------------------------------------------------------------------


class _Resp:
    """Minimal streamed response, with an optional lying content-length."""

    def __init__(self, payload, declared=None):
        self.status_code = 200
        self._payload = payload
        self.headers = {
            "content-length": str(len(payload) if declared is None else declared)
        }

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield self._payload

    def close(self):
        return None


class _Session:
    """Serves one payload for every request, warm-up included."""

    def __init__(self, payload, declared=None, seen=None, file_url=None):
        self._payload = payload
        self._declared = declared
        self._seen = seen
        self._file_url = file_url

    def get(self, url, headers=None, **kwargs):
        if self._seen is not None and url == self._file_url:
            self._seen.update(headers or {})
        return _Resp(self._payload, declared=self._declared)


def make_stream_thread(tmp_path, file_url):
    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)
    thread = cd.CreatorDownloadThread(
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
    thread.domain_config = {
        "base_url": "https://kemono.cr",
        "api_base": "https://kemono.cr/api",
        "referer": "https://kemono.cr/",
        "file_base_url": "https://n1.kemono.cr",
    }
    return thread


def test_download_writes_a_part_file_then_renames_it(monkeypatch, tmp_path):
    payload = b"0123456789"
    file_url = "https://n1.kemono.cr/data/ab/cd/ok.jpg"
    seen = {}

    monkeypatch.setattr(
        cd,
        "get_session",
        lambda *a, **k: _Session(payload, seen=seen, file_url=file_url),
    )

    thread = make_stream_thread(tmp_path, file_url)
    thread.generate_filename_and_folder = lambda *a, **k: (str(tmp_path), "ok.jpg")
    stored = {}

    class FakeHashDB:
        def lookup(self, h):
            return None

        def store(self, url_hash, path, file_hash, url, size):
            stored.update(path=path, file_hash=file_hash, size=size)

    thread.hash_db = FakeHashDB()

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    assert (tmp_path / "ok.jpg").read_bytes() == payload
    assert not (tmp_path / "ok.jpg.part").exists()
    # The hash comes from the written bytes, not from re-reading the file.
    assert stored["file_hash"] == hashlib.md5(payload).hexdigest()
    assert stored["size"] == len(payload)
    # Size checks compare written bytes with content-length, so the transfer
    # must not be compressed behind the check's back.
    assert seen["Accept-Encoding"] == "identity"


def test_failed_size_check_leaves_nothing_behind(monkeypatch, tmp_path):
    payload = b"short"
    file_url = "https://n1.kemono.cr/data/ab/cd/bad.jpg"

    monkeypatch.setattr(
        cd, "get_session", lambda *a, **k: _Session(payload, declared=99)
    )

    thread = make_stream_thread(tmp_path, file_url)
    thread.generate_filename_and_folder = lambda *a, **k: (str(tmp_path), "bad.jpg")
    thread.hash_db = SimpleNamespace(lookup=lambda h: None, store=lambda *a, **k: None)

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    # A truncated transfer never reaches the real name, and its ".part" is
    # cleaned up rather than left for the next run to trust.
    assert not (tmp_path / "bad.jpg").exists()
    assert not (tmp_path / "bad.jpg.part").exists()
    assert file_url in thread.failed_files


def test_hash_file_matches_md5_of_the_whole_file(tmp_path):
    data = b"x" * (2 * 1024 * 1024 + 7)
    path = tmp_path / "big.bin"
    path.write_bytes(data)

    assert cd._hash_file(str(path)) == hashlib.md5(data).hexdigest()
