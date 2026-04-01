import gzip
import json
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd
from kemonodownloader.creator_downloader import PostDetectionThread, ThreadSettings


class FakeResponse:
    def __init__(self, content_bytes):
        self.content = content_bytes
        self.status_code = 200


class FakeSession:
    def __init__(self, content_bytes):
        self._content = content_bytes

    def get(self, *args, **kwargs):
        return FakeResponse(self._content)


def make_settings():
    settings_tab = SimpleNamespace(get_proxy_settings=lambda: None)
    return ThreadSettings(
        creator_posts_max_attempts=1,
        post_data_max_retries=1,
        file_download_max_retries=1,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def test_post_detection_handles_gzipped_json(monkeypatch):
    # Prepare gzipped JSON body representing a list of posts
    posts = [{"id": "101", "title": "Gzipped Post", "file": {"path": "/media/img.png"}}]
    gzipped = gzip.compress(json.dumps(posts).encode("utf-8"))

    # Monkeypatch get_session to return a session that yields the gzipped response
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSession(gzipped),
    )

    post_titles_map = {}
    settings = make_settings()
    thread = PostDetectionThread(
        "https://kemono.cr/fanbox/user/12345", post_titles_map, settings
    )

    # Run the detection synchronously
    thread.run()

    # The shared post_titles_map should have the detected post title stored
    key = ("fanbox", "12345", "101")
    assert key in post_titles_map
    assert post_titles_map[key] == "Gzipped_Post"


def _make_gz_resp(obj):
    b = json.dumps(obj).encode("utf-8")
    gz = gzip.compress(b)

    class Resp:
        status_code = 200
        content = gz
        headers = {}

    return Resp()


def _make_text_resp(obj):
    s = json.dumps(obj)

    class Resp:
        status_code = 200
        content = s.encode("utf-8")
        text = s
        headers = {}

    return Resp()


def test_post_detection_gzipped_emits_finished(monkeypatch):
    posts = [{"id": "10", "title": "One", "file": {"path": "/img/one.jpg"}}]
    resp = _make_gz_resp(posts)

    class FakeSession:
        def get(self, *a, **k):
            return resp

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: FakeSession())
    settings = cd.ThreadSettings(1, 1, 1, 1, 1, settings_tab=None)

    batches = []
    finished = []
    t = cd.PostDetectionThread("https://kemono.cr/user/1", {}, settings)
    t.posts_batch.connect(lambda b: batches.append(b))
    t.finished.connect(lambda f: finished.append(f))
    t.run()

    assert len(finished) == 1
    # finished emits a list of (title, (post_id, thumbnail_url))
    assert any("One" in title for title, _ in finished[0])


def test_post_detection_posts_dict_response(monkeypatch):
    posts = [{"id": "20", "title": "Two", "file": {"path": "/img/two.jpg"}}]
    resp = _make_text_resp({"posts": posts})

    class FakeSession2:
        def get(self, *a, **k):
            return resp

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: FakeSession2())
    settings = cd.ThreadSettings(1, 1, 1, 1, 1, settings_tab=None)

    finished = []
    t = cd.PostDetectionThread("https://kemono.cr/user/2", {}, settings)
    t.finished.connect(lambda f: finished.append(f))
    t.run()

    assert len(finished) == 1
    assert any("Two" in title for title, _ in finished[0])
