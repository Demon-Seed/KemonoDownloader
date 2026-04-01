import hashlib
import os

from PyQt6.QtGui import QColor, QPixmap

from kemonodownloader.creator_downloader import PreviewThread


class FakeResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.status_code = 200
        self.headers = {"content-length": str(sum(len(c) for c in chunks))}

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c

    def raise_for_status(self):
        return None

    def close(self):
        return None


class FakeSession:
    def __init__(self, chunks):
        self._chunks = chunks

    def get(self, *args, **kwargs):
        return FakeResponse(self._chunks)


def test_preview_thread_uses_cache(qtbot, tmp_path):
    url = "https://example.com/img.png"
    cache_dir = str(tmp_path / "cachep")
    os.makedirs(cache_dir, exist_ok=True)

    # Create a valid small PNG using QPixmap to avoid embedding bytes
    cache_key = hashlib.md5(url.encode()).hexdigest() + ".png"
    cache_path = os.path.join(cache_dir, cache_key)
    pix = QPixmap(4, 4)
    pix.fill(QColor("white"))
    pix.save(cache_path)

    called = []

    def on_preview(u, pix):
        called.append((u, isinstance(pix, QPixmap)))

    thread = PreviewThread(url, cache_dir, settings_tab=None)
    thread.preview_ready.connect(on_preview)
    thread.run()

    assert called and called[0][0] == url and called[0][1] is True


def test_preview_thread_emits_error_for_invalid_data(qtbot, tmp_path, monkeypatch):
    url = "https://example.com/bad.png"
    cache_dir = str(tmp_path / "cacheb")
    os.makedirs(cache_dir, exist_ok=True)

    # Invalid image bytes
    chunks = [b"notanimage"]
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSession(chunks),
    )

    errors = []

    def on_error(msg):
        errors.append(msg)

    thread = PreviewThread(url, cache_dir, settings_tab=None)
    thread.error.connect(on_error)
    thread.run()

    assert errors
