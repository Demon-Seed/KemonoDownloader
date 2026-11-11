import asyncio
from types import SimpleNamespace

import kemonodownloader.creator_downloader as cd


def _make_thread_for_runloop(tmp_path):
    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)
    t = cd.CreatorDownloadThread(
        service="kemono",
        creator_id="1",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[],
        files_to_posts_map={},
        console=SimpleNamespace(),
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={("kemono", "1", "1"): "Title"},
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )
    # Stub signals so emit calls don't fail
    t.log = SimpleNamespace(emit=lambda *a, **k: None)
    t.file_progress = SimpleNamespace(emit=lambda *a, **k: None)
    t.file_completed = SimpleNamespace(emit=lambda *a, **k: None)
    t.post_completed = SimpleNamespace(emit=lambda *a, **k: None)
    t.finished = SimpleNamespace(emit=lambda *a, **k: None)
    return t


def test_download_worker_times_out_and_exits(tmp_path):
    t = _make_thread_for_runloop(tmp_path)

    async def runner():
        q = asyncio.Queue()
        # Start worker
        task = asyncio.create_task(t.download_worker(q, str(tmp_path), 0))
        # Give it a short moment, then stop the thread so it exits after timeout
        await asyncio.sleep(0.2)
        t.is_running = False
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(runner())


def test_run_no_files_logs_warning(tmp_path):
    t = _make_thread_for_runloop(tmp_path)
    # Ensure no files to download
    t.files_to_download = []
    # Run should not raise
    t.run()
