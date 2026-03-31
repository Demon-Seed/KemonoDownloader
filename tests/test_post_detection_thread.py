import gzip
import json

from kemonodownloader import creator_downloader as cd


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
