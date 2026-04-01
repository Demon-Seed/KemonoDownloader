import os
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd
from kemonodownloader.creator_downloader import (
    CreatorDownloadThread,
    FilePreparationThread,
    sanitize_filename,
)


class FakeSettingsTab:
    def __init__(self, template=None, strategy="per_post"):
        self._template = template
        self._strategy = strategy

    def get_creator_filename_template(self):
        return self._template

    def get_creator_folder_strategy(self):
        return self._strategy


def test_sanitize_filename_basic():
    assert sanitize_filename("") == "unnamed"
    assert sanitize_filename(None) == "unnamed"
    s = ' bad<>:"/\\|?* name... '
    out = sanitize_filename(s, max_length=50)
    assert "<" not in out and ">" not in out and ":" not in out and "/" not in out
    assert " " not in out
    assert not out.startswith(".")


def _make_thread(tmp_path, template=None, strategy="per_post", auto_rename=False):
    files = ["https://kemono.cr/files/abc.png"]
    files_map = {files[0]: "1"}
    post_titles = {("kemono", "123", "1"): "PostTitle"}
    settings = SimpleNamespace(settings_tab=FakeSettingsTab(template, strategy))
    t = CreatorDownloadThread(
        "kemono",
        "123",
        str(tmp_path),
        ["1"],
        files,
        files_map,
        None,
        str(tmp_path),
        post_titles,
        auto_rename,
        settings,
    )
    t.creator_name = "CreatorName"
    return t


def test_generate_filename_default(tmp_path):
    t = _make_thread(tmp_path)
    target_folder, final_filename = t.generate_filename_and_folder(
        t.files_to_download[0], str(tmp_path), 0, 1, "1", "PostTitle"
    )
    assert final_filename.endswith(".png")
    assert "1_" in final_filename or "PostTitle" in target_folder


def test_generate_filename_auto_rename(tmp_path):
    t = _make_thread(tmp_path, auto_rename=True)
    t.auto_rename_enabled = True
    f1 = t.generate_filename_and_folder(
        t.files_to_download[0], str(tmp_path), 0, 2, "1", "PostTitle"
    )[1]
    f2 = t.generate_filename_and_folder(
        t.files_to_download[0], str(tmp_path), 1, 2, "1", "PostTitle"
    )[1]
    assert f1 != f2
    assert f1.startswith("1_") and f2.startswith("2_")


def test_generate_filename_custom_template(tmp_path):
    template = "{creator_id}_{post_id}_{orig_name}_{file_index}_{total_files}"
    t = _make_thread(tmp_path, template=template)
    folder, fname = t.generate_filename_and_folder(
        t.files_to_download[0], str(tmp_path), 0, 3, "1", "PostTitle"
    )
    assert "123_1" in fname


def test_generate_filename_malformed_template_fallback(tmp_path):
    t = _make_thread(tmp_path, template="{nonexistent_key}")
    folder, fname = t.generate_filename_and_folder(
        t.files_to_download[0], str(tmp_path), 0, 1, "1", "PostTitle"
    )
    assert fname.startswith("1_")  # fallback to safe default


def test_get_desc_folder_for_post(tmp_path):
    t = _make_thread(tmp_path)
    t.settings = SimpleNamespace(settings_tab=FakeSettingsTab(None, "single_folder"))
    desc = t.get_desc_folder_for_post(str(tmp_path), "1", "PostTitle")
    assert desc == os.path.normpath(str(tmp_path))
    t.settings.settings_tab = FakeSettingsTab(None, "by_file_type")
    desc2 = t.get_desc_folder_for_post(str(tmp_path), "1", "PostTitle")
    assert os.path.basename(desc2) in ("txt", "txt")


def test_detect_files_main_and_attachments_and_content():
    # Setup a FilePreparationThread and a sample post with main/attachments/content
    settings = SimpleNamespace(settings_tab=None)

    class C:
        def __init__(self, checked=True):
            self._checked = checked

        def isChecked(self):
            return self._checked

    ext_checks = {".jpg": C(True), ".png": C(True), ".zip": C(True)}
    post = {
        "file": {"path": "/media/main.jpg", "name": "main.jpg"},
        "attachments": [
            {"path": "/att/file.zip", "name": "file.zip"},
            {"path": "/att/pic.png"},
        ],
        "content": '<p>Hi<img src="/images/img1.png"></p>',
    }
    fpt = FilePreparationThread([1], {}, ext_checks, True, True, True, settings)
    domain_config = {"base_url": "https://kemono.cr"}
    files = fpt.detect_files(post, [".jpg", ".png", ".zip"], domain_config)
    names = [n for n, u in files]
    assert any("main" in n for n in names)
    assert any(n.endswith(".zip") or n.endswith(".png") for n in names)


def test_generate_filename_strategies_and_creator_folder(tmp_path):
    # single_folder strategy
    t = _make_thread(tmp_path, template=None, strategy="single_folder")
    t.creator_name = "CreatorName"
    target, fname = t.generate_filename_and_folder(
        t.files_to_download[0], str(tmp_path), 0, 1, "1", "PostTitle"
    )
    assert os.path.normpath(target).endswith(
        os.path.normpath(str(tmp_path / f"{t.creator_id}_{t.creator_name}"))
    ) or os.path.normpath(target) == os.path.normpath(
        str(tmp_path / f"{t.creator_id}_{t.creator_name}")
    )

    # by_file_type strategy
    t2 = _make_thread(tmp_path, template=None, strategy="by_file_type")
    t2.creator_name = "CreatorName"
    target2, fname2 = t2.generate_filename_and_folder(
        t2.files_to_download[0], str(tmp_path), 0, 1, "1", "PostTitle"
    )
    assert os.path.basename(target2) in ("png", "other")

    # folder already contains creator folder
    creator_folder = str(tmp_path / f"{t.creator_id}_{t.creator_name}")
    os.makedirs(creator_folder, exist_ok=True)
    t3 = _make_thread(tmp_path)
    t3.creator_name = "CreatorName"
    target3, fname3 = t3.generate_filename_and_folder(
        t3.files_to_download[0], creator_folder, 0, 1, "1", "PostTitle"
    )
    assert os.path.normpath(target3).startswith(os.path.normpath(creator_folder))


def test_fetch_creator_and_post_info_success(monkeypatch, tmp_path):
    # Prepare fake responses for profile and post
    profile_resp = SimpleNamespace(status_code=200, json=lambda: {"name": "My Creator"})
    post_resp = SimpleNamespace(
        status_code=200, json=lambda: {"title": "My Post", "content": "<p>x</p>"}
    )

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            if url.endswith("/profile"):
                return profile_resp
            if "/post/" in url:
                return post_resp
            return SimpleNamespace(status_code=404, json=lambda: {})

    monkeypatch.setattr(cd, "get_session", lambda settings_tab: FakeSession())

    settings = SimpleNamespace(
        settings_tab=None, file_download_max_retries=1, post_data_max_retries=1
    )
    file_url = "https://kemono.cr/files/abc.png"
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
    # Provide domain config used to build URLs
    t.domain_config = {"api_base": "https://api.test", "referer": "https://kemono.cr"}
    # Ensure post_titles_map is empty so fetch occurs
    t.post_titles_map = {}
    t.fetch_creator_and_post_info()
    assert t.creator_name is not None
    # Post title should be stored in post_titles_map
    key = (t.service, t.creator_id, "1")
    assert key in t.post_titles_map
