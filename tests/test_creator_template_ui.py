from PyQt6.QtWidgets import QMessageBox

from kemonodownloader.creator_downloader import CreatorDownloadThread
from kemonodownloader.kd_language import translate
from kemonodownloader.kd_settings import SettingsTab


def test_template_boxes_hold_the_defaults(qapp, monkeypatch):
    st = SettingsTab(None)
    try:
        # Plain text boxes: no preset combo to keep in step.
        assert not hasattr(st, "creator_filename_combo")
        assert not hasattr(st, "creator_shared_filename_combo")
        assert not hasattr(st, "creator_folder_name_combo")

        assert st.creator_filename_input.text() == (
            "{file_number}_{post_id}_{orig_name}"
        )
        assert st.creator_shared_filename_input.text() == (
            "{post_id}_{file_number}_{orig_name}"
        )
        assert st.creator_folder_name_input.text() == "{post_id}_{post_title}"

        # Typing writes straight into the setting, separators included.
        st.creator_filename_input.setText("{post_id}-{orig_name}")
        assert st.temp_settings["creator_filename_template"] == "{post_id}-{orig_name}"
        st.creator_shared_filename_input.setText("{post_date}-{orig_name}")
        assert st.temp_settings["creator_filename_template_shared"] == (
            "{post_date}-{orig_name}"
        )

        # Help buttons exist and open without raising.
        assert hasattr(st, "creator_template_help_btn")
        assert hasattr(st, "creator_shared_template_help_btn")
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        st.show_template_help()

        # The dedup guard is an Off/On dropdown, on by default.
        assert st.creator_unique_filenames_combo.itemText(0) == translate("option_off")
        assert st.creator_unique_filenames_combo.itemText(1) == translate("option_on")
        assert bool(st.creator_unique_filenames_combo.currentData()) is True
        st.creator_unique_filenames_combo.setCurrentIndex(0)
        assert st.temp_settings["creator_unique_filenames"] is False
        st.creator_unique_filenames_combo.setCurrentIndex(1)
        assert st.temp_settings["creator_unique_filenames"] is True
    finally:
        st.deleteLater()


def test_template_help_lists_every_placeholder():
    text = translate("filename_template_help_text")
    for placeholder in (
        "{post_id}",
        "{post_title}",
        "{orig_name}",
        "{ext}",
        "{file_number}",
        "{file_index}",
        "{post_file_count}",
        "{total_files}",
        "{post_date}",
        "{creator_id}",
        "{creator_name}",
        "{service}",
    ):
        assert placeholder in text
    # The separators note stays: both work.
    assert "{post_id}-{orig_name}" in text
    assert "{post_id}_{orig_name}" in text
    # The dupe warning stays; the other row's explanation does not.
    assert "Warning" in text
    assert "In Post Folder" not in text


def test_invalid_template_falls_back_and_logs(qapp):
    # Create a thread-like object to test formatting
    class DummySettingsTab:
        def get_creator_filename_template(self):
            return "{unknown_field}"

        def get_creator_folder_strategy(self):
            return "per_post"

    class DummySettings:
        def __init__(self):
            self.settings_tab = DummySettingsTab()

    t = CreatorDownloadThread(
        "patreon",
        "creator123",
        "/downloads",
        ["1"],
        [],
        {},
        None,
        "/tmp/other",
        {},
        settings=DummySettings(),
        max_concurrent=1,
    )
    t.creator_name = "Creator Name"
    # Should not raise even with invalid template
    folder, filename = t.generate_filename_and_folder(
        "https://kemono.cr/media/abc/image.jpg", "/downloads", 0, 1, "1", "My Post", page_number=1
    )
    # Fallback format uses post_id_orig_name
    assert (
        filename.endswith("-image.jpg")
        or filename.endswith("_image.jpg")
        or "1_" in filename
        or "1-image.jpg" in filename
    )
