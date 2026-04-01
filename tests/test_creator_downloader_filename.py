import os
from types import SimpleNamespace

from kemonodownloader.creator_downloader import (
    CreatorDownloadThread,
    ThreadSettings,
    sanitize_filename,
)


def make_settings_with_strategy(strategy, template=None):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: template,
        get_creator_folder_strategy=lambda: strategy,
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


def test_generate_filename_and_folder_autorename_and_strategies(tmp_path):
    download_folder = str(tmp_path / "downloads")
    other_files_dir = str(tmp_path / "other")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/origname.png?f=origname.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Per-post strategy with auto-rename
    settings = make_settings_with_strategy("per_post", template=None)
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creator123", "1"): "My Post"},
        auto_rename_enabled=True,
        settings=settings,
        download_text=False,
    )

    target_folder, filename = thread.generate_filename_and_folder(
        file_url, download_folder, 0, total_files=1, post_id="1", post_title="My Post"
    )

    # Expect auto-rename prefix '1_' and default template '{post_id}_{orig_name}'
    assert filename.endswith("origname.png")
    assert filename.startswith("1_1_")

    # Expect folder ends with sanitized post title
    expected_post_folder = f"1_{sanitize_filename('My Post')}"
    assert os.path.basename(target_folder) == expected_post_folder

    # Single-folder strategy places desc in creator folder
    settings2 = make_settings_with_strategy("single_folder")
    thread2 = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creator123", "1"): "My Post"},
        auto_rename_enabled=False,
        settings=settings2,
        download_text=False,
    )

    tfolder2, fname2 = thread2.generate_filename_and_folder(
        file_url, download_folder, 0, total_files=1, post_id="1", post_title="My Post"
    )
    # creator folder should be the immediate child of download_folder
    creator_folder_name = os.path.basename(tfolder2)
    assert creator_folder_name in (
        "creator123_creator123",
        "creator123_Unknown_Creator",
    )


def test_template_fallback_on_error(tmp_path):
    download_folder = str(tmp_path / "downloads3")
    other_files_dir = str(tmp_path / "other3")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/origname.png?f=origname.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "42"}

    # Provide a broken template that will raise during formatting
    settings = make_settings_with_strategy(
        "per_post", template="{nonexistent}_{post_id}"
    )
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creatorX",
        download_folder=download_folder,
        selected_posts=["42"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creatorX", "42"): "Title"},
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    tfolder, fname = thread.generate_filename_and_folder(
        file_url, download_folder, 0, total_files=1, post_id="42", post_title="Title"
    )

    # Fallback should produce filename like '{post_id}_{orig_name}.ext'
    assert fname.endswith("origname.png")
    assert "42_" in fname
