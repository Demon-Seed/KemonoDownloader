import asyncio
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
        file_download_max_retries=3,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def test_download_file_retries_records_failure(monkeypatch, tmp_path):
    """If all download attempts raise RequestException, the file should be recorded as failed."""
    download_folder = str(tmp_path / "downloads")
    other_files_dir = str(tmp_path / "other")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/1.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    settings = make_settings(tmp_path)

    # Monkeypatch get_session to return a session that always errors
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSessionAlwaysError(),
    )

    thread = CreatorDownloadThread(
        service="kemono",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    # Run the async download_file coroutine; it should exhaust retries and record a failure
    asyncio.run(thread.download_file(file_url, download_folder, 0, total_files=1))

    assert file_url in thread.failed_files
    # Ensure no completed files were recorded
    assert file_url not in thread.completed_files


def test_run_returns_immediately_when_stopped(tmp_path):
    """Calling stop() before run() should cause run() to exit without performing work."""
    download_folder = str(tmp_path / "downloads2")
    other_files_dir = str(tmp_path / "other2")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/2.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "2"}

    settings = make_settings(tmp_path)

    thread = CreatorDownloadThread(
        service="kemono",
        creator_id="creator456",
        download_folder=download_folder,
        selected_posts=["2"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    # Stop before running; run() should return quickly and not create folders or files
    thread.stop()
    thread.run()

    # No files should be marked completed or failed
    assert not thread.completed_files
    assert not thread.failed_files
