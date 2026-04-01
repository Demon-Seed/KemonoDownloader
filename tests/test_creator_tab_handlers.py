from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


class SimpleSignal:
    def __init__(self):
        pass

    def connect(self, cb):
        return None


def make_parent(tmp_path):
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path / "cache")
    parent.other_files_folder = str(tmp_path / "other")
    parent.download_folder = str(tmp_path / "dl")
    # Minimal settings_tab with required getters and connectable signals
    st = SimpleNamespace()
    st.settings_applied = SimpleSignal()
    st.language_changed = SimpleSignal()
    st.get_creator_posts_max_attempts = lambda: 1
    st.get_post_data_max_retries = lambda: 1
    st.get_file_download_max_retries = lambda: 1
    st.get_api_request_max_retries = lambda: 1
    st.get_simultaneous_downloads = lambda: 1
    parent.settings_tab = st
    parent.ensure_folders_exist = lambda: None
    parent.post_tab = SimpleNamespace()
    parent.creator_tab = SimpleNamespace()
    return parent


def test_create_remove_handler_removes_url(monkeypatch, tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    url = "https://kemono.cr/user/xyz"
    tab.creator_queue.append((url, False))

    # Confirm dialog -> Yes
    monkeypatch.setattr(
        cd.QMessageBox,
        "question",
        lambda *a, **k: cd.QMessageBox.StandardButton.Yes,
    )

    handler = tab.create_remove_handler(url)
    handler()
    assert all(item[0] != url for item in tab.creator_queue)


def test_add_creator_to_queue_validates_and_adds(monkeypatch, tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Fake ValidationThread to immediately emit a successful result
    class FakeVal:
        def __init__(self, url, settings):
            self.result = SimpleNamespace(connect=lambda cb: setattr(self, "_cb", cb))
            self.log = SimpleNamespace(connect=lambda cb: None)
            self.finished = SimpleNamespace(connect=lambda cb: None)

        def start(self):
            # call the connected callback to simulate result True
            try:
                self._cb(True)
            except Exception:
                pass

    monkeypatch.setattr(cd, "ValidationThread", FakeVal)

    url = "https://kemono.cr/user/abc"
    tab.creator_url_input.setText(url)
    tab.add_creator_to_queue()
    assert any(u for u, _ in tab.creator_queue if u == url)
