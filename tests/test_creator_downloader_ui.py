from PyQt6.QtWidgets import QFileDialog, QMessageBox

from kemonodownloader import creator_downloader as cd


def test_creator_tab_basic_interactions(tmp_path, monkeypatch):
    class Parent:
        def __init__(self, base):
            self.cache_folder = str(base / "cache")
            self.other_files_folder = str(base / "other")
            self.download_folder = str(base / "dl")

        def animate_button(self, btn, flag):
            pass

    parent = Parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)

    # Fast mode toggle disables category checkboxes
    tab.toggle_fast_mode(2)
    assert tab.fast_mode is True
    assert not tab.creator_main_check.isEnabled()

    # Add a creator url via multi-url input
    test_url = "https://kemono.cr/user/1"
    tab.creator_multi_url_input.setPlainText(test_url)
    tab.add_multiple_creators_to_queue()
    assert any(test_url == item[0] for item in tab.creator_queue)

    # toggle_check_all should return early when no visible posts
    tab.toggle_check_all(2)

    # Test adding creators from file (monkeypatch file dialog)
    file_path = tmp_path / "links.txt"
    file_path.write_text(test_url + "\n")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(file_path), "")
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    tab.add_creators_from_file()
    assert any(test_url == item[0] for item in tab.creator_queue)
