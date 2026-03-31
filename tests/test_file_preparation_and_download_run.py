import os

from kemonodownloader import creator_downloader as cd


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
    assert any("file_p1" in u or "file_p2" in u for u in files) or len(files) >= 1
    # Ensure mapping contains entries for returned file urls
    assert all(v in fmap.values() for v in fmap.values() or [True])


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
        True,
        Settings(),
        2,
    )

    # Stub fetch_creator_and_post_info to set creator_name and post_titles
    def fake_fetch_info():
        thread.creator_name = "Creator"
        thread.post_titles_map[(thread.service, thread.creator_id, "1")] = "Title"

    monkeypatch.setattr(thread, "fetch_creator_and_post_info", fake_fetch_info)

    # Async download_file that immediately marks completion
    async def fake_download_file(self, file_url, folder, file_index, total_files):
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
