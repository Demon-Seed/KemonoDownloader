"""The app keeps its own working files away from the user's posts.

Cache/ and Other Files/ hold thumbnails and the two SQLite databases. They must
not live inside the Save Directory: pointing that at a library has to leave the
folder holding only saved posts, and repointing it must not lose the
duplicate/naming memory.
"""

import os
import sys

import pytest

from kemonodownloader import kd_paths


def test_windows_default_is_appdata(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\someone\AppData\Roaming")

    assert kd_paths.default_data_directory() == os.path.join(
        r"C:\Users\someone\AppData\Roaming", "Kemono Downloader"
    )


def test_macos_default_is_application_support(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    # The path is written with forward slashes, as macOS uses.
    assert (
        kd_paths.default_data_directory().replace("\\", "/")
        .endswith("Library/Application Support/Kemono Downloader")
    )


def test_linux_default_is_under_xdg_data_home(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/home/user/.local/share")

    assert kd_paths.default_data_directory() == os.path.join(
        "/home/user/.local/share", "Kemono Downloader"
    )


def test_configured_directory_wins_over_the_default(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\someone\AppData\Roaming")
    monkeypatch.delenv(kd_paths.DATA_DIR_ENV, raising=False)

    assert kd_paths.data_directory("/media/library/appdata") == "/media/library/appdata"


def test_environment_override_wins_over_the_setting(monkeypatch):
    """Tests rely on this to stay out of the real profile."""
    monkeypatch.setenv(kd_paths.DATA_DIR_ENV, "/tmp/isolated")

    assert kd_paths.data_directory("/media/library/appdata") == "/tmp/isolated"


def test_a_blank_setting_falls_back_to_the_default(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\someone\AppData\Roaming")
    monkeypatch.delenv(kd_paths.DATA_DIR_ENV, raising=False)

    assert kd_paths.data_directory("") == kd_paths.default_data_directory()
    assert kd_paths.data_directory(None) == kd_paths.default_data_directory()


def test_cache_and_other_files_sit_inside_the_data_directory(monkeypatch):
    monkeypatch.delenv(kd_paths.DATA_DIR_ENV, raising=False)

    assert kd_paths.cache_dir("/data") == os.path.join("/data", "Cache")
    assert kd_paths.other_files_dir("/data") == os.path.join("/data", "Other Files")
    # Never inside the Save Directory: the two settings are independent.
    assert not kd_paths.cache_dir("/data").startswith("/posts")
    assert not kd_paths.other_files_dir("/data").startswith("/posts")


@pytest.mark.parametrize("name", ["Cache", "Other Files"])
def test_data_directories_are_named_as_before(monkeypatch, name):
    monkeypatch.delenv(kd_paths.DATA_DIR_ENV, raising=False)

    resolved = {
        "Cache": kd_paths.cache_dir("/data"),
        "Other Files": kd_paths.other_files_dir("/data"),
    }[name]

    assert os.path.basename(resolved) == name
