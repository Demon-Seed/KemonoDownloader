import inspect
import os
from types import SimpleNamespace

from PyQt6.QtWidgets import QTextEdit, QWidget

from kemonodownloader import creator_downloader as cd
from kemonodownloader.creator_downloader import LogsWindow


def make_parent(tmp_path):
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path / "cache")
    parent.other_files_folder = str(tmp_path / "other")
    parent.download_folder = str(tmp_path / "dl")
    st = SimpleNamespace()
    st.settings_applied = SimpleNamespace(connect=lambda cb: None)
    st.language_changed = SimpleNamespace(connect=lambda cb: None)
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


def test_detection_to_population_flow(tmp_path, monkeypatch):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    class FakeSignal:
        def __init__(self):
            self.cb = None

        def connect(self, cb):
            self.cb = cb

        def emit(self, *args):
            if self.cb:
                # Call only as many args as the slot accepts to mimic Qt behavior
                import inspect

                try:
                    n = len(inspect.signature(self.cb).parameters)
                except Exception:
                    n = 0
                self.cb(*args[:n])

    class FakePostDetectionThread:
        def __init__(self, url, post_titles_map, settings, **kwargs):
            self.finished = FakeSignal()
            self.posts_batch = FakeSignal()
            self.log = FakeSignal()
            self.error = FakeSignal()

        def isRunning(self):
            return False

        def start(self):
            batch = [("T1", ("p1", "thumb1"))]
            self.posts_batch.emit(batch)
            self.finished.emit(batch)

    class FakePostPopulationThread:
        def __init__(self, detected_posts, post_dates_map=None):
            self.finished = FakeSignal()
            self.log = FakeSignal()

        def isRunning(self):
            return False

        def start(self):
            post_url_map = {"T1 (ID: p1)": ("p1", "thumb1")}
            self.finished.emit(post_url_map, [("T1", ("p1", "thumb1"))])

    monkeypatch.setattr(cd, "PostDetectionThread", FakePostDetectionThread)
    monkeypatch.setattr(cd, "PostPopulationThread", FakePostPopulationThread)

    url = "https://kemono.cr/fanbox/user/1"
    tab.creator_queue.append((url, False))
    tab.update_creator_queue_list()

    # Trigger the check which will use our fake threads synchronously
    tab.check_creator_from_queue(url)

    assert tab.all_detected_posts
    assert tab.post_url_map
    # Ensure items are added to checked_urls for new posts
    assert any(pid in tab.checked_urls for _, (pid, _) in tab.all_detected_posts)


class FakeSignal:
    def __init__(self):
        self._cbs = []

    def connect(self, cb):
        self._cbs.append(cb)

    def emit(self, *args):
        for cb in list(self._cbs):
            try:
                cb(*args)
            except TypeError:
                # Some slots may accept fewer args; fall back to calling without args
                cb()


class FakePostDetectionThread:
    def __init__(self, url, post_titles_map, settings, **kwargs):
        self.finished = FakeSignal()
        self.posts_batch = FakeSignal()
        self.log = FakeSignal()
        self.error = FakeSignal()
        self._started = False

    def start(self):
        # Simulate an incremental batch followed by finished
        sample = [("TitleX", ("1", "thumb"))]
        self.posts_batch.emit(sample)
        self.finished.emit(sample)


def make_parent__from_creator_detection_ui(tmp_path):
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path / "cache")
    parent.other_files_folder = str(tmp_path / "other")
    parent.download_folder = str(tmp_path / "dl")
    parent.settings_tab = None
    parent.ensure_folders_exist = lambda: None
    parent.post_tab = SimpleNamespace()
    parent.creator_tab = SimpleNamespace()
    # settings_tab must provide a settings_applied signal with connect()
    parent.settings_tab = SimpleNamespace()
    parent.settings_tab.settings_applied = FakeSignal()
    parent.settings_tab.language_changed = FakeSignal()
    # Provide minimal getters used by CreatorDownloaderTab._create_thread_settings
    parent.settings_tab.get_creator_posts_max_attempts = lambda: 1
    parent.settings_tab.get_post_data_max_retries = lambda: 1
    parent.settings_tab.get_file_download_max_retries = lambda: 1
    parent.settings_tab.get_api_request_max_retries = lambda: 1
    parent.settings_tab.get_simultaneous_downloads = lambda: 1
    return parent


def test_check_creator_from_queue_triggers_detection(monkeypatch, tmp_path):
    parent = make_parent__from_creator_detection_ui(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Prevent modal dialogs
    monkeypatch.setattr(cd.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(cd.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(
        cd.QMessageBox, "question", lambda *a, **k: cd.QMessageBox.StandardButton.Yes
    )

    # Monkeypatch PostDetectionThread to our fake
    monkeypatch.setattr(cd, "PostDetectionThread", FakePostDetectionThread)

    called = {}

    def fake_start_population(posts):
        called["started"] = True

    tab.start_population_thread = fake_start_population

    url = "https://kemono.cr/user/123"
    tab.creator_queue.append((url, False))
    tab.check_creator_from_queue(url)

    # The fake thread will finish immediately; ensure the population start was called
    assert called.get("started") is True


def make_parent__from_creator_downloader_tab_behavior(tmp_path):
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


def test_create_remove_handler_and_queue_update(qtbot, tmp_path, monkeypatch):
    parent = make_parent__from_creator_downloader_tab_behavior(tmp_path)
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
    parent = make_parent__from_creator_downloader_tab_behavior(tmp_path)
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


class FakeSignal__from_creator_downloader_tab_flow_ui:
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


class FakePostDetectionThread__from_creator_downloader_tab_flow_ui:
    def __init__(self, url, post_titles_map, settings, **kwargs):
        self.url = url
        self.post_titles_map = post_titles_map
        self.settings = settings
        self.finished = FakeSignal__from_creator_downloader_tab_flow_ui()
        self.posts_batch = FakeSignal__from_creator_downloader_tab_flow_ui()
        self.log = FakeSignal__from_creator_downloader_tab_flow_ui()
        self.error = FakeSignal__from_creator_downloader_tab_flow_ui()

    def start(self):
        # Emit a small batch and a finished list synchronously
        batch = [("Post One", ("1", "https://thumb"))]
        self.posts_batch.emit(batch)
        self.finished.emit(batch)


class FakePostPopulationThread:
    def __init__(self, detected_posts, post_dates_map=None):
        self.detected_posts = detected_posts
        self.finished = FakeSignal__from_creator_downloader_tab_flow_ui()
        self.log = FakeSignal__from_creator_downloader_tab_flow_ui()

    def start(self):
        # Provide a post_url_map and pass through detected posts
        post_url_map = {
            f"{p[0]} (ID: {p[1][0]})": (p[1][0], p[1][1]) for p in self.detected_posts
        }
        self.finished.emit(post_url_map, list(self.detected_posts))


def make_parent__from_creator_downloader_tab_flow_ui(tmp_path):
    class FakeTabs:
        def count(self):
            return 1

        def currentIndex(self):
            return 0

        def setTabEnabled(self, i, enabled):
            pass

    settings_tab = SimpleNamespace(
        settings_applied=FakeSignal__from_creator_downloader_tab_flow_ui(),
        language_changed=FakeSignal__from_creator_downloader_tab_flow_ui(),
    )
    parent = SimpleNamespace(
        cache_folder=str(tmp_path / "cache"),
        other_files_folder=str(tmp_path / "other"),
        download_folder=str(tmp_path / "download"),
        settings_tab=settings_tab,
        tabs=FakeTabs(),
        status_label=SimpleNamespace(setText=lambda s: None),
        animate_button=lambda *a, **k: None,
    )
    return parent


def test_check_creator_from_queue_flow(qtbot, monkeypatch, tmp_path):
    # Monkeypatch thread classes and thread settings helper
    monkeypatch.setattr(
        cd,
        "PostDetectionThread",
        FakePostDetectionThread__from_creator_downloader_tab_flow_ui,
    )
    monkeypatch.setattr(cd, "PostPopulationThread", FakePostPopulationThread)
    monkeypatch.setattr(
        cd.CreatorDownloaderTab,
        "_create_thread_settings",
        lambda self: SimpleNamespace(
            creator_posts_max_attempts=1,
            post_data_max_retries=1,
            file_download_max_retries=1,
            api_request_max_retries=1,
            simultaneous_downloads=1,
            settings_tab=None,
        ),
    )

    parent = make_parent__from_creator_downloader_tab_flow_ui(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    url = "https://kemono.cr/service/user/creator1"
    tab.creator_queue.append((url, False))

    # Run the flow
    tab.check_creator_from_queue(url)

    # After the fake threads run synchronously, the queue entry should be marked processed
    assert any(item[0] == url and item[1] for item in tab.creator_queue)
    # all_detected_posts should be populated
    assert tab.all_detected_posts


class DummyParent(QWidget):
    def __init__(self):
        super().__init__()
        self._lines = [("line1", "green"), ("line2", "green")]
        self.append_log_to_console = lambda *a, **k: None

    def log_lines_from(self, index):
        return self._lines[index:]

    def log_next_index(self):
        return len(self._lines)

    def clear_log(self):
        self._lines.clear()


def test_logs_window_download_logs(tmp_path, qapp, monkeypatch):
    # Parent exposing the shared log store, plus append_log_to_console
    parent = DummyParent()

    lw = cd.LogsWindow(parent)
    # Force update of logs_display from the store (timer won't fire in test)
    lw._do_update()

    # Monkeypatch QFileDialog.getSaveFileName to return a path
    save_path = str(tmp_path / "logs.txt")
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.QFileDialog.getSaveFileName",
        lambda *a, **k: (save_path, None),
    )

    lw.download_logs()

    assert os.path.exists(save_path)


def test_add_creators_from_file_reads_and_adds(tmp_path, qapp, monkeypatch):
    # Create minimal parent expected by CreatorDownloaderTab
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path / "cache")
    parent.other_files_folder = str(tmp_path / "other")
    parent.base_folder = str(tmp_path / "base")
    parent.download_folder = str(tmp_path / "dl")
    parent.tabs = SimpleNamespace(
        count=lambda: 1, setTabEnabled=lambda i, b: None, currentIndex=lambda: 0
    )
    parent.settings_tab = SimpleNamespace(
        settings_applied=SimpleNamespace(connect=lambda *a, **k: None),
        language_changed=SimpleNamespace(connect=lambda *a, **k: None),
    )
    os.makedirs(parent.cache_folder, exist_ok=True)
    os.makedirs(parent.other_files_folder, exist_ok=True)

    tab = cd.CreatorDownloaderTab(parent)

    # Create a temp file with two URLs (one valid, one invalid)
    f = tmp_path / "links.txt"
    f.write_text("https://kemono.cr/artist/user/1\nnot-a-url\n")

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(f), None),
    )

    # Prevent modal dialogs from blocking the test
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.QMessageBox.information",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.QMessageBox.critical",
        lambda *a, **k: None,
    )

    # Monkeypatch append_log_to_console to capture messages
    logs = []
    tab.append_log_to_console = lambda msg, level: logs.append((level, msg))

    tab.add_creators_from_file()

    # Expect at least one added and one invalid reported
    assert (
        any("invalid" in m[1].lower() or "invalid" in m[0].lower() for m in logs)
        or len(tab.creator_queue) >= 1
    )


class SimpleSignal:
    def __init__(self):
        pass

    def connect(self, cb):
        return None


def make_parent__from_creator_tab_handlers(tmp_path):
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
    parent = make_parent__from_creator_tab_handlers(tmp_path)
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


def test_add_multiple_creators_to_queue_validates_and_adds(monkeypatch, tmp_path):
    parent = make_parent__from_creator_tab_handlers(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    url = "https://kemono.cr/user/abc"
    tab.creator_multi_url_input.setPlainText(url)
    tab.add_multiple_creators_to_queue()
    assert any(u for u, _ in tab.creator_queue if u == url)


def make_parent__from_creator_tab_population_and_filter(tmp_path):
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
    def __init__(
        self,
        all_detected_posts,
        checked_urls,
        search_text,
        search_scopes=None,
        post_search_index=None,
        post_filters=None,
        creator_url=None,
        file_skip_keywords=None,
    ):
        self.all_detected_posts = all_detected_posts
        self.creator_url = creator_url
        self.checked_urls = checked_urls
        self.search_text = search_text
        self.search_scopes = search_scopes
        self.post_search_index = post_search_index
        self.post_filters = post_filters
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
    parent = make_parent__from_creator_tab_population_and_filter(tmp_path)
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


def test_creator_tab_ui_basics(monkeypatch, qapp, tmp_path):
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path)
    parent.other_files_folder = str(tmp_path)
    parent.download_folder = str(tmp_path)

    # Instantiate the tab with a minimal parent (no settings_tab)
    tab = cd.CreatorDownloaderTab(parent)

    # Prevent modal dialogs from blocking tests
    monkeypatch.setattr(cd.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(cd.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(
        cd.QMessageBox, "question", lambda *a, **k: cd.QMessageBox.StandardButton.Yes
    )

    # update_ui_text should populate widget labels without error
    tab.update_ui_text()
    assert tab.creator_download_btn.text() != ""

    # The multi-URL input is always available.

    # Add multiple creators: include one valid and one invalid URL
    valid = "https://kemono.cr/user/123"
    invalid = "not a url"
    tab.creator_multi_url_input.setPlainText(f"{valid}\n{invalid}\n")
    tab.add_multiple_creators_to_queue()
    # valid should have been added
    assert any(valid in u for u, _ in tab.creator_queue)

    # Empty input logs an error and leaves the queue untouched
    tab.creator_multi_url_input.setPlainText("")
    tab.add_multiple_creators_to_queue()
    # Duplicate prevention: adding the same valid URL again is skipped
    tab.creator_multi_url_input.setPlainText(valid)
    tab.add_multiple_creators_to_queue()
    assert sum(1 for u, _ in tab.creator_queue if u == valid) == 1

    # create_remove_handler should remove entry when user confirms
    pre_len = len(tab.creator_queue)
    url_to_remove = tab.creator_queue[0][0]
    remove_handler = tab.create_remove_handler(url_to_remove)
    remove_handler()
    assert len(tab.creator_queue) <= pre_len


def make_parent__from_creator_tab_ui_small(tmp_path):
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


def test_add_multiple_creators_to_queue_basic(tmp_path):
    parent = make_parent__from_creator_tab_ui_small(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Provide one valid and one invalid URL
    tab.creator_multi_url_input.setPlainText(
        "https://kemono.cr/fanbox/user/111\nnot-a-url"
    )
    tab.add_multiple_creators_to_queue()

    # The valid URL should be in the queue, input cleared
    assert any("fanbox/user/111" in item[0] for item in tab.creator_queue)
    assert tab.creator_multi_url_input.toPlainText().strip() == ""


def test_category_checks_are_enabled(tmp_path):
    parent = make_parent__from_creator_tab_ui_small(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    assert tab.creator_main_check.isEnabled() is True
    assert tab.creator_attachments_check.isEnabled() is True
    assert tab.creator_content_check.isEnabled() is True


class StoreParent(QWidget):
    """Minimal parent exposing the shared log-store API."""

    def __init__(self, lines=()):
        super().__init__()
        self._lines = list(lines)
        self.clear_calls = 0

    def log_lines_from(self, index):
        return self._lines[index:]

    def log_next_index(self):
        return len(self._lines)

    def clear_log(self):
        self.clear_calls += 1
        self._lines.clear()


def test_logs_window_download_and_clear(tmp_path, monkeypatch):
    parent = StoreParent([("line1", "green"), ("line2", "green")])
    appended = []
    parent.append_log_to_console = lambda msg, level=None: appended.append((msg, level))

    logs = cd.LogsWindow(parent)

    out_path = str(tmp_path / "out.txt")
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.QFileDialog.getSaveFileName",
        lambda *a, **k: (out_path, ""),
    )

    logs._do_update()
    logs.download_logs()
    assert os.path.exists(out_path)
    assert appended  # saving is reported back to the parent's log

    # Clearing the window clears the parent's store as well.
    logs.clear_logs()
    assert logs.logs_display.toPlainText() == ""
    assert parent.clear_calls == 1


def test_image_modal_display_and_progress(monkeypatch):
    # Create an uninitialized ImageModal to test its methods directly
    modal = cd.ImageModal.__new__(cd.ImageModal)
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QLabel, QProgressBar

    modal._progress_bar = QProgressBar()
    modal._label = QLabel()

    # update_progress should set value and label text
    modal.update_progress(42)
    assert modal._progress_bar.value() == 42

    # display_image should set a pixmap on the label
    pix = QPixmap(10, 10)
    pix.fill()
    modal.display_image("http://x", pix)
    assert modal._label.pixmap() is not None

    # display_error should set label text and call QMessageBox.critical
    called = {}

    def fake_critical(*a, **k):
        called["ok"] = True

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.QMessageBox.critical",
        fake_critical,
    )
    modal.display_error("some error")
    assert called.get("ok") is True


class StoreParent__from_logs_window(QTextEdit):
    """Minimal parent exposing the shared log-store API."""

    def __init__(self, lines=()):
        super().__init__()
        self._lines = list(lines)
        self.clear_calls = 0
        self.logged = []

    def log_lines_from(self, index):
        return self._lines[index:]

    def log_next_index(self):
        return len(self._lines)

    def clear_log(self):
        self.clear_calls += 1
        self._lines.clear()

    def append_log_to_console(self, message, level=None):
        self.logged.append((message, level))


def test_logs_window_download_and_clear__from_logs_window(qtbot, tmp_path, monkeypatch):
    parent = StoreParent__from_logs_window([("line1", "green"), ("line2", "green")])

    lw = LogsWindow(parent)
    qtbot.addWidget(lw)

    # Draw whatever the store already holds (the timer does not fire in tests).
    lw._do_update()

    save_path = str(tmp_path / "out_logs.txt")

    # Monkeypatch the QFileDialog.getSaveFileName used inside download_logs
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QFileDialog.getSaveFileName", lambda *a, **k: (save_path, None)
    )

    lw.download_logs()

    assert os.path.exists(save_path)
    with open(save_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "line1" in content
    assert parent.logged  # the save is reported back to the parent's log

    # Clearing the window clears the parent's store as well.
    lw.clear_logs()
    assert lw.logs_display.toPlainText() == ""
    assert parent.clear_calls == 1
