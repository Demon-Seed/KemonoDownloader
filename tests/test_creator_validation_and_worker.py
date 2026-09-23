import asyncio
from types import SimpleNamespace

from kemonodownloader.creator_downloader import (
    CreatorDownloadThread,
    ThreadSettings,
)


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
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def test_download_worker_invokes_download_file(monkeypatch):
    settings = make_settings()
    td = CreatorDownloadThread(
        service="svc",
        creator_id="creator",
        download_folder="/tmp",
        selected_posts=[],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir="/tmp",
        post_titles_map={},
        auto_rename_enabled=False,
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )

    called = {}

    async def fake_download(file_url, folder, idx, total, page_number):
        called["url"] = file_url
        called["page_number"] = page_number

    # Monkeypatch the async download_file
    td.download_file = fake_download
    # download_worker loops while is_running, which defaults to False in __init__.
    td.is_running = True

    async def run_worker():
        q = asyncio.Queue()
        # download_worker unpacks (file_index, file_url, page_number).
        await q.put((0, "https://kemono.cr/files/x.png", None))
        # Run the worker in the background and wait for the queue to be processed.
        worker_task = asyncio.create_task(td.download_worker(q, "/tmp", total_files=1))
        await q.join()
        # Signal the worker to stop and cancel the task to break out of wait_for
        td.is_running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_worker())
    assert called.get("url") == "https://kemono.cr/files/x.png"
    assert called.get("page_number") is None


def test_safe_emit_ignores_when_destroyed():
    settings = make_settings()
    td = CreatorDownloadThread(
        service="svc",
        creator_id="creator",
        download_folder="/tmp",
        selected_posts=[],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir="/tmp",
        post_titles_map={},
        auto_rename_enabled=False,
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )

    td._destroyed = True
    td.emitted = False

    class S:
        def emit(self, *a, **k):
            td.emitted = True

    td._safe_emit(S(), 1, 2, 3)
    assert td.emitted is False
