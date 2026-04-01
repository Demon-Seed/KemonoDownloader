import asyncio
import hashlib
import os
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


class FakeResponse:
    def __init__(self, chunks, headers=None):
        self._chunks = list(chunks)
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
        False,
        settings,
    )
    t.hash_db = FakeHashDB()
    t.domain_config = {
        "api_base": "https://kemono.cr/api",
        "referer": "https://kemono.cr",
    }

    dest_folder = tmp_path / "out"
    dest_folder.mkdir()

    asyncio.run(t.download_file(file_url, str(dest_folder), 0, 1))

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

    ft = FakeThread({"u": "err"})
    tab.cleanup_thread(ft, [])
    assert "u" in tab.failed_files

    # Also test when thread is in active_threads
    ft2 = FakeThread({"v": "err2"})
    tab.active_threads.append(ft2)
    tab.cleanup_thread(ft2, [])
    assert "v" in tab.failed_files
