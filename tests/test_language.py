"""Tests for the English string table behind ``translate()``."""

import pytest

from kemonodownloader.kd_language import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    STRINGS,
    KDLanguage,
    language_manager,
    translate,
)
from kemonodownloader.kd_settings import SettingsTab


class TestKDLanguageClass:
    def test_class_instantiation(self):
        assert KDLanguage() is not None

    def test_translations_dict_exists(self):
        manager = KDLanguage()
        assert isinstance(manager.translations, dict)
        assert manager.translations is STRINGS

    def test_default_language(self):
        assert KDLanguage().current_language == DEFAULT_LANGUAGE


class TestLanguageSwitching:
    def test_only_english_is_available(self):
        assert LANGUAGES == ["english"]
        assert language_manager.get_available_languages() == ["english"]

    def test_switching_to_english_is_a_noop(self):
        manager = KDLanguage()
        assert manager.set_language("english") is False
        assert manager.get_current_language() == "english"

    def test_unsupported_languages_are_rejected(self):
        manager = KDLanguage()
        for language in ("japanese", "korean", "chinese-simplified", "klingon", None):
            assert manager.set_language(language) is False
        assert manager.get_current_language() == "english"


class TestTranslationOutput:
    def test_english_translation(self):
        assert translate("creator_downloader_tab") == "Creator Downloader"

    def test_english_translation_comes_from_the_table(self):
        assert translate("settings_tab") == STRINGS["settings_tab"]

    def test_missing_key_returns_the_key(self):
        missing = "this_key_is_not_in_the_table"
        assert translate(missing) == missing


class TestTranslationFormatting:
    def test_single_argument_formatting(self):
        assert translate("total_posts", 3) == "Total posts: 3"

    def test_no_arguments_leaves_the_placeholder(self):
        assert "{" in translate("total_posts")


class TestLanguageManagerSingleton:
    def test_language_manager_is_a_kdlanguage(self):
        assert isinstance(language_manager, KDLanguage)

    def test_translate_uses_the_singleton(self):
        assert translate("settings_tab") == language_manager.get_text("settings_tab")

    def test_get_language_name_is_english(self):
        assert language_manager.get_language_name() == "English"


class TestKDLanguageEdgeCases:
    def test_get_text_accepts_an_explicit_language(self):
        assert language_manager.get_text("settings_tab", "english") == "Settings"

    def test_get_text_with_extra_args_and_no_placeholder(self):
        # "settings_tab" has no placeholders, so a stray arg must be harmless.
        assert language_manager.get_text("settings_tab", None, "extra") == "Settings"


class TestBatchInputTranslations:
    """Verify that the multi-URL batch translation keys exist."""

    KEYS = [
        "multi_url_placeholder_creator",
        "add_all_to_queue",
    ]

    def setup_method(self):
        self.original = language_manager.current_language

    def teardown_method(self):
        language_manager.set_language(self.original)

    @pytest.mark.parametrize("lang", language_manager.get_available_languages())
    def test_keys_exist(self, lang):
        language_manager.set_language(lang)
        for key in self.KEYS:
            result = translate(key)
            # translate returns the key itself when it's missing
            assert result != key, f"Missing translation for '{key}' in {lang}"


class TestBulkAddSummaryTranslation:
    """Ensure the bulk_add_summary translation key works."""

    def setup_method(self):
        self.original = language_manager.current_language
        language_manager.set_language("english")

    def teardown_method(self):
        language_manager.set_language(self.original)

    def test_bulk_add_summary(self):
        result = translate("bulk_add_summary", 5, 2)
        assert "5" in result
        assert "2" in result


def test_folder_strategy_labels_translated(qapp):
    st = SettingsTab(None)
    try:
        # Default language is english
        st.update_ui_text()
        combo = st.creator_folder_strategy_combo
        assert combo.count() >= 3
        assert combo.itemText(0) == translate("per_post_folders")
        assert combo.itemText(1) == translate("single_creator_folder")
        assert combo.itemText(2) == translate("subfolders_by_file_type")
    finally:
        st.deleteLater()
