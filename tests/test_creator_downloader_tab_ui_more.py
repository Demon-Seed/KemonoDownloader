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
        cache_folder=str(tmp_path / "cache2"),
        other_files_folder=str(tmp_path / "other2"),
        download_folder=str(tmp_path / "download2"),
        settings_tab=settings_tab,
        tabs=FakeTabs(),
        status_label=SimpleNamespace(setText=lambda s: None),
        animate_button=lambda *a, **k: None,
    )
    return parent


def test_toggle_fast_mode_and_states(qtbot, monkeypatch, tmp_path):
    # Keep thread settings simple
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
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Toggle fast mode ON (2 == Qt.Checked)
    tab.toggle_fast_mode(2)
    assert tab.fast_mode is True
    # Fast mode should force check-all on
    assert tab.creator_check_all.isChecked()
    assert tab.creator_check_all_all.isChecked()
    # Some controls should be disabled when fast mode is on
    assert not tab.creator_main_check.isEnabled()

    # Toggle fast mode OFF
    tab.toggle_fast_mode(0)
    assert tab.fast_mode is False
    assert not tab.creator_multi_url_input.isVisible()


def test_pagination_and_display(qtbot, monkeypatch, tmp_path):
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
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Create 5 fake posts and set small page size
    tab.posts_per_page = 2
    tab.filtered_posts = [(f"Title{i}", str(i), "thumb", False) for i in range(5)]
    tab.total_pages = max(
        1, (len(tab.filtered_posts) + tab.posts_per_page - 1) // tab.posts_per_page
    )
    tab.current_page = 1
    tab.display_current_page()
    # Should show first page items (2 items)
    assert tab.creator_post_list.count() == 2

    tab.next_page()
    assert tab.current_page == 2
    tab.next_page()
    assert tab.current_page == 3
    tab.prev_page()
    assert tab.current_page == 2


def test_add_creators_from_file(monkeypatch, qtbot, tmp_path):
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
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Create a temporary file with valid and invalid URLs
    fpath = tmp_path / "links.txt"
    fpath.write_text("https://kemono.cr/service/user/creator1\nnot-a-url\n")

    # Monkeypatch file dialog to return our file
    monkeypatch.setattr(
        cd.QFileDialog, "getOpenFileName", lambda *a, **k: (str(fpath), "")
    )

    # Monkeypatch QMessageBox.information to prevent blocking
    monkeypatch.setattr(cd.QMessageBox, "information", lambda *a, **k: None)

    tab.add_creators_from_file()
    # Valid URL should have been added to queue
    assert any("creator1" in item[0] for item in tab.creator_queue)
