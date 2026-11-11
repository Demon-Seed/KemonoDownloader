import os
from types import SimpleNamespace

from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


def make_settings(template=None, strategy="per_post", shared=None):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: template,
        get_creator_filename_template_shared=lambda: shared,
        get_creator_folder_strategy=lambda: strategy,
    )
    return ThreadSettings(
        creator_posts_max_attempts=1,
        post_data_max_retries=1,
        file_download_max_retries=1,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def make_thread(file_url, tmp_path, settings):
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=str(tmp_path),
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={("svc", "creator123", "1"): "My Post"},
        settings=settings,
        download_text=False,
    )
    # Replace signal emitters to avoid PyQt interactions
    thread.log = SimpleNamespace(emit=lambda *a, **k: None)
    thread.creator_name = "Alice"
    return thread


def test_generate_filename_default(tmp_path):
    file_url = "https://kemono.cr/files/image.png"
    settings = make_settings()
    thread = make_thread(file_url, tmp_path, settings)

    target_folder, filename = thread.generate_filename_and_folder(
        file_url, str(tmp_path), 0, 1, "1", "My Post", page_number=1
    )

    expected_folder = os.path.join(str(tmp_path), "creator123_Alice", "1_My_Post")
    assert target_folder == expected_folder
    # Post-folder default: {file_number}_{post_id}_{orig_name}
    assert filename == "1_1_image.png"


def test_generate_filename_shared_template_is_used_for_shared_folders(tmp_path):
    file_url = "https://kemono.cr/files/image.png"
    settings = make_settings(strategy="single_folder", shared="{post_id}_{orig_name}")
    thread = make_thread(file_url, tmp_path, settings)

    _target_folder, filename = thread.generate_filename_and_folder(
        file_url, str(tmp_path), 0, 1, "1", "My Post", page_number=1
    )

    # The shared template wins in a pooled folder, not the post-folder one.
    assert filename == "1_image.png"


def test_generate_filename_single_folder_strategy(tmp_path):
    file_url = "https://kemono.cr/files/image.png"
    settings = make_settings(strategy="single_folder")
    thread = make_thread(file_url, tmp_path, settings)

    target_folder, filename = thread.generate_filename_and_folder(
        file_url, str(tmp_path), 0, 1, "1", "My Post", page_number=1
    )

    expected_folder = os.path.join(str(tmp_path), "creator123_Alice")
    assert target_folder == expected_folder
    assert filename == "1_1_image.png"


def test_generate_filename_bad_template_falls_back(tmp_path):
    file_url = "https://kemono.cr/files/image.png"
    # Template references nonexistent keys and will raise during format
    settings = make_settings(template="{nonexistent}")
    thread = make_thread(file_url, tmp_path, settings)

    _target_folder, filename = thread.generate_filename_and_folder(
        file_url, str(tmp_path), 0, 1, "1", "My Post", page_number=1
    )

    # Should fallback to default naming
    assert filename == "1_image.png"


def test_get_desc_folder_variants(tmp_path):
    file_url = "https://kemono.cr/files/image.png"

    # by_file_type -> txt subfolder
    settings = make_settings(strategy="by_file_type")
    thread = make_thread(file_url, tmp_path, settings)
    creator_folder = os.path.join(str(tmp_path), "creator123_Alice")
    got = thread.get_desc_folder_for_post(creator_folder, "1", "My Post")
    assert got == os.path.join(creator_folder, "txt")

    # single_folder -> return creator folder itself
    settings = make_settings(strategy="single_folder")
    thread = make_thread(file_url, tmp_path, settings)
    got = thread.get_desc_folder_for_post(creator_folder, "1", "My Post")
    assert got == creator_folder

    # per_post -> creator_folder/post_id_post_title
    settings = make_settings(strategy="per_post")
    thread = make_thread(file_url, tmp_path, settings)
    got = thread.get_desc_folder_for_post(creator_folder, "1", "My Post")
    assert got == os.path.join(creator_folder, "1_My_Post")
