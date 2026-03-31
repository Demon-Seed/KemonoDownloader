import asyncio
from types import SimpleNamespace

import requests

from kemonodownloader import creator_downloader as cd


class FakeResp:
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


def make_thread(tmp_path, file_url, other_dir=None, settings_retries=2):
    service = "kemono"
    creator_id = "9"
    other = other_dir or str(tmp_path / "other")
    settings = SimpleNamespace(
        settings_tab=None, file_download_max_retries=settings_retries
    )
    t = cd.CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        None,
        other,
        {},
        False,
        settings,
        max_concurrent=1,
        download_text=False,
    )
    return t


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

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1))
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

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1))
    assert file_url in t.completed_files
