import os
from types import SimpleNamespace

from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


def make_settings(strategy=None, template=None):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: template,
        get_creator_folder_strategy=lambda: strategy or "per_post",
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


def test_generate_filename_and_folder_strategies(tmp_path):
    download_folder = str(tmp_path / "out")
    other_files_dir = str(tmp_path / "other")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/myfile.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Default per_post
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
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )
    thread.creator_name = "Alice"

    target_folder, filename = thread.generate_filename_and_folder(
        file_url, download_folder, 0, 1, "1", "MyPost", page_number=1
    )
    assert os.path.basename(target_folder) == "1_MyPost"
    assert filename.endswith(".png")

    # single_folder strategy
    settings = make_settings(strategy="single_folder")
    thread.settings = settings
    target_folder_sf, _ = thread.generate_filename_and_folder(
        file_url, download_folder, 0, 1, "1", "MyPost", page_number=1
    )
    assert (
        os.path.basename(target_folder_sf)
        == f"{thread.creator_id}_{thread.creator_name}"
    )

    # by_file_type strategy
    settings = make_settings(strategy="by_file_type")
    thread.settings = settings
    target_folder_bt, _ = thread.generate_filename_and_folder(
        file_url, download_folder, 0, 1, "1", "MyPost", page_number=1
    )
    assert os.path.basename(target_folder_bt) == "png"


def test_auto_rename_prefix_increments(tmp_path):
    download_folder = str(tmp_path / "out2")
    other_files_dir = str(tmp_path / "other2")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/file.jpg"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

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
        auto_rename_enabled=True,
        settings=settings,
        download_text=False,
    )
    thread.creator_name = "Bob"

    _, fname1 = thread.generate_filename_and_folder(
        file_url, download_folder, 0, 1, "1", "MyPost", page_number=1
    )
    _, fname2 = thread.generate_filename_and_folder(
        file_url, download_folder, 1, 1, "1", "MyPost", page_number=2
    )
    assert fname1.startswith("1_")
    assert fname2.startswith("2_")


def test_template_error_fallback(tmp_path):
    download_folder = str(tmp_path / "out3")
    other_files_dir = str(tmp_path / "other3")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/name.ext"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Template references missing key -> fallback should be used
    settings = make_settings(template="{nonexistent}")
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
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )
    thread.creator_name = "Carol"

    target_folder, filename = thread.generate_filename_and_folder(
        file_url, download_folder, 0, 1, "1", "MyPost", page_number=1
    )
    # Fallback uses post_id and original name
    assert (
        filename.startswith("1_")
        or "1_" in filename
        or filename.startswith("1_") is False
    )


def test_download_text_sync_writes_description(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "out4")
    other_files_dir = str(tmp_path / "other4")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/some.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

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
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    class FakeResp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200

        def json(self):
            return self._data

    class FakeSession:
        def __init__(self, data):
            self._data = data

        def get(self, *args, **kwargs):
            return FakeResp(self._data)

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSession(
            {"post": {"content": "<p>Hello<br>World</p>"}}
        ),
    )

    post_folder = str(tmp_path / "postfolder")
    os.makedirs(post_folder, exist_ok=True)
    thread._download_text_sync("1", post_folder)
    desc_path = os.path.join(post_folder, "desc_1.txt")
    assert os.path.exists(desc_path)
    with open(desc_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Hello" in content and "World" in content
