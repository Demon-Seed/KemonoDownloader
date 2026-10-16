import os
from types import SimpleNamespace

import kemonodownloader.creator_downloader as cd


def _make_thread(tmp_path, settings, auto_rename=False):
    other_dir = str(tmp_path / "other")
    os.makedirs(other_dir, exist_ok=True)
    t = cd.CreatorDownloadThread(
        service="kemono",
        creator_id="42",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[],
        files_to_posts_map={},
        console=SimpleNamespace(),
        other_files_dir=other_dir,
        post_titles_map={("kemono", "42", "1"): "Title 1"},
        auto_rename_enabled=auto_rename,
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )
    t.creator_name = "Creator"
    return t


def test_generate_filename_single_folder(tmp_path):
    settings = SimpleNamespace(
        settings_tab=SimpleNamespace(
            get_creator_filename_template=lambda: "{post_id}_{orig_name}_{file_index}",
            get_creator_folder_strategy=lambda: "single_folder",
        )
    )

    t = _make_thread(tmp_path, settings)
    file_url = "https://kemono.cr/files/abc.jpg"
    target_folder, filename = t.generate_filename_and_folder(
        file_url, str(tmp_path / "base"), 0, 1, "1", "Title 1", page_number=1
    )

    assert os.path.basename(target_folder) == "42_Creator"
    assert filename.endswith(".jpg")
    assert filename.startswith("1_abc_1")


def test_generate_filename_by_file_type(tmp_path):
    settings = SimpleNamespace(
        settings_tab=SimpleNamespace(
            get_creator_filename_template=lambda: "{post_id}_{orig_name}",
            get_creator_folder_strategy=lambda: "by_file_type",
        )
    )

    t = _make_thread(tmp_path, settings)
    file_url = "https://kemono.cr/files/f.jpg"
    target_folder, filename = t.generate_filename_and_folder(
        file_url, str(tmp_path / "base"), 0, 1, "1", "Title 1", page_number=1
    )

    assert os.path.basename(target_folder) == "jpg"
    assert filename == "1_f.jpg"


def test_auto_rename_prefix_increments(tmp_path):
    settings = SimpleNamespace(
        settings_tab=SimpleNamespace(
            get_creator_filename_template=lambda: "{orig_name}",
            get_creator_folder_strategy=lambda: "per_post",
        )
    )

    t = _make_thread(tmp_path, settings, auto_rename=True)
    file_url = "https://kemono.cr/files/pic.png"
    _, filename1 = t.generate_filename_and_folder(
        file_url, str(tmp_path / "base"), 0, 2, "1", "Title 1", page_number=1
    )
    _, filename2 = t.generate_filename_and_folder(
        file_url, str(tmp_path / "base"), 1, 2, "1", "Title 1", page_number=2
    )

    assert filename1.startswith("1_")
    assert filename2.startswith("2_")


def test_template_error_fallback(tmp_path):
    # Template uses unknown placeholder -> should fallback
    settings = SimpleNamespace(
        settings_tab=SimpleNamespace(
            get_creator_filename_template=lambda: "{does_not_exist}",
            get_creator_folder_strategy=lambda: "per_post",
        )
    )

    t = _make_thread(tmp_path, settings)
    file_url = "https://kemono.cr/files/x.txt"
    _, filename = t.generate_filename_and_folder(
        file_url, str(tmp_path / "base"), 0, 1, "1", "Title 1", page_number=1
    )

    assert filename.startswith("1_")


def test_creator_folder_already_in_path(tmp_path):
    settings = SimpleNamespace(
        settings_tab=SimpleNamespace(
            get_creator_filename_template=lambda: "{post_id}_{orig_name}",
            get_creator_folder_strategy=lambda: "single_folder",
        )
    )

    t = _make_thread(tmp_path, settings)
    base = str(tmp_path / "base" / "42_Creator")
    os.makedirs(base, exist_ok=True)
    target_folder, _ = t.generate_filename_and_folder(
        "https://kemono.cr/files/a.jpg", base, 0, 1, "1", "Title 1", page_number=1
    )

    # Should not append creator folder again
    assert os.path.normpath(target_folder) == os.path.normpath(base)
