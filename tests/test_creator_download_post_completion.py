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
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def test_check_post_completion_triggers_post_completed(tmp_path):
    download_folder = str(tmp_path / "pc_d")
    other_files_dir = str(tmp_path / "pc_o")

    u1 = "https://kemono.cr/files/a.png"
    u2 = "https://kemono.cr/files/b.png"
    files = [u1, u2]
    files_map = {u1: "post1", u2: "post1"}

    settings = make_settings()

    thread = CreatorDownloadThread(
        service="svc",
        creator_id="c1",
        download_folder=download_folder,
        selected_posts=["post1"],
        files_to_download=files,
        files_to_posts_map=files_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    called = []

    def on_post_completed(post_id):
        called.append(post_id)

    thread.post_completed.connect(on_post_completed)

    # Simulate both files completed
    thread.completed_files.add(u1)
    thread.completed_files.add(u2)

    # Trigger check for one file; should emit post_completed
    thread.check_post_completion(u1)

    assert called == ["post1"]
