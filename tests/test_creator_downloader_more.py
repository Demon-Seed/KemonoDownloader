import gzip
import json
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


def make_gzipped_json(obj):
    return gzip.compress(json.dumps(obj).encode())


def test_post_detection_thread_handles_gzipped_posts(qapp, monkeypatch):
    settings = SimpleNamespace(creator_posts_max_attempts=1, settings_tab=None)
    post_titles_map = {}
    url = "https://kemono.cr/fanbox/user/123"

    posts = [{"id": "p1", "title": "T1", "file": {"path": "/img/a.jpg"}}]
    mock_resp = SimpleNamespace()
    mock_resp.content = make_gzipped_json(posts)
    mock_resp.text = ""
    mock_resp.status_code = 200

    class Sess:
        def get(self, *a, **k):
            return mock_resp

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Sess())

    thread = cd.PostDetectionThread(url, post_titles_map, settings)
    batches = []
    thread.posts_batch.connect(lambda b: batches.append(b))

    thread.run()
    assert batches, "Expected at least one posts_batch emitted"
    assert batches[0][0][0] == "T1"


def test_post_detection_thread_handles_posts_key_and_data_key(qapp, monkeypatch):
    settings = SimpleNamespace(creator_posts_max_attempts=1, settings_tab=None)
    post_titles_map = {}
    url = "https://kemono.cr/fanbox/user/123"

    # Case: API returns {"posts": [...]}
    posts = [{"id": "p2", "title": "Title2"}]
    mock_resp1 = SimpleNamespace()
    mock_resp1.content = json.dumps({"posts": posts}).encode()
    mock_resp1.text = json.dumps({"posts": posts})
    mock_resp1.status_code = 200

    # Case: API returns {"data": [...]}
    posts3 = [{"id": "p3", "title": "Title3"}]
    mock_resp2 = SimpleNamespace()
    mock_resp2.content = json.dumps({"data": posts3}).encode()
    mock_resp2.text = json.dumps({"data": posts3})
    mock_resp2.status_code = 200

    class Sess:
        def __init__(self):
            self._calls = 0

        def get(self, *a, **k):
            self._calls += 1
            return mock_resp1 if self._calls == 1 else mock_resp2

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Sess())

    thread = cd.PostDetectionThread(url, post_titles_map, settings)
    out = []
    thread.posts_batch.connect(lambda b: out.append(b))
    thread.run()
    # We should have batches for both responses
    assert any("Title2" in str(b) or "Title3" in str(b) for b in out)


def test_file_preparation_detect_files_various_cases():
    # Create a FilePreparationThread and call detect_files with different inputs
    t = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks={},
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=1),
    )

    domain_config = {"base_url": "https://kemono.cr"}

    post = {
        "file": {"path": "/a/b/c.jpg", "name": "pic.jpg"},
        "attachments": [{"path": "/att/d.png", "name": "att.png"}],
        "content": '<p>hello <img src="/img/e.gif"></p>',
    }

    detected = t.detect_files(post, [".jpg", ".png", ".gif"], domain_config)
    # Should detect main, attachment and content image
    names = [n for n, u in detected]
    assert "pic.jpg" in names
    assert "att.png" in names
    assert any(u.endswith("/img/e.gif") for _, u in detected)


def test_fetch_and_detect_files_success(monkeypatch, tmp_path):
    # Prepare a FilePreparationThread with checkbox-like objects
    checks = {".jpg": SimpleNamespace(isChecked=lambda: True)}
    settings = SimpleNamespace(post_data_max_retries=1, settings_tab=None)
    t = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks=checks,
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=settings,
    )

    post_id = "99"
    creator_url = "https://kemono.cr/fanbox/user/321"

    post = {"id": post_id, "file": {"path": "/f/g.jpg", "name": "g.jpg"}}

    mock_resp = SimpleNamespace()
    mock_resp.status_code = 200
    mock_resp.json = lambda: post

    class Sess:
        def get(self, *a, **k):
            return mock_resp

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Sess())

    result = t.fetch_and_detect_files(post_id, creator_url)
    assert result is not None
    pid, files = result
    assert pid == post_id
    assert files and files[0][0] == "g.jpg"


def test_download_text_sync_writes_file(monkeypatch, tmp_path):
    # Create a CreatorDownloadThread and run _download_text_sync
    monkeypatch.setattr(
        cd,
        "get_session",
        lambda *a, **k: SimpleNamespace(
            get=lambda *a, **k: SimpleNamespace(
                status_code=200, json=lambda: {"post": {"content": "<p>Hi</p>"}}
            )
        ),
    )

    class DummyHashDB:
        def __init__(self, other_files_dir):
            pass

        def lookup(self, *a, **k):
            return None

        def store(self, *a, **k):
            return None

    monkeypatch.setattr(cd, "HashDB", DummyHashDB)

    th = cd.CreatorDownloadThread(
        service="fanbox",
        creator_id="321",
        download_folder=str(tmp_path),
        selected_posts=["11"],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        auto_rename_enabled=False,
        settings=SimpleNamespace(settings_tab=None),
        max_concurrent=1,
        download_text=False,
    )

    post_folder = tmp_path / "postdesc"
    post_folder.mkdir()
    th._download_text_sync("11", str(post_folder))
    desc_path = post_folder / "desc_11.txt"
    assert desc_path.exists()
    content = desc_path.read_text(encoding="utf-8")
    assert "Hi" in content
