from types import MethodType

from kemonodownloader import creator_downloader as cd


class DummySignal:
    def __init__(self):
        self.emitted = False
        self.last_args = None

    def emit(self, *args):
        self.emitted = True
        self.last_args = args


def test_creator_download_thread_run_loop(monkeypatch, tmp_path):
    class DummySettings:
        file_download_max_retries = 1
        settings_tab = None
        simultaneous_downloads = 1

    file_url = "https://kemono.cr/files/a.jpg"
    thread = cd.CreatorDownloadThread(
        service="fanbox",
        creator_id="123",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        auto_rename_enabled=False,
        settings=DummySettings(),
        max_concurrent=1,
    )

    # Prevent network calls in fetch_creator_and_post_info
    thread.fetch_creator_and_post_info = lambda: None

    # Fake async worker that consumes one queue item and returns
    async def fake_worker(self, queue, folder, total_files):
        file_index, file_url, page_number = await queue.get()
        queue.task_done()

    # Bind the coroutine to the instance
    thread.download_worker = MethodType(fake_worker, thread)

    # Replace finished signal to capture emission
    finished = DummySignal()
    thread.finished = finished

    # Run the thread's run() synchronously
    thread.run()

    assert finished.emitted is True
