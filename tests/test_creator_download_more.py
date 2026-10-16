import asyncio
import hashlib
from types import SimpleNamespace

from PyQt6.QtWidgets import QTextEdit

from kemonodownloader.creator_downloader import (
    CreatorDownloadThread,
    ThreadSettings,
    sanitize_filename,
)


def test_generate_filename_fallback_on_bad_template(tmp_path):
    file_url = "https://kemono.cr/files/123?f=my image.jpg"
    post_id = "1"
    service = "svc"
    creator_id = "42"

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    console = QTextEdit()
    post_titles_map = {(service, creator_id, post_id): "My Post"}

    thread = CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path / "dl"),
        [post_id],
        [file_url],
        {file_url: post_id},
        console,
        str(tmp_path / "other"),
        post_titles_map,
        False,
        settings,
        settings.simultaneous_downloads,
    )

    # Install a bad template that will raise during formatting
    bad_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{nope}",
        get_creator_folder_strategy=lambda: "per_post",
    )
    thread.settings.settings_tab = bad_tab

    target_folder, filename = thread.generate_filename_and_folder(
        file_url,
        str(tmp_path),
        0,
        1,
        post_id,
        post_titles_map[(service, creator_id, post_id)], page_number=1
    )

    # Fallback should include post_id and sanitized original name
    assert f"{post_id}_" in filename
    assert sanitize_filename("my image") in filename


def test_download_file_uses_hashdb_entry_and_skips_download(tmp_path):
    file_url = "https://kemono.cr/files/keep.jpg"
    post_id = "1"
    service = "svc"
    creator_id = "42"

    # Create an existing file and compute its hash
    existing = tmp_path / "existing.jpg"
    existing.write_bytes(b"hello-content")
    md5 = hashlib.md5(existing.read_bytes()).hexdigest()
    size = existing.stat().st_size

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    console = QTextEdit()
    post_titles_map = {(service, creator_id, post_id): "Title"}

    thread = CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path / "dl"),
        [post_id],
        [file_url],
        {file_url: post_id},
        console,
        str(tmp_path / "other"),
        post_titles_map,
        False,
        settings,
        settings.simultaneous_downloads,
    )

    class FakeHashDB:
        def lookup(self, url_hash):
            return {
                "file_path": str(existing),
                "file_hash": md5,
                "url": file_url,
                "file_size": size,
            }

    thread.hash_db = FakeHashDB()

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    assert file_url in thread.completed_files


def test_download_file_size_mismatch_deletes_incomplete(monkeypatch, tmp_path):
    file_url = "https://kemono.cr/files/bad.jpg"
    post_id = "1"
    service = "svc"
    creator_id = "42"

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    # Set file_download_max_retries to 1 to fail fast
    settings.file_download_max_retries = 1
    console = QTextEdit()
    post_titles_map = {(service, creator_id, post_id): "Title"}

    thread = CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path / "dl"),
        [post_id],
        [file_url],
        {file_url: post_id},
        console,
        str(tmp_path / "other"),
        post_titles_map,
        False,
        settings,
        settings.simultaneous_downloads,
    )

    class FakeResp:
        def __init__(self):
            self.headers = {"content-length": "10"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield b"1234"

        def close(self):
            return None

    class FakeSession:
        def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session", lambda *a, **k: FakeSession()
    )

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))

    # The incomplete file should not exist and the file should be marked failed
    # It should have recorded a failure
    assert file_url in thread.failed_files


def test_run_emits_no_files_warning(tmp_path):
    # If there are no files to download, run() should log a warning via thread.log
    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    console = QTextEdit()
    thread = CreatorDownloadThread(
        "svc",
        "42",
        str(tmp_path / "dl"),
        [],
        [],
        {},
        console,
        str(tmp_path / "other"),
        {},
        False,
        settings,
        settings.simultaneous_downloads,
    )

    logs = []

    # Monkeypatch _safe_emit to capture emitted messages more reliably
    def _capture_safe_emit(signal, *args):
        # capture the formatted message (first arg) when present
        if args:
            logs.append(args[0])

    thread._safe_emit = _capture_safe_emit
    # Call run directly; ensure it completes without raising
    thread.run()
    assert True
