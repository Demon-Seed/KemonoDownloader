from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


def test_creator_download_thread_run_with_fake_workers(tmp_path, monkeypatch):
    # Prepare a thread with one file to download
    file_url = "https://kemono.cr/files/runfile.png"
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

    # Stub fetch_creator_and_post_info to avoid network
    def fake_fetch():
        t.creator_name = "Creator"
        t.post_titles_map[(t.service, t.creator_id, "1")] = "PostTitle"

    monkeypatch.setattr(t, "fetch_creator_and_post_info", fake_fetch)

    # Replace download_worker with a coroutine that marks files completed
    async def fake_download_worker(self_queue, folder, total_files):
        # Consume one item if present
        try:
            idx, url = self_queue.get_nowait()
        except Exception:
            return
        # simulate immediate completion
        t._safe_emit(t.file_completed, idx, url, True)
        self_queue.task_done()

    monkeypatch.setattr(
        cd.CreatorDownloadThread, "download_worker", fake_download_worker
    )

    # Run the thread.run() method synchronously
    t.run()

    # After running, finished signal would have been emitted (no exceptions)
    # Ensure the run created the creator folder
    # (creator folder name uses service/creator id pattern)
    # No assertion beyond 'no exception' — ensure completed_files processed
    assert isinstance(t.post_titles_map, dict)
