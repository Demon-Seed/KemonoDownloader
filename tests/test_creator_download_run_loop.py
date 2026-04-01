import types
from types import SimpleNamespace

from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


def make_settings():
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
        simultaneous_downloads=2,
        settings_tab=settings_tab,
    )


def test_creator_download_run_processes_queue(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "run_d")
    other_files_dir = str(tmp_path / "run_o")

    files = [f"https://kemono.cr/files/{i}.png" for i in range(3)]

    settings = make_settings()

    thread = CreatorDownloadThread(
        service="svc",
        creator_id="c",
        download_folder=download_folder,
        selected_posts=[str(i) for i in range(1, 4)],
        files_to_download=files,
        files_to_posts_map={u: str(i) for i, u in enumerate(files, start=1)},
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    # Prevent network calls in fetch_creator_and_post_info
    thread.fetch_creator_and_post_info = lambda: None

    async def fake_download_file(file_url, folder, file_index, total_files):
        # mark as completed
        thread.completed_files.add(file_url)

    # Bind coroutine to instance
    thread.download_file = types.MethodType(
        lambda self, *a, **k: fake_download_file(*a, **k), thread
    )

    # Run the thread.run() which should process the queue and finish
    thread.run()

    # All files should have been processed (added to completed_files)
    for u in files:
        assert u in thread.completed_files
