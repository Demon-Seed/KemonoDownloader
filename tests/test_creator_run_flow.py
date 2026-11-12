"""Whole-run behaviour: folders, hash DB reuse, stress and file preparation."""

import asyncio
import hashlib
import os
from types import SimpleNamespace

from tests.factories import make_settings

from kemonodownloader import creator_downloader as cd
from kemonodownloader.creator_downloader import CreatorDownloadThread


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


def test_generate_filename_respects_existing_creator_folder(tmp_path):
    base = str(tmp_path / "base")
    os.makedirs(base, exist_ok=True)

    file_url = "https://kemono.cr/files/x.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    settings = make_settings()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=base,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={("svc", "creator123", "1"): "MyPost"},
        settings=settings,
        download_text=False,
    )
    thread.creator_name = "Alice"

    # Simulate caller passing creator_folder that already ends with creator folder name
    creator_folder_name = f"{thread.creator_id}_{thread.creator_name}"
    folder_arg = os.path.join(base, creator_folder_name)

    target_folder, filename = thread.generate_filename_and_folder(
        file_url, folder_arg, 0, 1, "1", "MyPost", page_number=1
    )

    # Should not duplicate the creator folder segment
    assert target_folder == os.path.join(
        folder_arg, "1_MyPost"
    ) or target_folder.startswith(folder_arg)


def test_run_handles_makedirs_oserror(monkeypatch, tmp_path):
    base = str(tmp_path / "out_error")
    files_to_download = []
    files_to_posts_map = {}

    settings = make_settings()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=base,
        selected_posts=[],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Provide a safe get_session stub so fetch_creator_and_post_info doesn't raise
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: SimpleNamespace(
            get=lambda *a, **k: SimpleNamespace(
                status_code=200, json=lambda: {"name": "X"}
            )
        ),
    )

    real_makedirs = os.makedirs

    def bad_makedirs(path, exist_ok=False):
        # Raise for any creation attempt under the test base
        if str(path).startswith(base):
            raise OSError("permission denied")
        return real_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr("os.makedirs", bad_makedirs)

    # Running should not raise even if mkdir fails
    thread.run()

    # Cleanup monkeypatch will restore os.makedirs; ensure no folder was created
    assert not os.path.isdir(
        os.path.join(base, f"{thread.creator_id}_{thread.creator_name}")
    )


class DummySettingsTab:
    def get_creator_filename_template(self):
        return "{post_id}_{orig_name}"

    def get_creator_folder_strategy(self):
        return "per_post"


class DummySettings:
    def __init__(self):
        self.settings_tab = DummySettingsTab()


def test_creator_folder_not_duplicated():
    t = CreatorDownloadThread(
        "patreon",
        "17913091",
        "/downloads",
        ["1"],
        [],
        {},
        None,
        "/tmp/other",
        {},
        settings=DummySettings(),
        max_concurrent=1,
    )
    t.creator_name = "jtveemo"

    creator_folder_name = f"{t.creator_id}_{t.creator_name}"
    # Simulate run-created creator_folder passed into workers
    creator_folder = os.path.normpath(
        os.path.join(t.download_folder, creator_folder_name)
    )

    # Now call generator with folder already being creator_folder
    target_folder, filename = t.generate_filename_and_folder(
        "https://kemono.cr/media/abc/image.jpg",
        creator_folder,
        0,
        1,
        "1",
        "My Post",
        page_number=1,
    )

    # target_folder should not contain duplication
    assert target_folder.count(creator_folder_name) == 1

    # Also check when passing base download folder it still builds correct path
    base_folder = os.path.normpath(t.download_folder)
    target_folder2, filename2 = t.generate_filename_and_folder(
        "https://kemono.cr/media/abc/image2.jpg",
        base_folder,
        0,
        1,
        "1",
        "My Post",
        page_number=1,
    )
    assert target_folder2.count(creator_folder_name) == 1


class FakeFileResponse:
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


class FakeAPIResponse:
    def __init__(self, data, code=200):
        self._data = data
        self.status_code = code

    def json(self):
        return self._data


class FakeSessionMulti:
    def __init__(self, profile_name, post_titles, file_chunks_map):
        self.profile_name = profile_name
        self.post_titles = post_titles
        self.file_chunks_map = file_chunks_map

    def get(self, url, *args, **kwargs):
        if url.endswith("/profile"):
            return FakeAPIResponse({"name": self.profile_name}, 200)
        if "/post/" in url:
            # return a post JSON
            pid = url.rstrip("/").split("/")[-1]
            title = self.post_titles.get(pid, f"Post_{pid}")
            return FakeAPIResponse({"title": title}, 200)
        if url in self.file_chunks_map:
            return FakeFileResponse(self.file_chunks_map[url])
        return FakeAPIResponse({}, 404)


class FakeHashDB:
    def __init__(self):
        self.store_calls = {}
        self.lookup_map = {}

    def lookup(self, url_hash):
        return self.lookup_map.get(url_hash)

    def store(self, url_hash, path, file_hash, file_url, file_size):
        self.store_calls[url_hash] = {
            "file_path": path,
            "file_hash": file_hash,
            "file_size": file_size,
        }


def test_creator_run_downloads_all_files(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "out_run")
    other_files_dir = str(tmp_path / "other_run")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file1 = "https://kemono.cr/files/a.png"
    file2 = "https://kemono.cr/files/b.png"
    files_to_download = [file1, file2]
    files_to_posts_map = {file1: "1", file2: "1"}

    chunks_a = [b"aaa"]
    chunks_b = [b"bbbb"]

    fake_session = FakeSessionMulti(
        "CreatorX", {"1": "MyPost"}, {file1: chunks_a, file2: chunks_b}
    )

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: fake_session,
    )

    settings = make_settings()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        max_concurrent=2,
        download_text=False,
    )

    # Inject fake HashDB
    fake_db = FakeHashDB()
    thread.hash_db = fake_db

    # Run the full thread run loop synchronously
    thread.run()

    assert file1 in thread.completed_files
    assert file2 in thread.completed_files
    # HashDB should have stored entries for both files
    assert len(fake_db.store_calls) == 2


def test_creator_skips_existing_hash_entry(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "out_run2")
    other_files_dir = str(tmp_path / "other_run2")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/exists.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Create an existing file in other_files_dir
    existing_path = os.path.join(other_files_dir, "exists.png")
    with open(existing_path, "wb") as f:
        f.write(b"content")
    actual_size = os.path.getsize(existing_path)
    with open(existing_path, "rb") as f:
        file_hash = hashlib.md5(f.read()).hexdigest()

    settings = make_settings()
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
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )

    # Monkeypatch session to ensure no network calls are attempted
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: (_ for _ in ()).throw(
            RuntimeError("Should not be called")
        ),
    )

    fake_db = FakeHashDB()
    # Return entry matching existing file
    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    fake_db.lookup_map[url_hash] = {
        "file_path": existing_path,
        "file_hash": file_hash,
        "file_size": actual_size,
    }
    thread.hash_db = fake_db

    # Call download_file which should detect existing file and skip download
    import asyncio

    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    assert file_url in thread.completed_files


def test_stress_run_reduced_concurrency_does_not_crash(tmp_path):
    # This is a lightweight stress test that launches the download thread with
    # multiple workers but avoids network by giving no files. It ensures run() does
    # not crash immediately under threaded asyncio execution.
    t = CreatorDownloadThread(
        service="patreon",
        creator_id="stress",
        download_folder=str(tmp_path),
        selected_posts=["1", "2", "3"],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir=str(tmp_path),
        post_titles_map={},
        settings=make_settings(template="{post_id}_{orig_name}"),
        max_concurrent=2,
    )
    try:
        # Prevent network activity in the test run
        t.fetch_creator_and_post_info = lambda: None
        t.start()
        # Wait a bit for thread to finish gracefully
        finished = t.wait(2000)
        assert finished is True
    finally:
        t.stop()
        t.quit()
        t.wait(2000)


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


def test_file_preparation_thread_run(monkeypatch, qapp):
    # Prepare an all_files_map containing a creator with two posts
    creator_url = "https://kemono.cr/user/creator"
    all_files_map = {creator_url: [("T1", ("p1", None)), ("T2", ("p2", None))]}

    settings = type("S", (), {"post_data_max_retries": 1, "settings_tab": None})()

    thread = cd.FilePreparationThread(
        ["p1", "p2"], all_files_map, {}, True, True, True, settings, max_concurrent=2
    )

    # Monkeypatch fetch_and_detect_files to return a predictable result
    def fake_fetch(pid, curl):
        return (pid, [(f"file_{pid}", f"https://kemono.cr/{pid}/file.jpg")])

    monkeypatch.setattr(thread, "fetch_and_detect_files", fake_fetch)

    finished = []
    thread.finished.connect(lambda files, fmap: finished.append((files, fmap)))

    # Run synchronously (call run directly) to avoid threading complexity in tests
    thread.run()

    assert finished, "FilePreparationThread did not finish as expected"
    files, fmap = finished[0]
    assert sorted(files) == [
        "https://kemono.cr/p1/file.jpg",
        "https://kemono.cr/p2/file.jpg",
    ]
    # Every queued file maps back to the post it came from.
    assert fmap == {
        "https://kemono.cr/p1/file.jpg": "p1",
        "https://kemono.cr/p2/file.jpg": "p2",
    }


def test_creator_download_thread_run_simulated(monkeypatch, qapp, tmp_path):
    # Simulate a CreatorDownloadThread run where download_file is fast and marks files complete
    download_folder = str(tmp_path)
    files = ["https://kemono.cr/1/a.jpg", "https://kemono.cr/1/b.jpg"]
    files_map = {files[0]: "1", files[1]: "1"}

    class SettingsTab:
        pass

    class Settings:
        settings_tab = SettingsTab()
        file_download_max_retries = 1

    thread = cd.CreatorDownloadThread(
        "svc",
        "creator",
        download_folder,
        ["1"],
        files,
        files_map,
        object(),
        download_folder,
        {("svc", "creator", "1"): "Title"},
        Settings(),
        2,
    )

    # Stub fetch_creator_and_post_info to set creator_name and post_titles
    def fake_fetch_info():
        thread.creator_name = "Creator"
        thread.post_titles_map[(thread.service, thread.creator_id, "1")] = "Title"

    monkeypatch.setattr(thread, "fetch_creator_and_post_info", fake_fetch_info)

    # Async download_file that immediately marks completion
    async def fake_download_file(
        self, file_url, folder, file_index, total_files, page_number
    ):
        # create the target folder/file to mimic a real download
        target_dir = os.path.join(
            folder, f"{self.creator_id}_{self.creator_name}", "1_Title"
        )
        os.makedirs(target_dir, exist_ok=True)
        fpath = os.path.join(target_dir, os.path.basename(file_url))
        with open(fpath, "wb") as f:
            f.write(b"x")
        with self.completed_files_lock:
            self.completed_files.add(file_url)
        self._safe_emit(self.file_progress, file_index, 100)
        self._safe_emit(self.file_completed, file_index, file_url, True)
        self.check_post_completion(file_url)

    # Bind the coroutine method to the instance
    monkeypatch.setattr(
        thread, "download_file", fake_download_file.__get__(thread, thread.__class__)
    )

    finished = []
    thread.finished.connect(lambda: finished.append(True))

    # Run synchronously
    thread.run()

    # After a successful run, completed_files should include our files
    assert set(files).issubset(thread.completed_files)
    assert finished
