import asyncio
import hashlib
from types import SimpleNamespace

import pytest
import requests

from kemonodownloader import creator_downloader as cd
from kemonodownloader import download_utils as du


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


def test_progress_is_reported_only_when_the_percentage_moves(monkeypatch, tmp_path):
    """One file must not emit one GUI event per read.

    The loop used to emit ``file_progress`` for every 8 KiB chunk, which
    queued tens of thousands of cross-thread signals for a large file and is
    what made the window stutter.
    """
    payload = b"y" * (300 * 1024)
    file_url = "https://n1.kemono.cr/data/ab/cd/chunky.jpg"

    class ChunkyResponse:
        status_code = 200

        def __init__(self):
            self.headers = {"content-length": str(len(payload))}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            for start in range(0, len(payload), 1024):
                yield payload[start : start + 1024]

        def close(self):
            return None

    class ChunkySession:
        def get(self, url, headers=None, **kwargs):
            return ChunkyResponse()

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: ChunkySession())

    thread = make_stream_thread(tmp_path, file_url)
    thread.generate_filename_and_folder = lambda *a, **k: (str(tmp_path), "chunky.jpg")
    thread.hash_db = SimpleNamespace(lookup=lambda h: None, store=lambda *a, **k: None)
    progress = []
    thread.file_progress = SimpleNamespace(
        emit=lambda index, percent: progress.append(percent)
    )

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    assert progress, "a completed download must report progress"
    assert progress[-1] == 100
    assert len(progress) <= 101, f"{len(progress)} progress events for one file"
    # The reported values only ever move forward.
    assert progress == sorted(progress)
    assert (tmp_path / "chunky.jpg").read_bytes() == payload


# ---------------------------------------------------------------------------
# Direct media-server URLs
# ---------------------------------------------------------------------------


class TestDirectDownloadUrl:
    CONFIG = {"domain": "pawchive.pw", "base_url": "https://pawchive.pw"}

    def test_builds_the_media_server_url(self):
        assert (
            cd.direct_download_url(
                "https://n1.pawchive.pw", "/data/aa/bb/x.png", "x.png", self.CONFIG
            )
            == "https://n1.pawchive.pw/data/aa/bb/x.png?f=x.png"
        )

    def test_adds_the_data_prefix(self):
        assert (
            cd.direct_download_url(
                "https://n1.pawchive.pw", "aa/bb/x.png", "x.png", self.CONFIG
            )
            == "https://n1.pawchive.pw/data/aa/bb/x.png?f=x.png"
        )

    def test_omits_the_query_without_a_name(self):
        assert (
            cd.direct_download_url(
                "https://n1.pawchive.pw", "/data/aa/x.png", "", self.CONFIG
            )
            == "https://n1.pawchive.pw/data/aa/x.png"
        )

    @pytest.mark.parametrize(
        "server",
        [
            None,
            "",
            "http://n1.pawchive.pw",
            "https://evil.example",
            "https://n1.pawchive.pw/some/path",
            "https://n1.pawchive.pw:8443",
            "https://pawchive.pw.evil.example",
        ],
    )
    def test_rejects_untrusted_servers(self, server):
        assert (
            cd.direct_download_url(server, "/data/x.png", "x.png", self.CONFIG) is None
        )

    def test_rejects_a_missing_path(self):
        assert (
            cd.direct_download_url("https://n1.pawchive.pw", "", "x.png", self.CONFIG)
            is None
        )


def test_download_requests_the_remembered_media_server(monkeypatch, tmp_path):
    """A remembered media server is asked directly, with its own origin."""
    payload = b"direct"
    file_url = "https://file.pawchive.pw/data/ab/cd/x.png?f=x.png"
    direct_url = "https://n1.pawchive.pw/data/ab/cd/x.png?f=x.png"
    du.remember_direct_url(file_url, direct_url)
    seen = []

    class Session:
        def get(self, url, headers=None, **kwargs):
            seen.append((url, headers))
            return _Resp(payload)

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Session())

    thread = make_stream_thread(tmp_path, file_url)
    thread.generate_filename_and_folder = lambda *a, **k: (str(tmp_path), "x.png")
    thread.hash_db = SimpleNamespace(lookup=lambda h: None, store=lambda *a, **k: None)

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    # The warm-up hits the media host's root; the file itself comes from it.
    assert seen[-1][0] == direct_url
    assert seen[-1][1]["Referer"] == "https://n1.pawchive.pw/"
    assert (tmp_path / "x.png").read_bytes() == payload


def test_a_missing_file_on_the_media_server_falls_back(monkeypatch, tmp_path):
    """A 404 from the media server must not condemn the file.

    Media servers are rotated: the API can still name one that no longer has
    the file while ``file.<domain>`` serves it, so the usual address gets its
    own attempt without spending a retry on it.
    """
    payload = b"fallback"
    file_url = "https://file.pawchive.pw/data/ab/cd/x.png?f=x.png"
    direct_url = "https://n1.pawchive.pw/data/ab/cd/x.png?f=x.png"
    du.remember_direct_url(file_url, direct_url)
    seen = []

    class NotFound:
        status_code = 404
        headers = {}
        text = ""

        def raise_for_status(self):
            raise requests.HTTPError("404 Client Error", response=self)

        def close(self):
            return None

    class Session:
        def get(self, url, headers=None, **kwargs):
            seen.append(url)
            if url == direct_url:
                return NotFound()
            return _Resp(payload)

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Session())

    # One retry only: the fallback must not need a second one.
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
        "domain": "pawchive.pw",
        "base_url": "https://pawchive.pw",
        "api_base": "https://pawchive.pw/api/v1",
        "referer": "https://pawchive.pw/",
        "file_base_url": "https://file.pawchive.pw",
    }
    thread.generate_filename_and_folder = lambda *a, **k: (str(tmp_path), "x.png")
    thread.hash_db = SimpleNamespace(lookup=lambda h: None, store=lambda *a, **k: None)

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    # The media server was asked first, the usual address second and served it.
    assert seen[-1] == file_url
    assert (tmp_path / "x.png").read_bytes() == payload
    assert file_url in thread.completed_files
    assert file_url not in thread.failed_files


def test_a_failing_media_server_does_not_spend_a_retry(monkeypatch, tmp_path):
    """A timeout or 5xx from the media server is free: the usual URL is next.

    Media servers are rotated, so what one of them answers says nothing about
    ``file.<domain>``.  Charging that failure to the file would fail a download
    the usual address would have served, which a single retry setting cannot
    afford, and it is reported as a debug line so the rotation is not silent.
    """
    payload = b"fallback"
    file_url = "https://file.pawchive.pw/data/ab/cd/y.png?f=y.png"
    direct_url = "https://n1.pawchive.pw/data/ab/cd/y.png?f=y.png"
    du.remember_direct_url(file_url, direct_url)
    seen = []

    class ServerError:
        status_code = 500
        headers = {}
        text = ""

        def raise_for_status(self):
            raise requests.HTTPError("500 Server Error", response=self)

        def close(self):
            return None

    class Session:
        def get(self, url, headers=None, **kwargs):
            seen.append(url)
            if url == direct_url:
                return ServerError()
            return _Resp(payload)

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Session())

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
        "domain": "pawchive.pw",
        "base_url": "https://pawchive.pw",
        "api_base": "https://pawchive.pw/api/v1",
        "referer": "https://pawchive.pw/",
        "file_base_url": "https://file.pawchive.pw",
    }
    thread.generate_filename_and_folder = lambda *a, **k: (str(tmp_path), "y.png")
    thread.hash_db = SimpleNamespace(lookup=lambda h: None, store=lambda *a, **k: None)
    logs = []
    thread.log.connect(lambda message, level: logs.append((message, level)))

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    assert seen[-1] == file_url
    assert (tmp_path / "y.png").read_bytes() == payload
    assert file_url in thread.completed_files
    assert file_url not in thread.failed_files
    assert any("using the usual address" in message for message, _ in logs)
    assert ("DEBUG" in [level for _, level in logs]) is True
