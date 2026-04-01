from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        # responses is an iterable of FakeResponse objects
        self._responses = list(responses)
        self._calls = 0

    def get(self, *args, **kwargs):
        idx = min(self._calls, len(self._responses) - 1)
        resp = self._responses[idx]
        self._calls += 1
        return resp


def test_fetch_and_detect_files_success(monkeypatch):
    post_payload = {
        "post": {
            "file": {"path": "/media/main.jpg", "name": "main.jpg"},
            "attachments": [{"path": "/att/file.zip", "name": "file.zip"}],
            "content": '<p><img src="/images/img1.png"></p>',
        }
    }

    fake_session = FakeSession([FakeResponse(200, post_payload)])
    monkeypatch.setattr(cd, "get_session", lambda settings_tab: fake_session)

    settings = SimpleNamespace(post_data_max_retries=1, settings_tab=None)

    class C:
        def __init__(self, checked=True):
            self._checked = checked

        def isChecked(self):
            return self._checked

    ext_checks = {".jpg": C(True), ".png": C(True), ".zip": C(True)}

    fpt = cd.FilePreparationThread(["1"], {}, ext_checks, True, True, True, settings)
    res = fpt.fetch_and_detect_files("1", "https://kemono.cr/service/user/creator")
    assert res is not None
    pid, files = res
    assert pid == "1"
    assert any(
        "main.jpg" in n or n.endswith(".zip") or n.endswith(".png") for n, u in files
    )


def test_fetch_and_detect_files_rate_limit_retry(monkeypatch):
    # First response is 429, second is 200
    post_payload = {"post": {"file": {"path": "/media/m.jpg", "name": "m.jpg"}}}
    fake_session = FakeSession([FakeResponse(429, {}), FakeResponse(200, post_payload)])
    monkeypatch.setattr(cd, "get_session", lambda settings_tab: fake_session)
    # Avoid sleeping delays
    monkeypatch.setattr(cd, "time", SimpleNamespace(sleep=lambda s: None))

    settings = SimpleNamespace(post_data_max_retries=2, settings_tab=None)

    class C:
        def __init__(self, checked=True):
            self._checked = checked

        def isChecked(self):
            return self._checked

    ext_checks = {".jpg": C(True)}
    fpt = cd.FilePreparationThread(["1"], {}, ext_checks, True, True, True, settings)
    res = fpt.fetch_and_detect_files("1", "https://kemono.cr/service/user/creator")
    assert res is not None
    pid, files = res
    assert pid == "1"
    assert files


def test_download_text_sync_writes_file(monkeypatch, tmp_path):
    # Prepare fake response containing HTML content
    post_payload = {"post": {"content": "<p>Hello <b>world</b></p>"}}
    fake_session = FakeSession([FakeResponse(200, post_payload)])
    monkeypatch.setattr(cd, "get_session", lambda settings_tab: fake_session)

    settings = SimpleNamespace(settings_tab=None)
    t = cd.CreatorDownloadThread(
        "service",
        "creator",
        str(tmp_path),
        ["1"],
        [],
        {},
        None,
        str(tmp_path),
        {},
        False,
        settings,
    )
    # Ensure domain config has api_base and referer
    t.domain_config = {
        "api_base": "https://kemono.cr/api",
        "referer": "https://kemono.cr",
    }

    post_folder = tmp_path / "post_1"
    post_folder.mkdir()
    t._download_text_sync("1", str(post_folder))
    desc_path = post_folder / "desc_1.txt"
    assert desc_path.exists()
    text = desc_path.read_text(encoding="utf-8")
    assert "Hello" in text
