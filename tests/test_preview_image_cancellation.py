import requests

from kemonodownloader import creator_downloader as cd


def test_preview_thread_error_emits_error(monkeypatch):
    # Make get_session.get raise an exception
    class FS:
        def get(self, *a, **k):
            raise requests.RequestException("net")

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: FS())

    captured = {}

    def on_error(msg):
        captured["err"] = msg

    pt = cd.PreviewThread("https://example.com/img.jpg", "/tmp", settings_tab=None)
    pt.error.connect(on_error)
    pt.run()
    assert "err" in captured


def test_image_modal_display_error_shows_message(monkeypatch):
    # Replace PreviewThread so it doesn't start a real thread on init
    class FakeSignal:
        def __init__(self):
            self._slots = []

        def connect(self, fn):
            self._slots.append(fn)

    class FakePreview:
        def __init__(self, *a, **k):
            self.preview_ready = FakeSignal()
            self.progress = FakeSignal()
            self.error = FakeSignal()
            self.finished = FakeSignal()

        def start(self):
            return None

        def deleteLater(self):
            return None

    monkeypatch.setattr(cd, "PreviewThread", FakePreview)

    modal = cd.ImageModal("https://example.com/img.jpg", "/tmp", parent=None)

    # Replace QMessageBox.critical to avoid UI modal
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.QMessageBox.critical", lambda *a, **k: None
    )
    modal.display_error("failed")
    # Label should reflect error loading image
    assert modal._label.text()


def test_cancellation_thread_signals_finished():
    class FakeThread:
        def __init__(self):
            self._running = True

        def stop(self):
            self._running = False

        def isRunning(self):
            return self._running

        def terminate(self):
            self._running = False

        def wait(self, timeout=None):
            return True

    threads = [FakeThread(), FakeThread()]
    ct = cd.CancellationThread(threads)
    finished = {"ok": False}
    ct.finished.connect(lambda: finished.__setitem__("ok", True))
    ct.run()
    assert finished["ok"] is True
