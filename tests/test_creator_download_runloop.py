import asyncio
import os
import types
from types import SimpleNamespace

from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


def test_fetch_creator_and_post_info_profile_failure_logs(monkeypatch, tmp_path):
    service = "svc"
    creator_id = "42"
    post_id = "1"
    file_url = "https://kemono.cr/files/1.jpg"

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    console = SimpleNamespace()  # not used in this test
    post_titles_map = {}

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

    class FakeProfileResp:
        status_code = 500

    class FakePostResp:
        status_code = 200

        def json(self):
            return {"title": "Some Title"}

    class FakeSession:
        def get(self, url, *a, **k):
            if "/profile" in url:
                return FakeProfileResp()
            return FakePostResp()

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session", lambda *a, **k: FakeSession()
    )

    logs = []
    thread._safe_emit = lambda signal, *args: logs.append(args)

    thread.fetch_creator_and_post_info()

    assert thread.creator_name == "Unknown_Creator"
    # Post title should have been populated
    key = (service, creator_id, post_id)
    assert key in thread.post_titles_map
    assert any(
        "Failed to fetch" in str(m) or "Error" in str(m) or "warning" in str(m).lower()
        for tup in logs
        for m in tup
    )


def test_download_worker_exception_is_logged(monkeypatch, tmp_path):
    service = "svc"
    creator_id = "42"
    post_id = "1"
    file_url = "https://kemono.cr/files/1.jpg"

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    console = SimpleNamespace()
    thread = CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path / "dl"),
        [post_id],
        [file_url],
        {file_url: post_id},
        console,
        str(tmp_path / "other"),
        {},
        False,
        settings,
        settings.simultaneous_downloads,
    )

    async def _raise(self, url, folder, idx, total, page_number):
        raise Exception("boom")

    # Bind the coroutine as a method
    thread.download_file = types.MethodType(_raise, thread)

    logs = []
    thread._safe_emit = lambda signal, *args: logs.append(args)

    async def run_worker():
        q = asyncio.Queue()
        q.put_nowait((0, file_url, 1))
        # Run the worker as a background task so we can stop it after work is done.
        worker_task = asyncio.create_task(thread.download_worker(q, str(tmp_path), 1))
        # Wait for the queued item to be processed
        await asyncio.wait_for(q.join(), timeout=2)
        # Signal the worker to exit and await its completion
        thread.is_running = False
        await asyncio.wait_for(worker_task, timeout=2)

    asyncio.run(run_worker())

    # Ensure an error was logged for the worker
    assert any(
        "error in download worker" in str(m).lower() or "boom" in str(m).lower()
        for tup in logs
        for m in tup
    )


def test_run_handles_creator_folder_oserror(monkeypatch, tmp_path):
    service = "svc"
    creator_id = "42"
    post_id = "1"
    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    console = SimpleNamespace()

    thread = CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path / "dl"),
        [post_id],
        [],
        {},
        console,
        str(tmp_path / "other"),
        {},
        False,
        settings,
        settings.simultaneous_downloads,
    )

    # Avoid network calls
    thread.fetch_creator_and_post_info = lambda: None
    thread.creator_name = "Bad:Name"

    orig_makedirs = os.makedirs

    def fake_makedirs(path, exist_ok=False):
        if path.endswith(f"{creator_id}_{thread.creator_name}"):
            raise OSError("cannot create")
        return orig_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr(os, "makedirs", fake_makedirs)

    logs = []
    thread._safe_emit = lambda signal, *args: logs.append(args)

    # Execute run (synchronous call)
    thread.run()

    assert any(
        "failed to create creator folder" in str(m).lower()
        or "cannot create" in str(m).lower()
        for tup in logs
        for m in tup
    )


def test_check_post_completion_emits(monkeypatch, tmp_path):
    service = "svc"
    creator_id = "42"
    post_id = "1"
    file1 = "f1"
    file2 = "f2"

    settings = ThreadSettings(1, 1, 1, 1, 1, settings_tab=SimpleNamespace())
    console = SimpleNamespace()
    thread = CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path / "dl"),
        [post_id],
        [file1, file2],
        {file1: post_id, file2: post_id},
        console,
        str(tmp_path / "other"),
        {},
        False,
        settings,
        settings.simultaneous_downloads,
    )

    thread.post_files_map = {post_id: [file1, file2]}
    thread.completed_files = {file1, file2}

    captured = []
    thread._safe_emit = lambda signal, *args: captured.append((signal, args))

    thread.check_post_completion(file1)

    # Should have emitted post_completed with post_id
    assert any(post_id in args for _, args in captured)
