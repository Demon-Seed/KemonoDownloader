import inspect
from types import SimpleNamespace

import kemonodownloader.creator_downloader as cd


def make_parent(tmp_path):
    class FakeTabs:
        def count(self):
            return 1

        def currentIndex(self):
            return 0

        def setTabEnabled(self, i, enabled):
            pass

    settings_tab = SimpleNamespace(
        settings_applied=SimpleNamespace(connect=lambda cb: None),
        language_changed=SimpleNamespace(connect=lambda cb: None),
    )
    parent = SimpleNamespace(
        cache_folder=str(tmp_path / "cacheX"),
        other_files_folder=str(tmp_path / "otherX"),
        download_folder=str(tmp_path / "downloadX"),
        settings_tab=settings_tab,
        tabs=FakeTabs(),
        status_label=SimpleNamespace(setText=lambda s: None),
        animate_button=lambda *a, **k: None,
    )
    return parent


class FinishedSignal:
    def __init__(self, value=None):
        self._cbs = []
        self._value = value

    def connect(self, cb):
        self._cbs.append(cb)

    def emit(self, *args):
        for cb in list(self._cbs):
            try:
                n = len(inspect.signature(cb).parameters)
            except Exception:
                n = 0
            cb(*args[:n])


class FakeFilterThread:
    def __init__(self, all_detected_posts, checked_urls, search_text):
        self.all_detected_posts = all_detected_posts
        self.checked_urls = checked_urls
        self.search_text = search_text
        self.finished = FinishedSignal()
        self.log = FinishedSignal()

    def start(self):
        # Build a filtered list identical to all_detected_posts with extra fields
        filtered = [
            (title, post_id, thumb, False)
            for title, (post_id, thumb) in self.all_detected_posts
        ]
        self.finished.emit(filtered)

    def deleteLater(self):
        return None

    def isRunning(self):
        return False


def test_on_post_population_finished_and_filtering(monkeypatch, qtbot, tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Prepare detected posts
    detected = [("Title A", ("1", "t1")), ("Title B", ("2", "t2"))]
    post_url_map = {f"{t} (ID: {p})": (p, thumb) for t, (p, thumb) in detected}

    # Provide files map so prepare_files_for_download won't error later
    tab.current_creator_url = "https://kemono.cr/fanbox/user/abc"
    tab.creator_queue.append((tab.current_creator_url, False))
    tab.all_files_map[tab.current_creator_url] = detected

    # Monkeypatch FilterThread to avoid real thread operations
    monkeypatch.setattr(cd, "FilterThread", FakeFilterThread)

    # Call on_post_population_finished directly
    tab.on_post_population_finished(post_url_map, detected)

    # After population, checked_urls should have entries for both posts
    assert "1" in tab.checked_urls and "2" in tab.checked_urls

    # The creator_queue entry for current_creator_url should be marked processed (True)
    assert any(
        u == tab.current_creator_url and processed for u, processed in tab.creator_queue
    )

    # Filtered posts should be populated and creator_post_list should contain items
    assert tab.filtered_posts
    assert tab.creator_post_list.count() > 0
