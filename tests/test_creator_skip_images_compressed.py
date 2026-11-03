"""Tests for the "Skip Images if Compressed" download option.

Images are only dropped when a compressed archive is among the files actually
being downloaded, so a post whose ZIP was not selected keeps its images.
"""

from types import SimpleNamespace

import kemonodownloader.creator_downloader as cd

DOMAIN_CONFIG = {
    "base_url": "https://kemono.cr",
    "referer": "https://kemono.cr/",
    "api_base": "https://kemono.cr/api/v1",
    "domain": "kemono.cr",
}


def _thread(skip_images_if_compressed):
    return cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks={},
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=1, settings_tab=None),
        skip_images_if_compressed=skip_images_if_compressed,
    )


POST = {
    "id": "p1",
    "title": "Title",
    "file": {"path": "/media/1.png", "name": "img1.png"},
    "attachments": [
        {"path": "/att/2.zip", "name": "file2.zip"},
        {"path": "/att/3.jpg", "name": "extra.jpg"},
    ],
    "content": "<p><img src='/content/4.gif'/></p>",
}


def _names(files):
    return sorted(name for name, _ in files)


def test_images_are_kept_by_default(qapp):
    files = _thread(False).detect_files(
        POST, [".png", ".jpg", ".gif", ".zip"], DOMAIN_CONFIG
    )

    assert _names(files) == ["4.gif", "extra.jpg", "file2.zip", "img1.png"]


def test_images_are_skipped_when_an_archive_is_selected(qapp):
    files = _thread(True).detect_files(
        POST, [".png", ".jpg", ".gif", ".zip"], DOMAIN_CONFIG
    )

    assert _names(files) == ["file2.zip"]


def test_images_are_kept_when_the_archive_is_not_selected(qapp):
    files = _thread(True).detect_files(POST, [".png", ".jpg", ".gif"], DOMAIN_CONFIG)

    assert _names(files) == ["4.gif", "extra.jpg", "img1.png"]


def test_non_image_files_survive_the_archive(qapp):
    post = {
        "id": "p2",
        "file": {"path": "/media/movie.mp4", "name": "movie.mp4"},
        "attachments": [{"path": "/att/pack.rar", "name": "pack.rar"}],
    }
    files = _thread(True).detect_files(post, [".mp4", ".rar"], DOMAIN_CONFIG)

    assert _names(files) == ["movie.mp4", "pack.rar"]


def test_helper_is_a_no_op_when_disabled(qapp):
    files = [("a.png", "https://kemono.cr/a.png"), ("b.zip", "https://kemono.cr/b.zip")]

    assert _thread(False)._drop_images_when_archive_present(files) == files
    assert _thread(True)._drop_images_when_archive_present(files) == [
        ("b.zip", "https://kemono.cr/b.zip")
    ]


def test_translations_exist_for_the_option():
    from kemonodownloader.kd_language import language_manager, translate

    keys = [
        "skip_images_if_compressed",
        "skip_images_info_title",
        "skip_images_info_text",
        "images_skipped_archive_present",
    ]
    original = language_manager.current_language
    try:
        for language in language_manager.get_available_languages():
            language_manager.set_language(language)
            for key in keys:
                assert translate(key, 1) not in ("", key)
    finally:
        language_manager.set_language(original)
