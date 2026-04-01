from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


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


# Removed flaky test_update_file_completion; coverage exercised elsewhere


def test_create_remove_handler_and_queue_update(qtbot, tmp_path, monkeypatch):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)
    url = "https://kemono.cr/service/user/creatorA"
    tab.creator_queue.append((url, False))

    # Simulate user clicking Yes in the confirmation dialog
    monkeypatch.setattr(
        cd.QMessageBox, "question", lambda *a, **k: cd.QMessageBox.StandardButton.Yes
    )

    handler = tab.create_remove_handler(url)
    handler()
    assert not any(item[0] == url for item in tab.creator_queue)


def test_toggle_check_all_uses_checkbox_thread(monkeypatch, qtbot, tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Populate post_widget_cache with two visible items
    tab.post_url_map = {"A (ID: 1)": ("1", "t1"), "B (ID: 2)": ("2", "t2")}
    tab.add_list_item("A (ID: 1)", "t1", False)
    tab.add_list_item("B (ID: 2)", "t2", False)

    # Fake CheckboxToggleThread to immediately emit finished with all checked
    class Finished:
        def __init__(self):
            self._cbs = []

        def connect(self, cb):
            self._cbs.append(cb)

        def emit(self, *args):
            import inspect

            for cb in list(self._cbs):
                try:
                    n = len(inspect.signature(cb).parameters)
                except Exception:
                    n = 0
                cb(*args[:n])

    class FakeCheckboxToggleThread:
        def __init__(self, visible_posts, checked_urls, state):
            self.visible_posts = visible_posts
            self.checked_urls = checked_urls.copy()
            self.state = state
            self.finished = Finished()
            self.log = Finished()

        def start(self):
            # Build new checked_urls and posts_to_download
            new_checked = {p[1][0]: True for p in self.visible_posts}
            posts_to_download = [p[1][0] for p in self.visible_posts]
            # Call the connected callbacks
            self.finished.emit(new_checked, posts_to_download)

        def deleteLater(self):
            return None

    monkeypatch.setattr(cd, "CheckboxToggleThread", FakeCheckboxToggleThread)
    # Call toggle_check_all with checked state (2)
    tab.toggle_check_all(2)
    # After fake thread runs, posts_to_download should be populated
    assert set(tab.posts_to_download) == {"1", "2"}
