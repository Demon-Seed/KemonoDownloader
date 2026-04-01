import asyncio
import hashlib
import os
from types import SimpleNamespace

from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


class FakeResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.status_code = 200
        self.headers = {"content-length": str(sum(len(c) for c in chunks))}

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c

    def raise_for_status(self):
        return None

    def close(self):
        return None


class FakeSession:
    def __init__(self, chunks):
        self._chunks = chunks

    def get(self, *args, **kwargs):
        return FakeResponse(self._chunks)


def make_settings(tmp_path):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: None,
        get_creator_folder_strategy=lambda: "per_post",
        get_proxy_settings=lambda: None,
    )
    return ThreadSettings(
        creator_posts_max_attempts=1,
        post_data_max_retries=1,
        file_download_max_retries=1,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


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
        lambda settings_tab=None: FakeSession(chunks),
    )

    settings = make_settings(tmp_path)

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
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    # Run the async download
    asyncio.run(thread.download_file(file_url, download_folder, 0, total_files=1))

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
