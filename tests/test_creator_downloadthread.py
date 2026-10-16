import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import kemonodownloader.creator_downloader as cd


def make_thread(tmp_path, settings=None, auto_rename=False, post_titles_map=None):
    dl = tmp_path / "dl"
    other = tmp_path / "other"
    dl.mkdir(exist_ok=True)
    other.mkdir(exist_ok=True)
    if post_titles_map is None:
        post_titles_map = {("svc", "42", "p1"): "Title"}
    t = cd.CreatorDownloadThread(
        "svc",
        "42",
        str(dl),
        ["p1"],
        [],
        {},
        MagicMock(),
        str(other),
        post_titles_map,
        auto_rename,
        settings,
        max_concurrent=1,
    )
    return t


def test_generate_filename_and_folder_default(tmp_path):
    t = make_thread(tmp_path, settings=None, auto_rename=False)
    t.creator_name = "Alice"
    key = (t.service, t.creator_id, "p1")
    t.post_titles_map[key] = "My Post"

    file_url = "https://kemono.cr/media/abc.png?f=orig.png"
    folder, filename = t.generate_filename_and_folder(
        file_url, str(tmp_path / "dl"), 0, 1, "p1", "My Post", page_number=1
    )

    assert filename.endswith(".png")
    assert "p1_orig" in filename
    assert os.path.basename(folder) == "p1_My_Post"


def test_generate_filename_single_folder_and_template(tmp_path):
    class MockST:
        def get_creator_filename_template(self):
            return "{creator_name}_{post_id}_{orig_name}"

        def get_creator_folder_strategy(self):
            return "single_folder"

    settings = SimpleNamespace(settings_tab=MockST())
    t = make_thread(tmp_path, settings=settings, auto_rename=True)
    t.creator_name = "Bob"
    file_url = "https://kemono.cr/media/1.jpg?f=file.jpg"

    folder, filename = t.generate_filename_and_folder(
        file_url, str(tmp_path / "dl"), 0, 2, "p1", "Title", page_number=1
    )

    # single_folder => target folder should end with creator folder
    assert os.path.basename(os.path.normpath(folder)) == "42_Bob"
    # auto_rename_enabled => prefix '1_' present on first call
    assert filename.startswith("1_")


def test_get_desc_folder_for_post_strategies(tmp_path):
    class MockST:
        def __init__(self, strat):
            self._s = strat

        def get_creator_folder_strategy(self):
            return self._s

    for strat, expected_tail in [
        ("by_file_type", os.path.join("", "txt")),
        ("single_folder", ""),
        ("per_post", "p1_Title"),
    ]:
        settings = SimpleNamespace(settings_tab=MockST(strat))
        t = make_thread(tmp_path, settings=settings)
        creator_folder = os.path.normpath(str(tmp_path / "dl" / "42_Alice"))
        desc = t.get_desc_folder_for_post(creator_folder, "p1", "Title")
        if strat == "by_file_type":
            assert desc.endswith(os.path.join("42_Alice", "txt"))
        elif strat == "single_folder":
            assert desc == creator_folder
        else:
            assert desc.endswith(os.path.join("42_Alice", "p1_Title"))


def test__download_text_sync_writes_file(tmp_path, monkeypatch):
    settings = SimpleNamespace(settings_tab=SimpleNamespace())
    t = make_thread(tmp_path, settings=settings)
    t.domain_config = cd.get_domain_config("https://kemono.cr/")

    class Resp:
        status_code = 200

        def json(self):
            return {"id": "p1", "content": "<p>Hello World</p>"}

    class S:
        def get(self, url, headers=None, timeout=None):
            return Resp()

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    post_folder = tmp_path / "desc_folder"
    post_folder.mkdir()
    t._download_text_sync("p1", str(post_folder))

    desc_path = post_folder / "desc_p1.txt"
    assert desc_path.exists()
    text = desc_path.read_text(encoding="utf-8")
    assert "Hello World" in text
