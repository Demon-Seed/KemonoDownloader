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


def test_add_multiple_creators_to_queue_basic(tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Provide one valid and one invalid URL
    tab.creator_multi_url_input.setPlainText(
        "https://kemono.cr/fanbox/user/111\nnot-a-url"
    )
    tab.add_multiple_creators_to_queue()

    # The valid URL should be in the queue, input cleared
    assert any("fanbox/user/111" in item[0] for item in tab.creator_queue)
    assert tab.creator_multi_url_input.toPlainText().strip() == ""


def test_toggle_fast_mode_disables_controls(tmp_path):
    parent = make_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Enable fast mode
    tab.toggle_fast_mode(2)
    assert tab.creator_main_check.isEnabled() is False
