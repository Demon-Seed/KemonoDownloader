import os
import subprocess
import sys

from PyQt6.QtCore import QEvent, QObject, QProcess, QSettings, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QCursor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from kemonodownloader import kd_paths
from kemonodownloader.kd_language import language_manager, translate

# Main repository (VoxDroid) used by the in-app update/repository links.
GITHUB_REPO_URL = "https://github.com/VoxDroid/KemonoDownloader"


# Modes for "Show only filetypes found in creator". Kept as plain strings
# and validated on load so a hand-edited settings file cannot land on an
# unknown state.
SHOW_ONLY_FILETYPE_MODES = ("off", "on", "on_with_count")

# "Dedup when name is taken": which kinds of name get a _1/_2 suffix instead of
# overwriting (file names, post folder names, or both).
NAME_DEDUP_MODES = ("off", "file", "folder", "both")

# How each mode is labelled in the combo and in the apply summary.
_NAME_DEDUP_LABEL_KEYS = {
    "off": "option_off",
    "file": "option_on_file",
    "folder": "option_on_folder",
    "both": "option_on_both",
}


def normalize_name_dedup(value):
    """Coerce a stored "dedup when name is taken" value to a known mode.

    Older settings stored a boolean: ``True`` meant "dedupe file names" and
    ``False`` meant "never". They map to ``both`` and ``off`` - the folder half
    of the check used to run unconditionally, so ``both`` keeps a returning
    user's behaviour instead of silently merging same-title posts.
    """
    if isinstance(value, bool):
        return "both" if value else "off"
    text = str(value or "").strip().lower()
    if text in NAME_DEDUP_MODES:
        return text
    if text in ("true", "1", "yes", "on"):
        return "both"
    if text in ("false", "0", "no"):
        return "off"
    return "both"


class ProxyUnavailableError(RuntimeError):
    """Raised when a proxy is enabled but cannot be used.

    ``get_proxy_settings`` returns None only for "no proxy configured". Going
    ahead without a proxy the user asked for would put their real address on
    the wire, so an unusable proxy is an error the download reports rather
    than a silent downgrade to a direct connection.
    """


class _WheelGuard(QObject):
    """Keeps the mouse wheel from changing values on the Settings page.

    Qt hands the wheel to spin boxes, combo boxes and sliders, so scrolling
    the page with the cursor over one of them changed the setting under it.
    Those events are swallowed here and re-sent to the scroll area, so the
    page still scrolls and no value moves.
    """

    def __init__(self, scroll_area, parent=None):
        super().__init__(parent)
        self._scroll_area = scroll_area

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        viewport = self._scroll_area.viewport() if self._scroll_area else None
        if viewport is not None:
            QApplication.sendEvent(viewport, event)
        return True


class SettingsTab(QWidget):
    settings_applied = pyqtSignal()
    language_changed = pyqtSignal()
    font_changed = pyqtSignal(str)
    download_started = pyqtSignal()
    download_finished = pyqtSignal()

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        # Real user storage. Tests must never write here: the autouse
        # isolate_qsettings fixture in tests/conftest.py redirects this
        # class to a temporary INI for the whole suite.
        self.qsettings = QSettings("VoxDroid", "KemonoDownloader")
        self.default_settings = {
            # Legacy: the old "<save>/<folder name>" level is gone, so this no
            # longer affects any path. Kept so existing configs keep loading.
            "base_folder_name": "Kemono Downloader",
            "base_directory": self.get_default_base_directory(),
            # Where the app's own working files live (cache, databases). Defaults
            # to the same folder as the Save Directory, so a fresh install keeps
            # them together until the user splits them.
            # A readout, not a setting: filled in from kd_paths at load time so
            # that importing this module never probes (or creates) the folder.
            "data_directory": "",
            "simultaneous_downloads": 5,
            "language": "english",
            "creator_posts_max_attempts": 200,
            "post_data_max_retries": 7,
            "file_download_max_retries": 50,
            "api_request_max_retries": 3,
            # Debug lines (internal bookkeeping and per-item detail the UI
            # already summarises) stay out of the log unless this is on.
            "verbose_logging": False,
            "show_only_found_filetypes": "on_with_count",
            "use_proxy": False,
            "proxy_type": "tor",  # "custom", "tor"
            "custom_proxy_url": "",
            "tor_path": "",
            # Creator downloader filename/folder customization. Two filename
            # templates replace the old "Rename & Sort" prefix: one for files
            # inside a post's own folder, one for files pooled in a folder
            # shared with other posts (single creator folder, filetype
            # subfolders, or a post whose folder was skipped). Both lead with
            # the post id and the file number, so a post's files stay grouped
            # and in order wherever they land.
            "creator_filename_template": "{post_id}_{file_number}_{orig_name}",
            "creator_filename_template_shared": "{post_id}_{file_number}_{orig_name}",
            # Safety net for templates that drop the placeholders that keep
            # names apart: never overwrite a file that is already there.
            "creator_unique_filenames": "both",
            "creator_folder_strategy": "per_post",  # per_post|single_folder|by_file_type
            "creator_folder_name_template": "{post_id}_{post_title}",
            # Font setting
            "font": "JetBrains Mono",  # "JetBrains Mono", "Poppins"
        }
        self.settings = self.load_settings()
        self.temp_settings = self.settings.copy()

        # Tor process management
        self.tor_process = None
        self.tor_data_dir = None
        self.tor_config_file = None
        # Worker-visible proxy state, refreshed on the GUI thread whenever the
        # proxy settings or the Tor process change (see get_proxy_settings).
        self._proxy_cache = None

        language_manager.set_language(self.settings["language"])

        self.setup_ui()
        self._refresh_proxy_cache()

    def get_default_base_directory(self):
        """Return the platform-appropriate default Save Directory.

        Posts go to the per-user folder, NOT to the app's own data folder:
        ``extras`` holds the databases and the thumbnail cache, and a library
        must never be mixed with those.
        """
        return kd_paths.per_user_directory()

    def load_settings(self):
        settings_dict = {}
        settings_dict["base_folder_name"] = self.qsettings.value(
            "base_folder_name", self.default_settings["base_folder_name"], type=str
        )
        settings_dict["base_directory"] = self.qsettings.value(
            "base_directory", self.default_settings["base_directory"], type=str
        )
        # Fixed location: the row is a readout, so a stored value is ignored.
        settings_dict["data_directory"] = kd_paths.data_directory()
        settings_dict["simultaneous_downloads"] = self.qsettings.value(
            "simultaneous_downloads",
            self.default_settings["simultaneous_downloads"],
            type=int,
        )
        saved_language = self.qsettings.value(
            "language", self.default_settings["language"], type=str
        )
        # Only English ships now, so a stale value from an older build falls back.
        settings_dict["language"] = (
            saved_language
            if saved_language in language_manager.get_available_languages()
            else self.default_settings["language"]
        )
        settings_dict["creator_posts_max_attempts"] = self.qsettings.value(
            "creator_posts_max_attempts",
            self.default_settings["creator_posts_max_attempts"],
            type=int,
        )
        settings_dict["post_data_max_retries"] = self.qsettings.value(
            "post_data_max_retries",
            self.default_settings["post_data_max_retries"],
            type=int,
        )
        settings_dict["file_download_max_retries"] = self.qsettings.value(
            "file_download_max_retries",
            self.default_settings["file_download_max_retries"],
            type=int,
        )
        settings_dict["api_request_max_retries"] = self.qsettings.value(
            "api_request_max_retries",
            self.default_settings["api_request_max_retries"],
            type=int,
        )
        settings_dict["verbose_logging"] = self.qsettings.value(
            "verbose_logging",
            self.default_settings["verbose_logging"],
            type=bool,
        )
        settings_dict["show_only_found_filetypes"] = self.qsettings.value(
            "show_only_found_filetypes",
            self.default_settings["show_only_found_filetypes"],
            type=str,
        )
        if settings_dict["show_only_found_filetypes"] not in SHOW_ONLY_FILETYPE_MODES:
            settings_dict["show_only_found_filetypes"] = "off"
        settings_dict["use_proxy"] = False  # Always start with proxy disabled
        settings_dict["proxy_type"] = self.qsettings.value(
            "proxy_type", self.default_settings["proxy_type"], type=str
        )
        # Convert old "none" proxy type to "tor" for backward compatibility
        if settings_dict["proxy_type"] == "none":
            settings_dict["proxy_type"] = "tor"
        settings_dict["custom_proxy_url"] = self.qsettings.value(
            "custom_proxy_url", self.default_settings["custom_proxy_url"], type=str
        )
        settings_dict["tor_path"] = self.qsettings.value(
            "tor_path", self.default_settings["tor_path"], type=str
        )
        # Creator downloader settings
        settings_dict["creator_filename_template"] = self.qsettings.value(
            "creator_filename_template",
            self.default_settings.get(
                "creator_filename_template", "{post_id}_{file_number}_{orig_name}"
            ),
            type=str,
        )
        settings_dict["creator_filename_template_shared"] = self.qsettings.value(
            "creator_filename_template_shared",
            self.default_settings.get(
                "creator_filename_template_shared",
                "{post_id}_{file_number}_{orig_name}",
            ),
            type=str,
        )
        settings_dict["creator_unique_filenames"] = normalize_name_dedup(
            self.qsettings.value(
                "creator_unique_filenames",
                self.default_settings.get("creator_unique_filenames", "both"),
                type=str,
            )
        )
        settings_dict["creator_folder_strategy"] = self.qsettings.value(
            "creator_folder_strategy",
            self.default_settings.get("creator_folder_strategy", "per_post"),
            type=str,
        )
        settings_dict["creator_folder_name_template"] = self.qsettings.value(
            "creator_folder_name_template",
            self.default_settings.get(
                "creator_folder_name_template", "{post_id}_{post_title}"
            ),
            type=str,
        )
        # Font setting
        settings_dict["font"] = self.qsettings.value(
            "font", self.default_settings.get("font", "JetBrains Mono"), type=str
        )
        return settings_dict

    def save_settings(self):
        self.qsettings.setValue("base_folder_name", self.settings["base_folder_name"])
        self.qsettings.setValue("base_directory", self.settings["base_directory"])
        self.qsettings.setValue(
            "data_directory", kd_paths.data_directory()
        )
        self.qsettings.setValue(
            "simultaneous_downloads", self.settings["simultaneous_downloads"]
        )
        self.qsettings.setValue("language", self.settings["language"])
        self.qsettings.setValue(
            "creator_posts_max_attempts", self.settings["creator_posts_max_attempts"]
        )
        self.qsettings.setValue(
            "post_data_max_retries", self.settings["post_data_max_retries"]
        )
        self.qsettings.setValue(
            "file_download_max_retries", self.settings["file_download_max_retries"]
        )
        self.qsettings.setValue(
            "api_request_max_retries", self.settings["api_request_max_retries"]
        )
        self.qsettings.setValue(
            "verbose_logging", self.settings.get("verbose_logging", False)
        )
        self.qsettings.setValue(
            "show_only_found_filetypes",
            self.settings.get("show_only_found_filetypes", "on_with_count"),
        )
        self.qsettings.setValue("proxy_type", self.settings["proxy_type"])
        self.qsettings.setValue("custom_proxy_url", self.settings["custom_proxy_url"])
        self.qsettings.setValue("tor_path", self.settings["tor_path"])
        # Creator downloader settings
        self.qsettings.setValue(
            "creator_filename_template",
            self.settings.get(
                "creator_filename_template", "{post_id}_{file_number}_{orig_name}"
            ),
        )
        self.qsettings.setValue(
            "creator_filename_template_shared",
            self.settings.get(
                "creator_filename_template_shared",
                "{post_id}_{file_number}_{orig_name}",
            ),
        )
        self.qsettings.setValue(
            "creator_unique_filenames",
            normalize_name_dedup(self.settings.get("creator_unique_filenames", "both")),
        )
        self.qsettings.setValue(
            "creator_folder_strategy",
            self.settings.get("creator_folder_strategy", "per_post"),
        )
        self.qsettings.setValue(
            "creator_folder_name_template",
            self.settings.get("creator_folder_name_template", "{post_id}_{post_title}"),
        )
        # Font setting
        self.qsettings.setValue(
            "font",
            self.settings.get("font", "JetBrains Mono"),
        )
        self.qsettings.sync()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Folder Settings Group
        self.folder_group = QGroupBox()
        self.folder_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        folder_layout = QGridLayout()

        self.directory_label = QLabel()
        folder_layout.addWidget(self.directory_label, 0, 0)
        self.directory_input = QLineEdit(self.temp_settings["base_directory"])
        self.directory_input.setStyleSheet("padding: 5px; border-radius: 5px;")
        self.directory_input.textChanged.connect(
            lambda: self.update_temp_setting(
                "base_directory", self.directory_input.text()
            )
        )
        folder_layout.addWidget(self.directory_input, 0, 1)

        self.browse_button = QPushButton()
        self.browse_button.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px;"
        )
        self.browse_button.clicked.connect(self.browse_directory)
        folder_layout.addWidget(self.browse_button, 0, 2)

        # The app's own working files live next to the application, in
        # "extras" - there is no setting for them any more, so the row is a
        # read-only readout of where they are (see kd_paths).
        self.data_directory_label = QLabel()
        folder_layout.addWidget(self.data_directory_label, 1, 0)
        self.data_directory_input = QLineEdit(kd_paths.data_directory())
        self.data_directory_input.setReadOnly(True)
        self.data_directory_input.setEnabled(False)
        self.data_directory_input.setStyleSheet(
            "padding: 5px; border-radius: 5px; color: #C8D4E8;"
        )
        folder_layout.addWidget(self.data_directory_input, 1, 1)

        self.browse_data_button = QPushButton()
        self.browse_data_button.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px;"
        )
        # It cannot choose the folder any more, so it opens it instead: that is
        # what people actually wanted (to back up or clear the databases).
        self.browse_data_button.clicked.connect(self.open_data_directory)
        folder_layout.addWidget(self.browse_data_button, 1, 2)

        self.folder_group.setLayout(folder_layout)
        layout.addWidget(self.folder_group)

        # Download Settings Group
        self.download_group = QGroupBox()
        self.download_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        download_layout = QGridLayout()

        self.simultaneous_downloads_label = QLabel()
        download_layout.addWidget(self.simultaneous_downloads_label, 0, 0)
        self.download_slider = QSlider(Qt.Orientation.Horizontal)
        self.download_slider.setRange(1, 20)
        self.download_slider.setValue(self.temp_settings["simultaneous_downloads"])
        self.download_slider.setStyleSheet(
            "QSlider::groove:horizontal { border: 1px solid #4A5B7A; height: 8px; background: #2A3B5A; margin: 2px 0; }"
            "QSlider::handle:horizontal { background: #4A5B7A; width: 18px; margin: -2px 0; border-radius: 9px; }"
        )
        self.download_slider.valueChanged.connect(self.update_simultaneous_downloads)
        download_layout.addWidget(self.download_slider, 0, 1)
        self.download_spinbox = QSpinBox()
        self.download_spinbox.setRange(1, 20)
        self.download_spinbox.setValue(self.temp_settings["simultaneous_downloads"])
        self.download_spinbox.setStyleSheet("padding: 5px; border-radius: 5px;")
        self.download_spinbox.valueChanged.connect(self.update_simultaneous_downloads)
        download_layout.addWidget(self.download_spinbox, 0, 2)

        self.download_group.setLayout(download_layout)
        layout.addWidget(self.download_group)

        # Retry Settings Group
        self.retry_group = QGroupBox()
        self.retry_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        retry_layout = QGridLayout()

        self.creator_posts_max_attempts_label = QLabel()
        retry_layout.addWidget(self.creator_posts_max_attempts_label, 0, 0)
        self.creator_posts_max_attempts_spinbox = QSpinBox()
        self.creator_posts_max_attempts_spinbox.setRange(1, 1000)
        self.creator_posts_max_attempts_spinbox.setValue(
            self.temp_settings["creator_posts_max_attempts"]
        )
        self.creator_posts_max_attempts_spinbox.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        self.creator_posts_max_attempts_spinbox.valueChanged.connect(
            lambda value: self.update_temp_setting("creator_posts_max_attempts", value)
        )
        retry_layout.addWidget(self.creator_posts_max_attempts_spinbox, 0, 1)

        self.post_data_max_retries_label = QLabel()
        retry_layout.addWidget(self.post_data_max_retries_label, 1, 0)
        self.post_data_max_retries_spinbox = QSpinBox()
        self.post_data_max_retries_spinbox.setRange(1, 100)
        self.post_data_max_retries_spinbox.setValue(
            self.temp_settings["post_data_max_retries"]
        )
        self.post_data_max_retries_spinbox.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        self.post_data_max_retries_spinbox.valueChanged.connect(
            lambda value: self.update_temp_setting("post_data_max_retries", value)
        )
        retry_layout.addWidget(self.post_data_max_retries_spinbox, 1, 1)

        self.file_download_max_retries_label = QLabel()
        retry_layout.addWidget(self.file_download_max_retries_label, 2, 0)
        self.file_download_max_retries_spinbox = QSpinBox()
        self.file_download_max_retries_spinbox.setRange(1, 200)
        self.file_download_max_retries_spinbox.setValue(
            self.temp_settings["file_download_max_retries"]
        )
        self.file_download_max_retries_spinbox.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        self.file_download_max_retries_spinbox.valueChanged.connect(
            lambda value: self.update_temp_setting("file_download_max_retries", value)
        )
        retry_layout.addWidget(self.file_download_max_retries_spinbox, 2, 1)

        self.api_request_max_retries_label = QLabel()
        retry_layout.addWidget(self.api_request_max_retries_label, 3, 0)
        self.api_request_max_retries_spinbox = QSpinBox()
        self.api_request_max_retries_spinbox.setRange(1, 50)
        self.api_request_max_retries_spinbox.setValue(
            self.temp_settings["api_request_max_retries"]
        )
        self.api_request_max_retries_spinbox.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        self.api_request_max_retries_spinbox.valueChanged.connect(
            lambda value: self.update_temp_setting("api_request_max_retries", value)
        )
        retry_layout.addWidget(self.api_request_max_retries_spinbox, 3, 1)

        self.retry_group.setLayout(retry_layout)
        layout.addWidget(self.retry_group)

        # Creator downloader customization group
        self.creator_custom_group = QGroupBox()
        self.creator_custom_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        creator_custom_layout = QGridLayout()

        self.creator_custom_label = QLabel()
        creator_custom_layout.addWidget(self.creator_custom_label, 0, 0)

        # Filename templates: one for files inside a post's own folder, one for
        # files that land in a folder shared with other posts. They replace the
        # old "Rename & Sort" prefix, which was prepended behind the user's
        # back; the defaults reproduce that output. Free text on purpose - there
        # are no presets to keep in step, and any separator works.
        self.creator_filename_input = QLineEdit(
            self.temp_settings.get(
                "creator_filename_template", "{post_id}_{file_number}_{orig_name}"
            )
        )
        self.creator_filename_input.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        self.creator_filename_input.textChanged.connect(
            lambda text: self.update_temp_setting("creator_filename_template", text)
        )
        creator_custom_layout.addWidget(self.creator_filename_input, 0, 1)

        # Help button for template variables (covers both template rows)
        self.creator_template_help_btn = QPushButton("?")
        self.creator_template_help_btn.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px; min-width: 26px; max-width: 26px;"
        )
        self.creator_template_help_btn.clicked.connect(self.show_template_help)
        creator_custom_layout.addWidget(self.creator_template_help_btn, 0, 2)

        self.creator_shared_template_label = QLabel()
        creator_custom_layout.addWidget(self.creator_shared_template_label, 1, 0)

        self.creator_shared_filename_input = QLineEdit(
            self.temp_settings.get(
                "creator_filename_template_shared",
                "{post_id}_{file_number}_{orig_name}",
            )
        )
        self.creator_shared_filename_input.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        self.creator_shared_filename_input.textChanged.connect(
            lambda text: self.update_temp_setting(
                "creator_filename_template_shared", text
            )
        )
        creator_custom_layout.addWidget(self.creator_shared_filename_input, 1, 1)

        self.creator_shared_template_help_btn = QPushButton("?")
        self.creator_shared_template_help_btn.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px; min-width: 26px; max-width: 26px;"
        )
        self.creator_shared_template_help_btn.clicked.connect(
            self.show_template_help
        )
        creator_custom_layout.addWidget(self.creator_shared_template_help_btn, 1, 2)

        self.creator_folder_name_label = QLabel(translate("folder_name_template"))
        creator_custom_layout.addWidget(self.creator_folder_name_label, 2, 0)

        # Folder name template: free text, same placeholder style.
        self.creator_folder_name_input = QLineEdit(
            self.temp_settings.get(
                "creator_folder_name_template", "{post_id}_{post_title}"
            )
        )
        self.creator_folder_name_input.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        self.creator_folder_name_input.textChanged.connect(
            lambda text: self.update_temp_setting(
                "creator_folder_name_template", text
            )
        )
        creator_custom_layout.addWidget(self.creator_folder_name_input, 2, 1)

        self.creator_folder_name_help_btn = QPushButton("?")
        self.creator_folder_name_help_btn.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px; min-width: 26px; max-width: 26px;"
        )
        self.creator_folder_name_help_btn.clicked.connect(
            self.show_folder_name_template_help
        )
        creator_custom_layout.addWidget(self.creator_folder_name_help_btn, 2, 2)

        # Safety net for templates that drop the placeholders keeping names
        # apart. File names and post folder names are deduped independently:
        # a folder needs it for same-title posts, a file needs it when the
        # template omits {file_number}/{post_id}. It follows the folder
        # template because it is the folder template's safety net.
        self.creator_unique_filenames_label = QLabel()
        creator_custom_layout.addWidget(self.creator_unique_filenames_label, 3, 0)

        self.creator_unique_filenames_combo = QComboBox()
        for label_key, mode in (
            ("option_off", "off"),
            ("option_on_file", "file"),
            ("option_on_folder", "folder"),
            ("option_on_both", "both"),
        ):
            self.creator_unique_filenames_combo.addItem(translate(label_key), mode)
        self.creator_unique_filenames_combo.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        current_unique = normalize_name_dedup(
            self.temp_settings.get("creator_unique_filenames", "both")
        )
        for i in range(self.creator_unique_filenames_combo.count()):
            if self.creator_unique_filenames_combo.itemData(i) == current_unique:
                self.creator_unique_filenames_combo.setCurrentIndex(i)
                break
        self.creator_unique_filenames_combo.currentIndexChanged.connect(
            lambda index: self.update_temp_setting(
                "creator_unique_filenames",
                self.creator_unique_filenames_combo.itemData(index),
            )
        )
        creator_custom_layout.addWidget(
            self.creator_unique_filenames_combo, 3, 1, 1, 2
        )

        self.creator_folder_strategy_label = QLabel()
        creator_custom_layout.addWidget(self.creator_folder_strategy_label, 4, 0)

        self.creator_folder_strategy_combo = QComboBox()
        self.creator_folder_strategy_combo.addItem(
            translate("per_post_folders"), "per_post"
        )
        self.creator_folder_strategy_combo.addItem(
            translate("single_creator_folder"), "single_folder"
        )
        self.creator_folder_strategy_combo.addItem(
            translate("subfolders_by_file_type"), "by_file_type"
        )
        self.creator_folder_strategy_combo.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        # Set current index based on temp setting
        strategy = self.temp_settings.get("creator_folder_strategy", "per_post")
        for i in range(self.creator_folder_strategy_combo.count()):
            if self.creator_folder_strategy_combo.itemData(i) == strategy:
                self.creator_folder_strategy_combo.setCurrentIndex(i)
                break
        self.creator_folder_strategy_combo.currentIndexChanged.connect(
            lambda idx: self.update_temp_setting(
                "creator_folder_strategy",
                self.creator_folder_strategy_combo.itemData(idx),
            )
        )
        creator_custom_layout.addWidget(self.creator_folder_strategy_combo, 4, 1)

        # Limit the Creator tab extension boxes to the filetypes a creator
        # really has: off, on, or on with a per-type filecount beside each box.
        self.show_only_found_filetypes_label = QLabel()
        self.show_only_found_filetypes_label.setStyleSheet("color: white;")
        creator_custom_layout.addWidget(
            self.show_only_found_filetypes_label, 5, 0
        )

        self.show_only_found_filetypes_combo = QComboBox()
        for label_key, mode in (
            ("filetype_filter_off", "off"),
            ("filetype_filter_on", "on"),
            ("filetype_filter_on_with_count", "on_with_count"),
        ):
            self.show_only_found_filetypes_combo.addItem(
                translate(label_key), mode
            )
        self.show_only_found_filetypes_combo.setStyleSheet(
            "padding: 5px; border-radius: 5px;"
        )
        current_mode = self.temp_settings.get(
            "show_only_found_filetypes", "off"
        )
        for i in range(self.show_only_found_filetypes_combo.count()):
            if self.show_only_found_filetypes_combo.itemData(i) == current_mode:
                self.show_only_found_filetypes_combo.setCurrentIndex(i)
                break
        self.show_only_found_filetypes_combo.currentIndexChanged.connect(
            lambda idx: self.update_temp_setting(
                "show_only_found_filetypes",
                self.show_only_found_filetypes_combo.itemData(idx),
            )
        )
        creator_custom_layout.addWidget(
            self.show_only_found_filetypes_combo, 5, 1, 1, 2
        )

        self.creator_custom_group.setLayout(creator_custom_layout)
        layout.addWidget(self.creator_custom_group)

        # Repository / Updates Group: a direct link to the main repository
        # replaced the previous automatic update check.
        self.update_group = QGroupBox()
        self.update_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        update_layout = QGridLayout()

        self.github_repo_link = QLabel()
        self.github_repo_link.setTextFormat(Qt.TextFormat.RichText)
        self.github_repo_link.setOpenExternalLinks(True)
        self.github_repo_link.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        update_layout.addWidget(self.github_repo_link, 0, 0)

        self.update_group.setLayout(update_layout)
        layout.addWidget(self.update_group)

        # Font Settings Group
        self.font_group = QGroupBox()
        self.font_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        font_layout = QGridLayout()

        self.font_label = QLabel()
        font_layout.addWidget(self.font_label, 0, 0)

        self.font_combo = QComboBox()
        self._available_fonts = [
            ("JetBrains Mono", "JetBrains Mono"),
            ("Poppins", "Poppins"),
        ]
        for display_name, font_family in self._available_fonts:
            self.font_combo.addItem(display_name, font_family)
        self.font_combo.setStyleSheet("padding: 5px; border-radius: 5px;")

        # Set current font selection
        current_font = self.temp_settings.get("font", "JetBrains Mono")
        for i in range(self.font_combo.count()):
            if self.font_combo.itemData(i) == current_font:
                self.font_combo.setCurrentIndex(i)
                break
        self.font_combo.currentIndexChanged.connect(self.update_font)
        font_layout.addWidget(self.font_combo, 0, 1)

        self.font_group.setLayout(font_layout)
        layout.addWidget(self.font_group)

        # Enable proxy checkbox (outside the proxy group so it's always visible)
        self.use_proxy_checkbox = QCheckBox()
        self.use_proxy_checkbox.setStyleSheet(
            "QCheckBox::indicator { width: 16px; height: 16px; }"
            "QCheckBox::indicator:unchecked { background: #2A3B5A; border: 1px solid #4A5B7A; }"
            "QCheckBox::indicator:checked { background: #4A6B9A; border: 1px solid #5A7BA9; }"
        )
        self.use_proxy_checkbox.stateChanged.connect(self.on_use_proxy_changed)

        # Proxy Settings Group
        self.proxy_group = QGroupBox()
        self.proxy_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        self.proxy_group.setVisible(
            False
        )  # Start hidden, will be shown by on_use_proxy_changed
        proxy_layout = QVBoxLayout()

        # Proxy type selection
        proxy_type_layout = QHBoxLayout()
        self.proxy_type_label = QLabel()
        proxy_type_layout.addWidget(self.proxy_type_label)

        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItem("Custom Proxy", "custom")
        self.proxy_type_combo.addItem("Tor", "tor")
        self.proxy_type_combo.setStyleSheet("padding: 5px; border-radius: 5px;")
        self.proxy_type_combo.currentIndexChanged.connect(self.on_proxy_type_changed)

        # Block signals during initialization to prevent premature UI updates
        self.use_proxy_checkbox.blockSignals(True)
        self.proxy_type_combo.blockSignals(True)

        # Set initial values
        self.use_proxy_checkbox.setChecked(self.temp_settings["use_proxy"])
        self.proxy_type_combo.setCurrentIndex(
            self.get_proxy_type_index(self.temp_settings["proxy_type"])
        )

        # Unblock signals
        self.use_proxy_checkbox.blockSignals(False)
        self.proxy_type_combo.blockSignals(False)

        # Verbose logging sits with the proxy switch at the bottom of the tab:
        # both are "when a run misbehaves" knobs. Off by default, so the log
        # keeps only events, warnings and errors.
        self.verbose_logging_checkbox = QCheckBox()
        self.verbose_logging_checkbox.setStyleSheet(
            "QCheckBox::indicator { width: 16px; height: 16px; } "
            "QCheckBox::indicator:unchecked { background: #2A3B5A; } "
            "QCheckBox::indicator:checked { background: #4A6B9A; }"
        )
        self.verbose_logging_checkbox.setChecked(
            bool(self.temp_settings.get("verbose_logging", False))
        )
        self.verbose_logging_checkbox.toggled.connect(
            lambda checked: self.update_temp_setting("verbose_logging", bool(checked))
        )
        layout.addWidget(self.verbose_logging_checkbox)

        layout.addWidget(self.use_proxy_checkbox)

        proxy_type_layout.addWidget(self.proxy_type_combo)
        proxy_layout.addLayout(proxy_type_layout)

        # Custom proxy input
        self.custom_proxy_layout = QHBoxLayout()
        self.custom_proxy_label = QLabel()
        self.custom_proxy_layout.addWidget(self.custom_proxy_label)

        self.custom_proxy_input = QLineEdit(self.temp_settings["custom_proxy_url"])
        self.custom_proxy_input.setStyleSheet("padding: 5px; border-radius: 5px;")
        self.custom_proxy_input.setPlaceholderText("e.g., 111.222.333.444:8080")
        self.custom_proxy_input.textChanged.connect(
            lambda: self.update_temp_setting(
                "custom_proxy_url", self.custom_proxy_input.text()
            )
        )
        self.custom_proxy_layout.addWidget(self.custom_proxy_input)

        self.test_custom_proxy_button = QPushButton()
        self.test_custom_proxy_button.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px;"
        )
        self.test_custom_proxy_button.clicked.connect(self.test_custom_proxy)
        self.custom_proxy_layout.addWidget(self.test_custom_proxy_button)

        proxy_layout.addLayout(self.custom_proxy_layout)

        # Tor settings
        self.tor_layout = QVBoxLayout()
        self.tor_label = QLabel()
        self.tor_layout.addWidget(self.tor_label)

        tor_path_layout = QHBoxLayout()
        self.tor_path_input = QLineEdit(self.temp_settings["tor_path"])
        self.tor_path_input.setStyleSheet("padding: 5px; border-radius: 5px;")
        self.tor_path_input.setReadOnly(True)
        self.tor_path_input.textChanged.connect(self.update_tor_button_states)
        tor_path_layout.addWidget(self.tor_path_input)

        self.browse_tor_button = QPushButton()
        self.browse_tor_button.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px;"
        )
        self.browse_tor_button.clicked.connect(self.browse_tor_executable)
        tor_path_layout.addWidget(self.browse_tor_button)

        self.start_tor_button = QPushButton()
        self.start_tor_button.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px;"
        )
        self.start_tor_button.clicked.connect(self.start_tor)
        tor_path_layout.addWidget(self.start_tor_button)

        self.stop_tor_button = QPushButton()
        self.stop_tor_button.setStyleSheet(
            "background: #7A4A4A; padding: 5px; border-radius: 5px;"
        )
        self.stop_tor_button.clicked.connect(self.stop_tor)
        tor_path_layout.addWidget(self.stop_tor_button)

        # Tor status label
        self.tor_status_label = QLabel(translate("tor_status_stopped"))
        self.tor_status_label.setStyleSheet(
            "color: #FF6B6B; font-weight: bold; margin-left: 10px;"
        )
        self.tor_status_label.setVisible(False)
        tor_path_layout.addWidget(self.tor_status_label)
        tor_path_layout.addStretch()

        self.download_tor_button = QPushButton()
        self.download_tor_button.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px;"
        )
        self.download_tor_button.clicked.connect(self.download_tor)
        tor_path_layout.addWidget(self.download_tor_button)

        self.test_tor_button = QPushButton()
        self.test_tor_button.setStyleSheet(
            "background: #4A5B7A; padding: 5px; border-radius: 5px;"
        )
        self.test_tor_button.clicked.connect(self.test_tor)
        tor_path_layout.addWidget(self.test_tor_button)

        self.help_tor_button = QPushButton("Help")
        self.help_tor_button.setStyleSheet(
            "background: #5A6B8A; padding: 5px; border-radius: 5px;"
        )
        self.help_tor_button.clicked.connect(self.show_tor_help)
        tor_path_layout.addWidget(self.help_tor_button)

        self.tor_layout.addLayout(tor_path_layout)

        # Tor download progress bar
        self.tor_progress_bar = QProgressBar()
        self.tor_progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; } QProgressBar::chunk { background: #4A5B7A; }"
        )
        self.tor_progress_bar.setVisible(False)
        self.tor_layout.addWidget(self.tor_progress_bar)

        # Tor output text area
        self.tor_output_label = QLabel("Tor Output:")
        self.tor_output_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        self.tor_output_label.setVisible(False)
        self.tor_layout.addWidget(self.tor_output_label)

        self.tor_output_text = QTextEdit()
        self.tor_output_text.setMaximumHeight(150)
        self.tor_output_text.setStyleSheet(
            "QTextEdit { border: 1px solid #4A5B7A; border-radius: 5px; padding: 5px; background: #2A2A2A; color: #FFFFFF; font-family: 'JetBrains Mono', 'Courier New', monospace; font-size: 10px; }"
        )
        self.tor_output_text.setReadOnly(True)
        self.tor_output_text.setVisible(False)
        self.tor_layout.addWidget(self.tor_output_text)

        proxy_layout.addLayout(self.tor_layout)

        self.proxy_group.setLayout(proxy_layout)
        layout.addWidget(self.proxy_group)

        # Initialize proxy UI state - hide widgets by default
        self.custom_proxy_label.setVisible(False)
        self.custom_proxy_input.setVisible(False)
        self.test_custom_proxy_button.setVisible(False)
        self.tor_label.setVisible(False)
        self.tor_path_input.setVisible(False)
        self.browse_tor_button.setVisible(False)
        self.start_tor_button.setVisible(False)
        self.stop_tor_button.setVisible(False)
        self.download_tor_button.setVisible(False)
        self.test_tor_button.setVisible(False)
        self.help_tor_button.setVisible(False)
        self.tor_status_label.setVisible(False)
        self.tor_progress_bar.setVisible(False)
        self.tor_output_label.setVisible(False)
        self.tor_output_text.setVisible(False)
        self.on_use_proxy_changed(self.temp_settings["use_proxy"])

        # Buttons Layout
        buttons_layout = QHBoxLayout()

        self.apply_button = QPushButton()
        self.apply_button.setStyleSheet(
            "background: #4A5B7A; padding: 8px; border-radius: 5px;"
        )
        self.apply_button.clicked.connect(self.confirm_and_apply_settings)
        buttons_layout.addWidget(self.apply_button)

        self.reset_button = QPushButton(translate("reset_to_defaults"))
        self.reset_button.setStyleSheet(
            "background: #7A4A5B; padding: 8px; border-radius: 5px;"
        )
        self.reset_button.clicked.connect(self.confirm_and_reset_settings)
        buttons_layout.addWidget(self.reset_button)

        layout.addLayout(buttons_layout)
        layout.addStretch()

        # Make the settings page scrollable
        container = QWidget()
        container.setLayout(layout)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(container)
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.scroll_area)
        self.setLayout(main_layout)

        # The wheel scrolls this page; it never changes the value under it.
        self._wheel_guard = _WheelGuard(self.scroll_area, self)
        for widget in self.scroll_area.findChildren(
            (QAbstractSpinBox, QComboBox, QSlider)
        ):
            widget.installEventFilter(self._wheel_guard)

        self.update_ui_text()

        # Initialize Tor button states
        self.update_tor_button_states()

    def update_font(self, index):
        font_family = self.font_combo.itemData(index)
        self.update_temp_setting("font", font_family)

    def show_template_help(self):
        """Show help text explaining the available filename template placeholders."""
        try:
            QMessageBox.information(
                self,
                translate("filename_template_help_title"),
                translate("filename_template_help_text"),
            )
        except Exception:
            # In case translation lookup or UI fails, fall back to a simple message
            QMessageBox.information(
                self,
                "Template Help",
                "Placeholders: {post_id}, {post_title}, {orig_name}, {ext}, "
                "{file_number}, {file_index}, {post_file_count}, {total_files}, "
                "{post_date}, {creator_id}, {creator_name}, {service}",
            )

    def show_folder_name_template_help(self):
        """Show help text explaining the available folder name template placeholders."""
        try:
            QMessageBox.information(
                self,
                translate("folder_name_template_help_title"),
                translate("folder_name_template_help_text"),
            )
        except Exception:
            QMessageBox.information(
                self,
                "Folder Name Template Help",
                "Placeholders: {post_id}, {post_title}, {creator_id}, {creator_name}. "
                "Example: {post_title} (drops the post id). "
                "Example: {post_title} drops the post ID from the folder name. "
                "Only applies when Folder Structure is 'Per-post folders'.",
            )

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self, translate("browse"), self.temp_settings["base_directory"]
        )
        if directory:
            self.directory_input.setText(directory)
            self.update_temp_setting("base_directory", directory)

    def open_data_directory(self):
        """Open the app's own data folder (it can no longer be chosen)."""
        path = kd_paths.data_directory()
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def browse_tor_executable(self):
        """Browse for Tor executable file."""
        if sys.platform == "win32":
            file_filter = "Executable files (*.exe);;All files (*.*)"
            initial_path = self.temp_settings["tor_path"] or "C:\\"
        else:
            file_filter = "All files (*.*)"
            initial_path = self.temp_settings["tor_path"] or "/"

        tor_exe_path, _ = QFileDialog.getOpenFileName(
            self, translate("select_tor_executable"), initial_path, file_filter
        )

        if tor_exe_path:
            self.update_temp_setting("tor_path", tor_exe_path)
            self.tor_path_input.setText(tor_exe_path)

    def auto_detect_tor(self):
        """Try to auto-detect Tor executable in common locations.

        Enhanced detection: in addition to well-known system locations, search
        the current app base directory and download folders so that Tor can be
        detected when installed within the app's own directory (e.g. in
        AppData/Roaming on Windows).
        """
        common_paths = []

        if sys.platform == "win32":
            # Windows common paths
            common_paths.extend(
                [
                    os.path.join(
                        os.getenv("PROGRAMFILES", "C:\\Program Files"),
                        "Tor Browser",
                        "Browser",
                        "TorBrowser",
                        "Tor",
                        "tor.exe",
                    ),
                    os.path.join(
                        os.getenv("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
                        "Tor Browser",
                        "Browser",
                        "TorBrowser",
                        "Tor",
                        "tor.exe",
                    ),
                    os.path.join(
                        os.path.expanduser("~"),
                        "Desktop",
                        "Tor Browser",
                        "Browser",
                        "TorBrowser",
                        "Tor",
                        "tor.exe",
                    ),
                    os.path.join(
                        os.path.expanduser("~"),
                        "Downloads",
                        "Tor Browser",
                        "Browser",
                        "TorBrowser",
                        "Tor",
                        "tor.exe",
                    ),
                ]
            )
        elif sys.platform == "darwin":
            # macOS common paths
            common_paths.extend(
                [
                    "/Applications/Tor Browser.app/Contents/MacOS/Tor/tor",
                    os.path.join(
                        os.path.expanduser("~"),
                        "Applications",
                        "Tor Browser.app",
                        "Contents",
                        "MacOS",
                        "Tor",
                        "tor",
                    ),
                    os.path.join(
                        os.path.expanduser("~"),
                        "Desktop",
                        "Tor Browser.app",
                        "Contents",
                        "MacOS",
                        "Tor",
                        "tor",
                    ),
                    os.path.join(
                        os.path.expanduser("~"),
                        "Downloads",
                        "Tor Browser.app",
                        "Contents",
                        "MacOS",
                        "Tor",
                        "tor",
                    ),
                ]
            )
        else:
            # Linux common paths
            common_paths.extend(
                [
                    "/usr/bin/tor",
                    "/usr/local/bin/tor",
                    "/opt/tor-browser/Browser/TorBrowser/Tor/tor",
                    os.path.join(
                        os.path.expanduser("~"),
                        "tor-browser",
                        "Browser",
                        "TorBrowser",
                        "Tor",
                        "tor",
                    ),
                    os.path.join(
                        os.path.expanduser("~"),
                        "Desktop",
                        "tor-browser",
                        "Browser",
                        "TorBrowser",
                        "Tor",
                        "tor",
                    ),
                    os.path.join(
                        os.path.expanduser("~"),
                        "Downloads",
                        "tor-browser",
                        "Browser",
                        "TorBrowser",
                        "Tor",
                        "tor",
                    ),
                ]
            )

        # Also look for Tor inside the app's data directory / save directory
        try:
            base_dir = self.temp_settings.get("base_directory")
            data_dir = kd_paths.data_directory(
                self.temp_settings.get("data_directory")
            )
        except Exception:
            base_dir = None
            data_dir = None

        candidate_roots = []
        if base_dir:
            candidate_roots.extend(
                [
                    base_dir,
                    os.path.join(base_dir, "Tor"),
                    # Where older builds kept it, so an existing install is
                    # still found after the folder layout change.
                    os.path.join(base_dir, "Downloads"),
                    os.path.join(base_dir, "Downloads", "Tor"),
                ]
            )
        if data_dir:
            candidate_roots.extend([data_dir, os.path.join(data_dir, "Tor")])

        # If parent (app) provides download_folder use that too
        if hasattr(self, "parent") and getattr(self.parent, "download_folder", None):
            df = getattr(self.parent, "download_folder")
            candidate_roots.extend([df, os.path.join(df, "Tor")])

        # Prefer searching the app's candidate roots first (so app-local Tor is detected before system-wide installs),
        # then fall back to common system locations
        search_roots = [
            p for p in candidate_roots if p not in common_paths
        ] + common_paths

        for path in search_roots:
            # If path is a file directly, test it
            if os.path.exists(path) and os.path.isfile(path):
                try:
                    result = subprocess.run(
                        [path, "--version"], capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0 and "Tor" in result.stdout:
                        return path
                except Exception:
                    continue

            # If path is a directory, walk it and look for tor executable
            if os.path.exists(path) and os.path.isdir(path):
                try:
                    for root, dirs, files in os.walk(path):
                        for f in files:
                            if f.lower() in ("tor.exe", "tor"):
                                candidate = os.path.join(root, f)
                                try:
                                    result = subprocess.run(
                                        [candidate, "--version"],
                                        capture_output=True,
                                        text=True,
                                        timeout=5,
                                    )
                                    if (
                                        result.returncode == 0
                                        and "Tor" in result.stdout
                                    ):
                                        return candidate
                                except Exception:
                                    # Continue searching other files
                                    continue
                except Exception:
                    # ignore and move to next root
                    continue

        return None

    def update_temp_setting(self, key, value):
        self.temp_settings[key] = value
        if key in ("use_proxy", "proxy_type", "custom_proxy_url", "tor_path"):
            # Proxy state is read by download threads, which must never touch
            # QProcess themselves: keep the cached answer current here, on the
            # GUI thread.
            self._refresh_proxy_cache()

    def _proxy_signature(self):
        """What the cached proxy answer depends on, without asking Qt."""
        merged = dict(self.settings)
        merged.update(self.temp_settings)
        return (
            bool(merged.get("use_proxy")),
            merged.get("proxy_type"),
            merged.get("custom_proxy_url"),
            id(getattr(self, "tor_process", None)),
        )

    def _refresh_proxy_cache(self):
        """Snapshot the proxy answer (GUI thread only - it reads QProcess)."""
        signature = self._proxy_signature()
        try:
            proxies = SettingsTab._compute_proxy_settings(self)
        except ProxyUnavailableError as error:
            self._proxy_cache = (signature, "error", error)
            return
        except Exception as error:  # never let a cache refresh raise
            self._proxy_cache = (signature, "error", ProxyUnavailableError(str(error)))
            return
        self._proxy_cache = (
            (signature, "proxies", proxies) if proxies else (signature, "none", None)
        )

    def update_simultaneous_downloads(self, value):
        self.temp_settings["simultaneous_downloads"] = value
        self.download_slider.blockSignals(True)
        self.download_spinbox.blockSignals(True)
        self.download_slider.setValue(value)
        self.download_spinbox.setValue(value)
        self.download_slider.blockSignals(False)
        self.download_spinbox.blockSignals(False)

    @staticmethod
    def _same_setting_value(left, right):
        """Compare two setting values, tolerating int/str/bool mismatches."""
        if isinstance(left, bool) or isinstance(right, bool):
            return bool(left) == bool(right)
        if isinstance(left, (int, float)) or isinstance(right, (int, float)):
            try:
                return float(left) == float(right)
            except (TypeError, ValueError):
                return str(left) == str(right)
        return str(left or "") == str(right or "")

    def _settings_rows(self, values):
        """(label, displayed value, setting key) for every prompt row."""
        enabled = translate("enabled")
        disabled = translate("disabled")
        mode_key = {
            "off": "filetype_filter_off",
            "on": "filetype_filter_on",
            "on_with_count": "filetype_filter_on_with_count",
        }.get(values.get("show_only_found_filetypes", "on_with_count"), "filetype_filter_off")
        strategy_key = {
            "per_post": "per_post_folders",
            "single_folder": "single_creator_folder",
            "by_file_type": "subfolders_by_file_type",
        }.get(values.get("creator_folder_strategy", "per_post"), "per_post_folders")

        return [
            (
                translate("data_directory"),
                kd_paths.data_directory(values.get("data_directory")),
                "data_directory",
            ),
            (
                translate("save_directory"),
                values.get("base_directory", ""),
                "base_directory",
            ),
            (
                translate("simultaneous_downloads"),
                values.get("simultaneous_downloads", ""),
                "simultaneous_downloads",
            ),
            (
                translate("creator_posts_max_attempts"),
                values.get("creator_posts_max_attempts", ""),
                "creator_posts_max_attempts",
            ),
            (
                translate("post_data_max_retries"),
                values.get("post_data_max_retries", ""),
                "post_data_max_retries",
            ),
            (
                translate("file_download_max_retries"),
                values.get("file_download_max_retries", ""),
                "file_download_max_retries",
            ),
            (
                translate("api_request_max_retries"),
                values.get("api_request_max_retries", ""),
                "api_request_max_retries",
            ),
            (
                translate("verbose_logging") + ":",
                enabled if values.get("verbose_logging") else disabled,
                "verbose_logging",
            ),
            (translate("language"), language_manager.get_language_name(), "language"),
            (
                translate("use_proxy") + ":",
                enabled if values.get("use_proxy") else disabled,
                "use_proxy",
            ),
            (
                translate("proxy_type"),
                str(values.get("proxy_type", "")).capitalize(),
                "proxy_type",
            ),
            (
                translate("filename_template"),
                values.get("creator_filename_template", ""),
                "creator_filename_template",
            ),
            (
                translate("filename_template_shared"),
                values.get("creator_filename_template_shared", ""),
                "creator_filename_template_shared",
            ),
            (
                translate("unique_filenames"),
                translate(_NAME_DEDUP_LABEL_KEYS.get(
                    normalize_name_dedup(values.get("creator_unique_filenames")),
                    "option_off",
                )),
                "creator_unique_filenames",
            ),
            (
                translate("folder_name_template"),
                values.get("creator_folder_name_template", ""),
                "creator_folder_name_template",
            ),
            (
                translate("folder_strategy"),
                translate(strategy_key),
                "creator_folder_strategy",
            ),
            (
                translate("show_only_found_filetypes"),
                translate(mode_key),
                "show_only_found_filetypes",
            ),
            (translate("font"), values.get("font", "JetBrains Mono"), "font"),
        ]

    def _settings_summary(self, values, baseline=None):
        """'Label: value' lines for the prompt, limited to what changed.

        With *baseline* (the settings as they were saved), only rows whose
        setting differs are listed, so the prompt reports what this apply
        changes instead of repeating every value back. Built from the settings
        rather than a fixed format string, so a new setting cannot go missing.
        """
        rows = self._settings_rows(values)
        if baseline is not None:
            rows = [
                row
                for row in rows
                if not self._same_setting_value(
                    values.get(row[2]), baseline.get(row[2])
                )
            ]
        if not rows:
            return translate("no_settings_changed")
        return "\n".join(f"{label} {value}" for label, value, _key in rows)

    def confirm_and_apply_settings(self):
        # The prompt reports changes against the settings as they were saved.
        before = self.settings.copy()
        reply = QMessageBox.question(
            self,
            translate("confirm_settings_change"),
            translate("confirm_settings_message")
            + "\n\n"
            + self._settings_summary(self.temp_settings, before),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.No:
            return

        # Create the Save Directory if it does not exist
        base_dir = self.temp_settings["base_directory"]
        if not os.path.isdir(base_dir):
            try:
                os.makedirs(base_dir, exist_ok=True)
            except OSError as e:
                QMessageBox.warning(
                    self,
                    translate("invalid_input"),
                    translate("directory_creation_failed", str(e)),
                )
                self.directory_input.setText(self.settings["base_directory"])
                self.temp_settings["base_directory"] = self.settings["base_directory"]
                return

        language_changed = self.settings["language"] != self.temp_settings["language"]
        font_changed = self.settings.get("font") != self.temp_settings.get("font")

        self.settings = self.temp_settings.copy()
        # The data folder is fixed: a value left in temp_settings (stale INI,
        # older build) must not survive Apply.
        self.settings["data_directory"] = kd_paths.data_directory()
        self.settings["use_proxy"] = (
            False  # Always keep proxy disabled in saved settings
        )
        self.save_settings()
        # Posts go straight into the Save Directory; the app's own files go to
        # the Data Directory, so the library folder only ever holds posts.
        self.parent.download_folder = self.settings["base_directory"]
        self.parent.cache_folder = kd_paths.cache_dir(
            self.settings.get("data_directory")
        )
        self.parent.other_files_folder = kd_paths.other_files_dir(
            self.settings.get("data_directory")
        )
        self.parent.ensure_folders_exist()

        creator_tab = getattr(self.parent, "creator_tab", None)
        if creator_tab is not None:
            creator_tab.cache_dir = self.parent.cache_folder
            creator_tab.other_files_dir = self.parent.other_files_folder

        if language_changed:
            language_manager.set_language(self.settings["language"])
            self.language_changed.emit()
            self.parent.log(translate("language_changed"))
            self.update_ui_text()

        if font_changed:
            self.font_changed.emit(self.settings.get("font", "JetBrains Mono"))

        self.settings_applied.emit()

        QMessageBox.information(
            self,
            translate("settings_applied"),
            translate("settings_applied_message")
            + "\n\n"
            + self._settings_summary(self.temp_settings, before),
        )

    def confirm_and_reset_settings(self):
        """Confirm and reset settings to defaults."""
        reply = QMessageBox.question(
            self,
            translate("reset_to_defaults"),
            translate("confirm_reset_message"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.reset_to_defaults()

    def reset_to_defaults(self):
        """Reset temp_settings to default values and update UI."""
        self.temp_settings = self.default_settings.copy()

        # Update UI elements to reflect default values
        self.directory_input.setText(self.temp_settings["base_directory"])
        self.data_directory_input.setText(kd_paths.data_directory())
        self.download_slider.setValue(self.temp_settings["simultaneous_downloads"])
        self.download_spinbox.setValue(self.temp_settings["simultaneous_downloads"])
        self.creator_posts_max_attempts_spinbox.setValue(
            self.temp_settings["creator_posts_max_attempts"]
        )
        self.post_data_max_retries_spinbox.setValue(
            self.temp_settings["post_data_max_retries"]
        )
        self.file_download_max_retries_spinbox.setValue(
            self.temp_settings["file_download_max_retries"]
        )
        self.api_request_max_retries_spinbox.setValue(
            self.temp_settings["api_request_max_retries"]
        )
        self.verbose_logging_checkbox.setChecked(
            bool(self.temp_settings.get("verbose_logging", False))
        )
        mode = self.temp_settings.get("show_only_found_filetypes", "on_with_count")
        self.show_only_found_filetypes_combo.blockSignals(True)
        for i in range(self.show_only_found_filetypes_combo.count()):
            if self.show_only_found_filetypes_combo.itemData(i) == mode:
                self.show_only_found_filetypes_combo.setCurrentIndex(i)
                break
        self.show_only_found_filetypes_combo.blockSignals(False)

        # Update proxy settings
        self.use_proxy_checkbox.blockSignals(True)
        self.proxy_type_combo.blockSignals(True)
        self.use_proxy_checkbox.setChecked(self.temp_settings["use_proxy"])
        self.proxy_type_combo.setCurrentIndex(
            self.get_proxy_type_index(self.temp_settings["proxy_type"])
        )
        self.use_proxy_checkbox.blockSignals(False)
        self.proxy_type_combo.blockSignals(False)
        self.custom_proxy_input.setText(self.temp_settings["custom_proxy_url"])
        self.tor_path_input.setText(self.temp_settings["tor_path"])
        self.on_use_proxy_changed(self.temp_settings["use_proxy"])

        # Update font combo box
        default_font = self.temp_settings.get("font", "JetBrains Mono")
        self.font_combo.blockSignals(True)
        for i in range(self.font_combo.count()):
            if self.font_combo.itemData(i) == default_font:
                self.font_combo.setCurrentIndex(i)
                break
        self.font_combo.blockSignals(False)

        # Creator-tab templates and the two layout dropdowns are part of the
        # defaults too: without them the page would keep showing the old
        # values while Apply saved the default ones.
        self.creator_filename_input.setText(
            self.temp_settings["creator_filename_template"]
        )
        self.creator_shared_filename_input.setText(
            self.temp_settings["creator_filename_template_shared"]
        )
        self.creator_folder_name_input.setText(
            self.temp_settings["creator_folder_name_template"]
        )
        for combo, key in (
            (self.creator_folder_strategy_combo, "creator_folder_strategy"),
            (self.creator_unique_filenames_combo, "creator_unique_filenames"),
        ):
            combo.blockSignals(True)
            index = combo.findData(self.temp_settings.get(key))
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

        QMessageBox.information(
            self, translate("reset_to_defaults"), translate("settings_reset_message")
        )

    def update_ui_text(self):
        self.folder_group.setTitle(translate("folder_settings"))
        self.directory_label.setText(translate("save_directory"))
        self.data_directory_label.setText(translate("data_directory"))
        self.data_directory_input.setToolTip(translate("data_directory_tooltip"))
        self.browse_button.setText(translate("browse"))
        self.browse_data_button.setText(translate("browse"))

        self.download_group.setTitle(translate("download_settings"))
        self.simultaneous_downloads_label.setText(translate("simultaneous_downloads"))

        self.retry_group.setTitle(translate("retry_settings"))
        self.creator_posts_max_attempts_label.setText(
            translate("creator_posts_max_attempts")
        )
        self.post_data_max_retries_label.setText(translate("post_data_max_retries"))
        self.file_download_max_retries_label.setText(
            translate("file_download_max_retries")
        )
        self.api_request_max_retries_label.setText(translate("api_request_max_retries"))
        self.verbose_logging_checkbox.setText(translate("verbose_logging"))
        self.verbose_logging_checkbox.setToolTip(translate("verbose_logging_tooltip"))
        self.show_only_found_filetypes_label.setText(
            translate("show_only_found_filetypes")
        )
        self.show_only_found_filetypes_combo.blockSignals(True)
        for index, label_key in enumerate(
            (
                "filetype_filter_off",
                "filetype_filter_on",
                "filetype_filter_on_with_count",
            )
        ):
            self.show_only_found_filetypes_combo.setItemText(
                index, translate(label_key)
            )
        self.show_only_found_filetypes_combo.blockSignals(False)
        self.show_only_found_filetypes_combo.setToolTip(
            translate("show_only_found_filetypes_tooltip")
        )

        self.update_group.setTitle(translate("update_settings"))
        self.github_repo_link.setText(
            f'<a href="{GITHUB_REPO_URL}">{translate("check_updates_on_github")}</a>'
        )

        # Creator downloader customization texts
        self.creator_custom_group.setTitle(translate("creator_downloader_settings"))
        self.creator_custom_label.setText(translate("filename_template"))
        if hasattr(self, "creator_shared_template_label"):
            self.creator_shared_template_label.setText(
                translate("filename_template_shared")
            )
        self.creator_folder_name_label.setText(
            translate("folder_name_template")
        )
        self.creator_folder_strategy_label.setText(translate("folder_strategy"))
        if hasattr(self, "creator_unique_filenames_label"):
            self.creator_unique_filenames_label.setText(translate("unique_filenames"))
        if hasattr(self, "creator_unique_filenames_combo"):
            self.creator_unique_filenames_combo.setToolTip(
                translate("unique_filenames_tooltip")
            )
            self.creator_unique_filenames_combo.blockSignals(True)
            for index in range(self.creator_unique_filenames_combo.count()):
                mode = self.creator_unique_filenames_combo.itemData(index)
                self.creator_unique_filenames_combo.setItemText(
                    index, translate(_NAME_DEDUP_LABEL_KEYS.get(mode, "option_off"))
                )
            self.creator_unique_filenames_combo.blockSignals(False)

        # Ensure folder strategy combo labels are localized
        try:
            if hasattr(self, "creator_folder_strategy_combo"):
                current_data = self.creator_folder_strategy_combo.itemData(
                    self.creator_folder_strategy_combo.currentIndex()
                )
                self.creator_folder_strategy_combo.blockSignals(True)
                self.creator_folder_strategy_combo.clear()
                self.creator_folder_strategy_combo.addItem(
                    translate("per_post_folders"), "per_post"
                )
                self.creator_folder_strategy_combo.addItem(
                    translate("single_creator_folder"), "single_folder"
                )
                self.creator_folder_strategy_combo.addItem(
                    translate("subfolders_by_file_type"), "by_file_type"
                )
                # restore selection based on data
                for i in range(self.creator_folder_strategy_combo.count()):
                    if (
                        self.creator_folder_strategy_combo.itemData(i) == current_data
                    ):  # pragma: no cover - trivial UI restore
                        self.creator_folder_strategy_combo.setCurrentIndex(i)
                        break
                self.creator_folder_strategy_combo.blockSignals(False)
        except Exception:
            pass

        # Tooltip/help for template
        if hasattr(self, "creator_template_help_btn"):
            self.creator_template_help_btn.setToolTip(
                translate("filename_template_help_title")
            )
        if hasattr(self, "creator_shared_template_help_btn"):
            self.creator_shared_template_help_btn.setToolTip(
                translate("filename_template_help_title")
            )
        if hasattr(self, "creator_folder_name_help_btn"):
            self.creator_folder_name_help_btn.setToolTip(
                translate("folder_name_template_help_title")
            )

        # Update proxy and other text

        self.font_group.setTitle(translate("font_settings"))
        self.font_label.setText(translate("font"))

        self.proxy_group.setTitle(translate("proxy_settings"))
        self.use_proxy_checkbox.setText(translate("use_proxy"))
        self.proxy_type_label.setText(translate("proxy_type"))
        self.custom_proxy_label.setText(translate("custom_proxy_url"))
        self.test_custom_proxy_button.setText(translate("test_proxy"))
        self.tor_label.setText(translate("tor_path"))
        self.browse_tor_button.setText(translate("browse"))
        self.start_tor_button.setText(translate("start_tor"))
        self.stop_tor_button.setText(translate("stop_tor"))
        self.download_tor_button.setText(translate("download_tor"))
        self.test_tor_button.setText(translate("test_tor"))
        self.tor_output_label.setText(translate("tor_output"))
        self.tor_status_label.setText(translate("tor_status_stopped"))

        self.apply_button.setText(translate("apply_changes"))
        self.reset_button.setText(translate("reset_to_defaults"))

    def get_simultaneous_downloads(self):
        return self.settings["simultaneous_downloads"]

    def get_creator_posts_max_attempts(self):
        return self.settings["creator_posts_max_attempts"]

    def get_post_data_max_retries(self):
        return self.settings["post_data_max_retries"]

    def get_file_download_max_retries(self):
        return self.settings["file_download_max_retries"]

    def get_api_request_max_retries(self):
        return self.settings["api_request_max_retries"]

    def get_verbose_logging(self):
        """True when internal debug lines should reach the log."""
        return bool(self.settings.get("verbose_logging", False))

    def get_show_only_found_filetypes(self):
        """Which filetype filter mode the Creator tab should use.

        One of "off", "on" or "on_with_count"; anything unrecognised falls
        back to "off" so a stale settings file cannot break the tab.
        """
        mode = str(self.settings.get("show_only_found_filetypes", "on_with_count"))
        return mode if mode in SHOW_ONLY_FILETYPE_MODES else "off"

    def get_creator_filename_template(self):
        """Template for files that land in a folder of their own (post folder)."""
        return self.settings.get(
            "creator_filename_template", "{post_id}_{file_number}_{orig_name}"
        )

    def get_creator_filename_template_shared(self):
        """Template for files pooled in a folder shared with other posts."""
        return self.settings.get(
            "creator_filename_template_shared",
            "{post_id}_{file_number}_{orig_name}",
        )

    def get_creator_unique_filenames(self):
        """True when a taken filename should get a _1/_2 suffix, not be replaced."""
        return normalize_name_dedup(self.settings.get("creator_unique_filenames")) in (
            "file",
            "both",
        )

    def get_creator_folder_dedup(self):
        """True when a post folder name is checked for same-run collisions."""
        return normalize_name_dedup(self.settings.get("creator_unique_filenames")) in (
            "folder",
            "both",
        )

    def get_creator_folder_strategy(self):
        return self.settings.get("creator_folder_strategy", "per_post")

    def get_creator_folder_name_template(self):
        return self.settings.get(
            "creator_folder_name_template", "{post_id}_{post_title}"
        )

    def get_font(self):
        return self.settings.get("font", "JetBrains Mono")

    def get_proxy_type_index(self, proxy_type):
        type_map = {"custom": 0, "tor": 1}
        return type_map.get(proxy_type, 1)  # Default to tor

    def is_tor_running(self):
        """Check if Tor process is currently running."""
        return (
            self.tor_process is not None
            and self.tor_process.state() == QProcess.ProcessState.Running
        )

    def on_use_proxy_changed(self, state):
        # Called both from the checkbox (an int/Qt state) and from code (a
        # bool, e.g. reset_to_defaults), so normalise before comparing.
        if isinstance(state, bool):
            enabled = state
        else:
            enabled = state == Qt.CheckState.Checked.value
        self.update_temp_setting("use_proxy", enabled)

        # Show/hide the proxy settings group (checkbox stays visible)
        self.proxy_group.setVisible(enabled)

        if enabled:
            # When enabling proxy, default to Tor if not already set
            if self.temp_settings["proxy_type"] not in ["custom", "tor"]:
                self.update_temp_setting("proxy_type", "tor")
                self.proxy_type_combo.setCurrentIndex(1)  # Tor index

            # Update UI based on current proxy type
            self.on_proxy_type_changed(self.proxy_type_combo.currentIndex())

            # Save proxy settings immediately when enabled
            self.settings["use_proxy"] = enabled
            self.settings["proxy_type"] = self.temp_settings["proxy_type"]
            self.save_settings()
        else:
            # When disabling proxy, save immediately
            self.settings["use_proxy"] = enabled
            self.save_settings()

        # Update the UI
        self.layout().update()
        self.repaint()
        self.adjustSize()

    def on_proxy_type_changed(self, index):
        proxy_type = self.proxy_type_combo.itemData(index)
        self.update_temp_setting("proxy_type", proxy_type)
        enabled = self.temp_settings["use_proxy"]

        # Show/hide widgets based on proxy type
        if proxy_type == "custom":
            self.custom_proxy_label.setVisible(enabled)
            self.custom_proxy_input.setVisible(enabled)
            self.test_custom_proxy_button.setVisible(enabled)
            # Hide Tor widgets
            self.tor_label.setVisible(False)
            self.tor_path_input.setVisible(False)
            self.browse_tor_button.setVisible(False)
            self.start_tor_button.setVisible(False)
            self.stop_tor_button.setVisible(False)
            self.download_tor_button.setVisible(False)
            self.test_tor_button.setVisible(False)
            self.help_tor_button.setVisible(False)
            self.tor_status_label.setVisible(False)
            self.tor_progress_bar.setVisible(False)
            self.tor_output_label.setVisible(False)
            self.tor_output_text.setVisible(False)
        elif proxy_type == "tor":
            # Hide custom proxy widgets
            self.custom_proxy_label.setVisible(False)
            self.custom_proxy_input.setVisible(False)
            self.test_custom_proxy_button.setVisible(False)
            # Show Tor widgets
            self.tor_label.setVisible(enabled)
            self.tor_path_input.setVisible(enabled)
            self.browse_tor_button.setVisible(enabled)
            self.start_tor_button.setVisible(enabled)
            self.stop_tor_button.setVisible(enabled)
            self.download_tor_button.setVisible(enabled)
            self.test_tor_button.setVisible(enabled)
            self.help_tor_button.setVisible(enabled)
            self.tor_status_label.setVisible(enabled)
            self.tor_progress_bar.setVisible(
                enabled and self.tor_progress_bar.isVisible()
            )
            self.tor_output_label.setVisible(enabled)
            self.tor_output_text.setVisible(enabled)

        # Enable/disable individual controls
        self.custom_proxy_input.setEnabled(enabled and proxy_type == "custom")
        self.test_custom_proxy_button.setEnabled(enabled and proxy_type == "custom")
        self.tor_path_input.setEnabled(enabled and proxy_type == "tor")
        self.browse_tor_button.setEnabled(enabled and proxy_type == "tor")
        self.download_tor_button.setEnabled(enabled and proxy_type == "tor")
        self.test_tor_button.setEnabled(enabled and proxy_type == "tor")
        self.help_tor_button.setEnabled(enabled and proxy_type == "tor")
        self.tor_progress_bar.setVisible(
            enabled and proxy_type == "tor" and self.tor_progress_bar.isVisible()
        )
        self.tor_output_label.setVisible(enabled and proxy_type == "tor")
        self.tor_output_text.setVisible(enabled and proxy_type == "tor")
        self.tor_status_label.setVisible(enabled and proxy_type == "tor")

        # Update Tor button states
        self.update_tor_button_states()

        # Save proxy_type immediately when changed
        self.settings["proxy_type"] = proxy_type
        self.save_settings()

        # Auto-detect Tor if switching to Tor and no path is set
        if (
            enabled
            and proxy_type == "tor"
            and not self.temp_settings["tor_path"].strip()
        ):
            detected_path = self.auto_detect_tor()
            if detected_path:
                self.update_temp_setting("tor_path", detected_path)
                self.tor_path_input.setText(detected_path)
                QMessageBox.information(
                    self,
                    translate("info"),
                    translate("tor_auto_detected", detected_path),
                )
                # Update button states after auto-detection
                self.update_tor_button_states()

        # Update the UI
        self.layout().update()
        self.repaint()
        self.adjustSize()

    def test_custom_proxy(self):
        proxy_url = self.temp_settings["custom_proxy_url"].strip()
        if not proxy_url:
            QMessageBox.warning(
                self, translate("error"), translate("custom_proxy_url_empty")
            )
            return

        # Test the proxy by making a request
        try:
            import requests

            proxies = {"http": proxy_url, "https": proxy_url}
            response = requests.get(
                "http://httpbin.org/ip", proxies=proxies, timeout=10
            )
            if response.status_code == 200:
                QMessageBox.information(
                    self, translate("success"), translate("proxy_test_successful")
                )
            else:
                QMessageBox.warning(
                    self,
                    translate("error"),
                    translate("proxy_test_failed", response.status_code),
                )
        except Exception as e:
            QMessageBox.warning(
                self, translate("error"), translate("proxy_test_failed", str(e))
            )

    def test_tor(self):
        tor_path = self.temp_settings["tor_path"]
        if not tor_path or not os.path.exists(tor_path):
            QMessageBox.warning(
                self, translate("error"), translate("tor_not_configured")
            )
            return

        # Check if tor executable is valid
        try:
            import subprocess

            result = subprocess.run(
                [tor_path, "--version"], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0 or "Tor" not in result.stdout:
                QMessageBox.warning(
                    self, translate("error"), translate("tor_test_failed")
                )
                return
        except Exception as e:
            QMessageBox.warning(
                self, translate("error"), translate("tor_test_failed", str(e))
            )
            return

        # Check if Tor is running as SOCKS proxy
        try:
            import requests

            # Test SOCKS5 proxy connection
            proxies = {
                "http": "socks5h://127.0.0.1:9050",
                "https": "socks5h://127.0.0.1:9050",
            }

            # Try to connect to a test service that works with Tor
            response = requests.get(
                "https://check.torproject.org/api/ip", proxies=proxies, timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("IsTor", False):
                    QMessageBox.information(
                        self, translate("success"), translate("tor_proxy_working")
                    )
                else:
                    QMessageBox.warning(
                        self,
                        translate("warning"),
                        translate("tor_executable_ok_but_proxy_not_running"),
                    )
            else:
                QMessageBox.warning(
                    self,
                    translate("warning"),
                    translate("tor_executable_ok_but_proxy_not_running"),
                )

        except ImportError:
            QMessageBox.information(
                self, translate("success"), translate("tor_test_successful")
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                translate("warning"),
                translate("tor_executable_ok_but_proxy_not_running", str(e)),
            )

    def start_tor(self):
        tor_path = self.temp_settings["tor_path"]
        if not tor_path or not os.path.exists(tor_path):
            QMessageBox.warning(
                self, translate("error"), translate("tor_not_configured")
            )
            return

        if (
            self.tor_process
            and self.tor_process.state() == QProcess.ProcessState.Running
        ):
            QMessageBox.information(
                self, translate("info"), translate("tor_already_running")
            )
            return

        # Create data directory if it doesn't exist
        if not self.tor_data_dir:
            import tempfile

            self.tor_data_dir = tempfile.mkdtemp(prefix="kemonodownloader_tor_")

        # Create a temporary torrc file to avoid using system config
        import tempfile

        self.tor_config_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".torrc", delete=False
        )
        self.tor_config_file.write(
            """SocksPort 9050
DataDirectory {data_dir}
Log notice stdout
ExitPolicy reject *:*
GeoIPExcludeUnknown 1
""".format(
                data_dir=self.tor_data_dir
            )
        )
        self.tor_config_file.close()

        # Clear previous output
        self.tor_output_text.clear()

        # Start Tor process
        self.tor_process = QProcess(self)
        self.tor_process.setProgram(tor_path)
        self.tor_process.setArguments(["--torrc-file", self.tor_config_file.name])

        self.tor_process.readyReadStandardOutput.connect(self.handle_tor_output)
        self.tor_process.readyReadStandardError.connect(self.handle_tor_error)
        self.tor_process.finished.connect(self.handle_tor_finished)
        # Tor's state is part of the proxy answer, and only the GUI thread may
        # ask for it.
        self.tor_process.stateChanged.connect(lambda *_: self._refresh_proxy_cache())

        self.tor_process.start()
        self._refresh_proxy_cache()

        # Update UI
        self.tor_status_label.setText(translate("tor_status_starting"))
        self.tor_status_label.setStyleSheet(
            "color: #FFA500; font-weight: bold; margin-left: 10px;"
        )
        self.start_tor_button.setEnabled(False)
        self.stop_tor_button.setEnabled(True)
        self.test_tor_button.setEnabled(True)
        self.tor_status_label.setText("Tor Status: Starting...")
        self.tor_status_label.setStyleSheet(
            "color: #FFD93D; font-weight: bold; margin-left: 10px;"
        )

        # Disable proxy type selection while Tor is running
        self.proxy_type_combo.setEnabled(False)

        QMessageBox.information(self, translate("info"), translate("tor_starting"))

    def stop_tor(self):
        if not self.tor_process:
            QMessageBox.warning(self, translate("error"), translate("tor_not_running"))
            return

        self.tor_process.terminate()
        if not self.tor_process.waitForFinished(5000):  # Wait up to 5 seconds
            self.tor_process.kill()
            self.tor_process.waitForFinished(2000)

        self.tor_process = None
        # Tor is gone, so a Tor proxy suddenly cannot be used any more: update
        # the worker-visible answer immediately rather than on the next change.
        self._refresh_proxy_cache()

        # Clean up temporary data directory
        if self.tor_data_dir and os.path.exists(self.tor_data_dir):
            try:
                import shutil

                shutil.rmtree(self.tor_data_dir)
                self.tor_data_dir = None
            except Exception as e:
                print(f"Failed to clean up Tor data directory: {e}")

        # Update UI
        self.start_tor_button.setEnabled(True)
        self.stop_tor_button.setEnabled(False)
        self.tor_status_label.setText(translate("tor_status_stopped"))
        self.tor_status_label.setStyleSheet(
            "color: #FF6B6B; font-weight: bold; margin-left: 10px;"
        )

        # Re-enable proxy type selection
        self.proxy_type_combo.setEnabled(True)

        QMessageBox.information(self, translate("info"), translate("tor_stopped"))

    def show_tor_help(self):
        """Show help modal with Tor setup instructions."""
        help_text = """<b>How to set up Tor for downloading:</b><br><br>
1. First Click <b>Download Tor</b> to download the Tor browser<br>
2. Wait for the download to complete<br>
3. Click <b>Start Tor</b> to start the Tor process<br>
4. Click <b>Test Tor</b> to verify Tor is working<br>
5. You can start downloading now with Tor proxy enabled<br><br>
<b>Note:</b> Tor provides anonymity but may be slower than direct connections."""

        QMessageBox.information(self, "Tor Setup Help", help_text)

    def download_tor(self):
        try:
            # Determine the Tor download URL based on platform
            if sys.platform == "win32":
                # Tor expert bundle for Windows
                tor_url = "https://archive.torproject.org/tor-package-archive/torbrowser/15.0.3/tor-expert-bundle-windows-x86_64-15.0.3.tar.gz"
                tor_extract_dir = "tor-expert-bundle-windows-x86_64-15.0.3"
            elif sys.platform == "darwin":
                # Check for Apple Silicon vs Intel
                import platform

                machine = platform.machine().lower()
                if machine == "arm64":
                    tor_url = "https://archive.torproject.org/tor-package-archive/torbrowser/15.0.3/tor-expert-bundle-macos-aarch64-15.0.3.tar.gz"
                    tor_extract_dir = "tor-expert-bundle-macos-aarch64-15.0.3"
                else:
                    tor_url = "https://archive.torproject.org/tor-package-archive/torbrowser/15.0.3/tor-expert-bundle-macos-x86_64-15.0.3.tar.gz"
                    tor_extract_dir = "tor-expert-bundle-macos-x86_64-15.0.3"
            else:  # Linux
                tor_url = "https://archive.torproject.org/tor-package-archive/torbrowser/15.0.3/tor-expert-bundle-linux-x86_64-15.0.3.tar.gz"
                tor_extract_dir = "tor-expert-bundle-linux-x86_64-15.0.3"

            # Create tor directory in the app's data folder
            tor_path = os.path.join(
                kd_paths.data_directory(self.temp_settings.get("data_directory")),
                "Tor",
            )
            os.makedirs(tor_path, exist_ok=True)

            # Show progress bar and disable button
            self.tor_progress_bar.setVisible(True)
            self.tor_progress_bar.setValue(0)
            self.download_tor_button.setEnabled(False)
            self.download_tor_button.setText(translate("downloading"))

            # Download Tor with progress tracking
            QMessageBox.information(
                self, translate("info"), translate("downloading_tor")
            )

            # Start download thread
            self.download_thread = DownloadTorThread(tor_url, tor_extract_dir, tor_path)
            self.download_thread.progress.connect(self.tor_progress_bar.setValue)
            self.download_thread.finished_success.connect(self.on_tor_download_success)
            self.download_thread.finished_error.connect(self.on_tor_download_error)

            # Disable buttons during download
            self.download_started.emit()
            self.test_tor_button.setEnabled(False)
            self.start_tor_button.setEnabled(False)
            self.stop_tor_button.setEnabled(False)
            # self.help_tor_button.setEnabled(False)  # Keep help always available

            self.download_thread.start()

        except Exception as e:
            # Hide progress bar and re-enable button on error
            self.tor_progress_bar.setVisible(False)
            self.download_tor_button.setEnabled(True)
            self.download_tor_button.setText(translate("download_tor"))
            self.download_finished.emit()
            QMessageBox.warning(
                self, translate("error"), translate("tor_download_failed", str(e))
            )

    def on_tor_download_success(self, tor_exe):
        self.download_finished.emit()
        # Hide progress bar and re-enable button
        self.tor_progress_bar.setVisible(False)
        self.download_tor_button.setEnabled(True)
        self.download_tor_button.setText(translate("download_tor"))

        self.update_temp_setting("tor_path", tor_exe)
        self.tor_path_input.setText(tor_exe)
        QMessageBox.information(
            self, translate("success"), translate("tor_download_successful")
        )
        self.update_tor_button_states()

    def on_tor_download_error(self, error_msg):
        self.download_finished.emit()
        # Hide progress bar and re-enable button on error
        self.tor_progress_bar.setVisible(False)
        self.download_tor_button.setEnabled(True)
        self.download_tor_button.setText(translate("download_tor"))
        if error_msg == "tor_exe_not_found":
            QMessageBox.warning(
                self, translate("error"), translate("tor_exe_not_found")
            )
        else:
            QMessageBox.warning(
                self, translate("error"), translate("tor_download_failed", error_msg)
            )

    def update_tor_button_states(self):
        tor_path = self.temp_settings["tor_path"]
        tor_exists = bool(tor_path and os.path.exists(tor_path))

        self.test_tor_button.setEnabled(bool(tor_exists))
        self.download_tor_button.setVisible(
            not tor_exists
        )  # Hide download button if Tor is already available

        if (
            self.tor_process
            and self.tor_process.state() == QProcess.ProcessState.Running
        ):
            self.start_tor_button.setEnabled(False)
            self.stop_tor_button.setEnabled(True)
        else:
            self.start_tor_button.setEnabled(bool(tor_exists))
            self.stop_tor_button.setEnabled(False)

    def handle_tor_output(self):
        if self.tor_process:
            output = (
                self.tor_process.readAllStandardOutput()
                .data()
                .decode("utf-8", errors="ignore")
            )
            if output.strip():
                # Append to text area
                self.tor_output_text.append(output.strip())
                # Auto-scroll to bottom
                scrollbar = self.tor_output_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

                # Check for bootstrap completion
                if "Bootstrapped 100%" in output:
                    self.tor_status_label.setText(translate("tor_status_running"))
                    self.tor_status_label.setStyleSheet(
                        "color: #6BCF7F; font-weight: bold; margin-left: 10px;"
                    )
                    QMessageBox.information(
                        self, translate("success"), translate("tor_running")
                    )

    def handle_tor_error(self):
        if self.tor_process:
            error = (
                self.tor_process.readAllStandardError()
                .data()
                .decode("utf-8", errors="ignore")
            )
            if error.strip():
                # Append error to text area
                self.tor_output_text.append(f"[ERROR] {error.strip()}")
                # Auto-scroll to bottom
                scrollbar = self.tor_output_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

    def handle_tor_finished(self, exit_code, exit_status):
        self.tor_process = None
        self._refresh_proxy_cache()

        # Clean up temporary data directory
        if self.tor_data_dir and os.path.exists(self.tor_data_dir):
            try:
                import shutil

                shutil.rmtree(self.tor_data_dir)
                self.tor_data_dir = None
            except Exception as e:
                print(f"Failed to clean up Tor data directory: {e}")

        # Clean up temporary config file
        if hasattr(self, "tor_config_file") and os.path.exists(
            self.tor_config_file.name
        ):
            try:
                os.unlink(self.tor_config_file.name)
            except Exception as e:
                print(f"Failed to clean up Tor config file: {e}")

        self.start_tor_button.setEnabled(True)
        self.stop_tor_button.setEnabled(False)
        self.tor_status_label.setText(translate("tor_status_stopped"))
        self.tor_status_label.setStyleSheet(
            "color: #FF6B6B; font-weight: bold; margin-left: 10px;"
        )

    def get_proxy_settings(self):
        """Return proxy settings for use with requests.

        Safe to call from a download thread: the answer is cached on the GUI
        thread whenever proxy state changes, because deciding it here used to
        mean touching ``QProcess.state()`` off the GUI thread (undefined
        behaviour) and re-running ``importlib`` on every request.

        ``None`` means "no proxy is configured", which is the only case where
        a direct connection is correct. When a proxy *is* enabled but cannot be
        used, this raises ``ProxyUnavailableError``: returning None there made
        the session drop its proxy and talk to the network on the user's real
        address, which is the opposite of what enabling a proxy asks for.
        """
        cached = getattr(self, "_proxy_cache", None)
        if cached is not None and cached[0] == self._proxy_signature():
            kind, value = cached[1], cached[2]
            if kind == "error":
                raise value
            return value
        # Settings or the Tor process changed since the snapshot was taken
        # (a direct mutation, or a mock): answer from live state instead.
        return SettingsTab._compute_proxy_settings(self)

    @staticmethod
    def _compute_proxy_settings(settings_tab):
        """Resolve the configured proxy. GUI thread, or a mock, only."""
        # temp_settings is the live copy - every widget edit lands there,
        # while self.settings only changes on Apply. Reading the saved copy
        # first made an edited custom-proxy URL invisible until Apply.
        settings_to_check = dict(settings_tab.settings)
        settings_to_check.update(settings_tab.temp_settings)

        if not settings_to_check.get("use_proxy"):
            return None

        if settings_to_check["proxy_type"] == "custom":
            proxy_url = (settings_to_check.get("custom_proxy_url") or "").strip()
            if proxy_url:
                return {"http": proxy_url, "https": proxy_url}
            raise ProxyUnavailableError(translate("proxy_custom_url_empty_error"))
        elif settings_to_check["proxy_type"] == "tor":
            # Check if Tor is actually running
            tor_process = getattr(settings_tab, "tor_process", None)
            if (
                not tor_process
                or tor_process.state() != QProcess.ProcessState.Running
            ):
                raise ProxyUnavailableError(translate("proxy_tor_not_running_error"))

            # For Tor, we need to use SOCKS5h proxy (resolves DNS through Tor)
            # Note: This requires requests[socks] or PySocks to be installed
            import importlib.util

            if importlib.util.find_spec("socks") is not None:
                return {
                    "http": "socks5h://127.0.0.1:9050",
                    "https": "socks5h://127.0.0.1:9050",
                }
            # Privoxy-style HTTP fallback. It fails closed on its own: nothing
            # answers there unless Privoxy is actually running.
            return {
                "http": "http://127.0.0.1:8118",  # Privoxy default
                "https": "http://127.0.0.1:8118",
            }
        return None


class DownloadTorThread(QThread):
    progress = pyqtSignal(int)
    finished_success = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def __init__(self, tor_url, tor_extract_dir, tor_path):
        super().__init__()
        self.tor_url = tor_url
        self.tor_extract_dir = tor_extract_dir
        self.tor_path = tor_path

    def run(self):
        import tarfile
        import tempfile

        import requests

        try:
            response = requests.get(self.tor_url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded_size = 0

            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".tar.gz"
            ) as tmp_file:
                tmp_archive = tmp_file.name
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        tmp_file.write(chunk)
                        downloaded_size += len(chunk)
                        if total_size > 0:
                            progress = int((downloaded_size / total_size) * 100)
                            self.progress.emit(progress)

            # Extract Tor
            self.progress.emit(100)

            with tarfile.open(tmp_archive, "r:gz") as tar_ref:
                # Safely extract files to avoid path traversal vulnerabilities.
                def _is_within_directory(directory, target):
                    abs_directory = os.path.abspath(directory)
                    abs_target = os.path.abspath(target)
                    try:
                        return os.path.commonpath(
                            [abs_directory]
                        ) == os.path.commonpath([abs_directory, abs_target])
                    except Exception:
                        return False

                for member in tar_ref.getmembers():
                    member_path = os.path.join(self.tor_path, member.name)
                    if not _is_within_directory(self.tor_path, member_path):
                        # Skip unsafe member
                        continue
                    tar_ref.extract(member, self.tor_path)

            # Clean up
            os.unlink(tmp_archive)

            # Find tor executable - search entire extracted directory tree
            tor_exe = None
            for root, dirs, files in os.walk(self.tor_path):
                for f in files:
                    if f.lower() in ("tor.exe", "tor"):
                        tor_exe = os.path.join(root, f)
                        break
                if tor_exe:
                    break

            if tor_exe:
                self.finished_success.emit(tor_exe)
            else:
                self.finished_error.emit("tor_exe_not_found")

        except Exception as e:
            self.finished_error.emit(str(e))
