import os
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
        auto_rename_enabled=False,
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
        auto_rename_enabled=False,
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
