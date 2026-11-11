from PyQt6.QtWidgets import QMessageBox

from kemonodownloader.kd_language import translate
from kemonodownloader.kd_settings import SettingsTab


class MockParent:
    def __init__(self):
        self.download_folder = ""
        self.cache_folder = ""
        self.other_files_folder = ""

        # Minimal post/creator tabs used elsewhere
        class DummyTab:
            pass

        self.post_tab = DummyTab()
        self.creator_tab = DummyTab()

    def ensure_folders_exist(self):
        # Real window creates the folders; the mock only needs the call to work.
        return None

    def log(self, msg):
        pass


def test_settings_applied_message_includes_template_and_strategy(
    monkeypatch, tmp_path, qapp
):
    parent = MockParent()
    st = SettingsTab(parent)
    try:
        # Prepare temp settings with non-empty directory to avoid directory creation warning
        st.temp_settings["base_directory"] = str(tmp_path)
        st.temp_settings["base_folder_name"] = "Kemono Downloader Test"
        st.temp_settings["simultaneous_downloads"] = 3
        st.temp_settings["language"] = "english"
        st.temp_settings["use_proxy"] = False
        st.temp_settings["proxy_type"] = "tor"

        # Set creator-specific settings
        st.temp_settings["creator_filename_template"] = "{post_title}-{post_id}"
        st.temp_settings["creator_folder_strategy"] = "single_folder"
        st.temp_settings["creator_unique_filenames"] = False

        # Monkeypatch question to behave as if the user clicked Yes
        asked = {}

        def fake_question(parent_arg, title, text, *args, **kwargs):
            asked["text"] = text
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", fake_question)

        captured = {}

        def fake_info(self_arg, title, message):
            captured["title"] = title
            captured["message"] = message

        monkeypatch.setattr(QMessageBox, "information", fake_info)

        # Call apply
        st.confirm_and_apply_settings()

        assert "{post_title}-{post_id}" in captured["message"]
        # Folder strategy display uses translate("single_creator_folder")
        assert translate("single_creator_folder") in captured["message"]

        # Both prompts carry the whole setting list, newer settings included.
        for prompt in (asked["text"], captured["message"]):
            assert translate("unique_filenames") in prompt
            assert translate("option_off") in prompt
            assert translate("creator_posts_max_attempts") in prompt
            assert translate("post_data_max_retries") in prompt
            assert translate("file_download_max_retries") in prompt
            assert translate("api_request_max_retries") in prompt
            assert translate("verbose_logging") in prompt
            assert translate("show_only_found_filetypes") in prompt
            assert str(st.temp_settings["file_download_max_retries"]) in prompt
    finally:
        st.deleteLater()
