import os
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


def make_thread(tmp_path, settings_tab=None, auto_rename=False):
    files = ["https://ex.org/files/f=example.png"]
    files_map = {files[0]: "42"}
    settings = SimpleNamespace(settings_tab=settings_tab)
    console = SimpleNamespace()
    t = cd.CreatorDownloadThread(
        service="svc",
        creator_id="creator1",
        download_folder=str(tmp_path / "dl"),
        selected_posts=[],
        files_to_download=files,
        files_to_posts_map=files_map,
        console=console,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        auto_rename_enabled=auto_rename,
        settings=settings,
    )
    t.creator_name = "CreatorName"
    return t


def test_generate_filename_and_folder_strategies(tmp_path):
    # Default strategy (per_post)
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{post_id}_{orig_name}",
        get_creator_folder_strategy=lambda: "per_post",
    )
    t = make_thread(tmp_path, settings_tab=settings_tab, auto_rename=False)
    folder, filename = t.generate_filename_and_folder(
        "https://ex.org/files/f=example.png", str(tmp_path), 0, 1, "42", "A Title", page_number=1
    )
    assert filename.endswith(".png")
    # Should create a per-post folder under the creator folder
    assert f"creator1_{t.creator_name}" in folder
    assert folder.endswith(os.path.join(f"creator1_{t.creator_name}", "42_Post_42"))

    # single_folder strategy
    settings_tab.get_creator_folder_strategy = lambda: "single_folder"
    t.settings.settings_tab = settings_tab
    folder2, _ = t.generate_filename_and_folder(
        "https://ex.org/files/f=example.png", str(tmp_path), 0, 1, "42", "A Title", page_number=1
    )
    assert os.path.basename(folder2) == f"creator1_{t.creator_name}"

    # by_file_type strategy
    settings_tab.get_creator_folder_strategy = lambda: "by_file_type"
    t.settings.settings_tab = settings_tab
    folder3, _ = t.generate_filename_and_folder(
        "https://ex.org/files/f=example.png", str(tmp_path), 0, 1, "42", "A Title", page_number=1
    )
    assert os.path.basename(folder3) == "png"


def test_generate_filename_template_fallback(tmp_path):
    # Template that will raise during formatting
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{nonexistent_field}",
        get_creator_folder_strategy=lambda: "per_post",
    )
    t = make_thread(tmp_path, settings_tab=settings_tab)
    folder, filename = t.generate_filename_and_folder(
        "https://ex.org/files/f=example.png", str(tmp_path), 0, 1, "42", "OK", page_number=1
    )
    # Fallback uses post_id_origname
    assert filename.startswith("42_")


def test_get_desc_folder_for_post(tmp_path):
    settings_tab = SimpleNamespace(get_creator_folder_strategy=lambda: "by_file_type")
    t = make_thread(tmp_path, settings_tab=settings_tab)
    creator_folder = os.path.normpath(str(tmp_path / "creator"))
    d = t.get_desc_folder_for_post(creator_folder, "42", "Title")
    assert d.endswith(
        os.path.join(os.path.basename(creator_folder), "txt")
    ) or d.endswith(os.path.join(creator_folder, "txt"))


def test_download_text_sync_writes_file(monkeypatch, tmp_path):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{post_id}_{orig_name}",
        get_creator_folder_strategy=lambda: "per_post",
    )

    t = make_thread(tmp_path, settings_tab=settings_tab)

    # Fake session to return HTML content in post
    class FakeResp:
        status_code = 200

        def json(self):
            return {"post": {"content": "<p>Some <b>HTML</b> content</p>"}}

    class FakeSession:
        def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: FakeSession())

    post_id = "42"
    desc_folder = str(tmp_path / "desc")
    os.makedirs(desc_folder, exist_ok=True)
    t._download_text_sync(post_id, desc_folder)
    p = os.path.join(desc_folder, f"desc_{post_id}.txt")
    assert os.path.exists(p)
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Some" in content


def test_safe_emit_ignores_when_destroyed(tmp_path):
    t = make_thread(tmp_path)
    # mark destroyed and ensure no exception
    t._destroyed = True
    # should not raise
    t._safe_emit(t.log, "ignored")


def test_download_file_skips_when_not_running(tmp_path):
    t = make_thread(tmp_path)
    t.is_running = False
    # Should return quickly without raising (async method)
    import asyncio

    asyncio.run(t.download_file(t.files_to_download[0], str(tmp_path), 0, 1, page_number=1))


def test_auto_rename_prefix_increments(tmp_path):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{post_id}_{orig_name}",
        get_creator_folder_strategy=lambda: "per_post",
    )
    t = make_thread(tmp_path, settings_tab=settings_tab, auto_rename=True)
    folder, fn1 = t.generate_filename_and_folder(
        "https://ex.org/files/f=example.png", str(tmp_path), 0, 1, "42", "Title", page_number=1
    )
    _, fn2 = t.generate_filename_and_folder(
        "https://ex.org/files/f=example.png", str(tmp_path), 1, 2, "42", "Title", page_number=2
    )
    assert fn1.startswith("1_")
    assert fn2.startswith("2_")


def test_download_post_text_if_needed_calls_once(monkeypatch, tmp_path):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{post_id}_{orig_name}",
        get_creator_folder_strategy=lambda: "per_post",
    )
    t = make_thread(tmp_path, settings_tab=settings_tab)

    called = {"n": 0}

    def fake_download(post_id, post_folder):
        called["n"] += 1

    monkeypatch.setattr(t, "_download_text_sync", fake_download)
    import asyncio

    asyncio.run(t.download_post_text_if_needed("42", str(tmp_path)))
    asyncio.run(t.download_post_text_if_needed("42", str(tmp_path)))
    assert called["n"] == 1
