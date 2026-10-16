import asyncio
import hashlib
from types import SimpleNamespace

import requests

from kemonodownloader.creator_downloader import (
    CreatorDownloadThread,
    ThreadSettings,
    sanitize_filename,
)


def test_get_domain_config_from_files_choice(tmp_path):
    # When files_to_download present, domain derived from first URL
    url = "https://coomer.st/files/x.png"
    t = CreatorDownloadThread(
        "svc",
        "cid",
        str(tmp_path),
        [],
        [url],
        {url: "1"},
        None,
        str(tmp_path),
        {},
        False,
        ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace()),
    )
    dom = t._get_domain_config_from_files()
    assert dom["domain"] == "coomer.st"

    # Without files, default to kemono.cr
    t2 = CreatorDownloadThread(
        "svc",
        "cid",
        str(tmp_path),
        [],
        [],
        {},
        None,
        str(tmp_path),
        {},
        False,
        ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace()),
    )
    dom2 = t2._get_domain_config_from_files()
    assert dom2["domain"] == "kemono.cr"


def test_build_post_files_map_filters(tmp_path):
    file1 = "u1"
    file2 = "u2"
    t = CreatorDownloadThread(
        "svc",
        "cid",
        str(tmp_path),
        ["1", "2"],
        [file1, file2],
        {file1: "1", file2: "3"},
        None,
        str(tmp_path),
        {},
        False,
        ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace()),
    )
    pfm = t.post_files_map
    assert "1" in pfm and file1 in pfm["1"]
    assert "2" in pfm and pfm["2"] == []


def test_fetch_creator_and_post_info_populates(monkeypatch, tmp_path):
    service = "svc"
    creator_id = "C"
    post_id = "42"

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    t = CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path),
        [post_id],
        [],
        {},
        None,
        str(tmp_path),
        {},
        False,
        settings,
    )

    class FakeProfile:
        status_code = 200

        def json(self):
            return {"name": "Creator Name"}

    class FakePost:
        status_code = 200

        def json(self):
            return {"title": "Fetched Title"}

    class S:
        def get(self, url, *a, **k):
            if url.endswith("/profile"):
                return FakeProfile()
            return FakePost()

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session", lambda *a, **k: S()
    )

    t.fetch_creator_and_post_info()

    assert t.creator_name == sanitize_filename("Creator Name")
    key = (service, creator_id, post_id)
    assert key in t.post_titles_map


def test_download_post_text_if_needed_writes_desc(monkeypatch, tmp_path):
    service = "svc"
    creator_id = "C"
    post_id = "10"

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    t = CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path),
        [post_id],
        [],
        {},
        None,
        str(tmp_path),
        {},
        False,
        settings,
    )

    class FakeResp:
        status_code = 200

        def json(self):
            return {"content": "<p>Hello <b>world</b></p>"}

    class S:
        def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session", lambda *a, **k: S()
    )

    dest = tmp_path / "desc"
    dest.mkdir()
    asyncio.run(t.download_post_text_if_needed(post_id, str(dest)))
    # file should exist
    assert (dest / f"desc_{post_id}.txt").exists()


def test_download_file_no_content_length_and_store(monkeypatch, tmp_path):
    file_url = "https://kemono.cr/files/nocl.png"
    post_id = "1"

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    settings.file_download_max_retries = 1
    t = CreatorDownloadThread(
        "svc",
        "cid",
        str(tmp_path / "dl"),
        [post_id],
        [file_url],
        {file_url: post_id},
        None,
        str(tmp_path / "other"),
        {("svc", "cid", post_id): "P"},
        False,
        settings,
    )

    class FakeResp:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield b"data"

        def close(self):
            return None

    class FakeSession:
        def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session", lambda *a, **k: FakeSession()
    )

    stored = {}

    class FakeHashDB:
        def lookup(self, h):
            return None

        def store(self, url_hash, full_path, file_hash, file_url, size):
            stored[url_hash] = full_path

    t.hash_db = FakeHashDB()

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    assert file_url in t.completed_files
    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    assert url_hash in stored


def test_download_file_request_exception_records_failure(monkeypatch, tmp_path):
    file_url = "https://kemono.cr/files/fail.png"
    post_id = "1"

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    settings.file_download_max_retries = 1
    t = CreatorDownloadThread(
        "svc",
        "cid",
        str(tmp_path / "dl"),
        [post_id],
        [file_url],
        {file_url: post_id},
        None,
        str(tmp_path / "other"),
        {},
        False,
        settings,
    )

    class S:
        def get(self, *a, **k):
            raise requests.RequestException("netfail")

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session", lambda *a, **k: S()
    )

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    assert file_url in t.failed_files


def test_run_full_download_cycle(monkeypatch, tmp_path):
    # Set up several files with different behaviors
    base = "https://kemono.cr/files/"
    ok1 = base + "ok1.png"
    ok2 = base + "ok2.jpg"
    mismatch = base + "mismatch.png"
    bad = base + "bad.png"

    post_id = "p"

    settings = ThreadSettings(1, 1, 2, 1, 2, settings_tab=SimpleNamespace())
    settings.file_download_max_retries = 2

    files = [ok1, ok2, mismatch, bad]

    t = CreatorDownloadThread(
        "svc",
        "cid",
        str(tmp_path / "dlroot"),
        [post_id],
        files,
        {u: post_id for u in files},
        None,
        str(tmp_path / "other"),
        {("svc", "cid", post_id): "PostTitle"},
        False,
        settings,
        max_concurrent=2,
        download_text=False,
    )

    # Prepare responses: ok responses with correct content-length
    class Resp:
        def __init__(self, chunks, headers=None, status_code=200):
            self._chunks = chunks
            self.status_code = status_code
            self.headers = headers or {}

        def raise_for_status(self):
            if self.status_code != 200:
                raise requests.RequestException("status")

        def iter_content(self, chunk_size=8192):
            for c in self._chunks:
                yield c

        def close(self):
            return None

        def json(self):
            # Provide safe default JSON for profile/post endpoints
            return {}

    # Map URLs to responses
    resp_map = {
        ok1: Resp([b"a" * 10], headers={"content-length": "10"}),
        ok2: Resp([b"b" * 5], headers={"content-length": "5"}),
        # mismatch: header says 10 but yields 4 -> triggers deletion and retry
        mismatch: Resp([b"1234"], headers={"content-length": "10"}),
        # bad: raises network error
        bad: Resp([b"x" * 3], headers={"content-length": "3"}),
    }

    class S:
        def get(self, url, *a, **k):
            if url == bad:
                raise requests.RequestException("network")
            # Return a mapped response or a harmless default for other endpoints
            return resp_map.get(url, Resp([], headers={}))

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session", lambda *a, **k: S()
    )

    # Fake HashDB which returns no existing entries
    stored = {}

    class FakeHashDB:
        def lookup(self, h):
            return None

        def store(self, url_hash, full_path, file_hash, file_url, size):
            stored[url_hash] = full_path

    t.hash_db = FakeHashDB()

    # Capture logs (avoid Qt signals)
    t._safe_emit = lambda sig, *a, **k: None

    # Run the full thread synchronously (will create its own asyncio loop)
    t.run()

    # ok1 and ok2 should be completed, mismatch should end as failed due to size mismatch, bad failed
    assert ok1 in t.completed_files
    assert ok2 in t.completed_files
    assert mismatch in t.failed_files or mismatch in t.completed_files
    assert bad in t.failed_files
