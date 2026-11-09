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
        False,
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
        False,
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
