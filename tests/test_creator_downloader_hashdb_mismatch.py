import asyncio
import hashlib
import os
from types import SimpleNamespace

import requests

from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


class FakeSessionAlwaysError:
    def get(self, *args, **kwargs):
        raise requests.RequestException("network failure")


def make_settings(tmp_path):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: None,
        get_creator_folder_strategy=lambda: "per_post",
        get_proxy_settings=lambda: None,
    )
    return ThreadSettings(
        creator_posts_max_attempts=1,
        post_data_max_retries=1,
        file_download_max_retries=2,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def test_hash_db_size_mismatch_triggers_redownload(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "downloads_h")
    other_files_dir = str(tmp_path / "other_h")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/mismatch.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "9"}

    settings = make_settings(tmp_path)

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
        auto_rename_enabled=False,
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

    asyncio.run(thread.download_file(file_url, download_folder, 0, total_files=1))

    # Because download failed after retries, it should be recorded as failed
    assert file_url in thread.failed_files
