from types import SimpleNamespace
from unittest.mock import MagicMock

import kemonodownloader.creator_downloader as cd


def test_template_bad_placeholder_fallsback_and_logs(tmp_path, qapp):
    """If the user-provided filename template raises during formatting,
    the code should log a warning and fall back to a safe default."""
    file_url = "https://kemono.cr/files/foo.png"
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{post_id}_{nonexistent}",
        get_creator_folder_strategy=lambda: "per_post",
    )
    settings = SimpleNamespace(settings_tab=settings_tab)

    post_titles = {("svc", "creator123", "1"): "My Post"}

    th = cd.CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map=post_titles,
        settings=settings,
    )

    # Capture log emits
    th.log = SimpleNamespace(emit=MagicMock())

    _target_folder, filename = th.generate_filename_and_folder(
        file_url, str(tmp_path / "dl"), 0, 1, "1", "My Post", page_number=1
    )

    # Should fall back to post_id + original name (orig_name from URL 'foo')
    assert filename.endswith("1_foo.png")
    # Ensure a warning was emitted about template error
    assert th.log.emit.called


def test_template_format_exception_falls_back_without_a_prefix(tmp_path, qapp):
    """A broken template falls back to post id + original name.

    The fallback carries no number prefix any more: numbering is part of the
    template now, so there is nothing to prepend.
    """
    file_url = "https://kemono.cr/files/bar.jpg"
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{missing_field}",
        get_creator_folder_strategy=lambda: "per_post",
    )
    settings = SimpleNamespace(settings_tab=settings_tab)

    post_titles = {("svc", "creatorX", "42"): "Some Post"}

    th = cd.CreatorDownloadThread(
        service="svc",
        creator_id="creatorX",
        download_folder=str(tmp_path / "dl2"),
        selected_posts=["42"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "42"},
        console=None,
        other_files_dir=str(tmp_path / "other2"),
        post_titles_map=post_titles,
        settings=settings,
    )

    th.log = SimpleNamespace(emit=MagicMock())

    _, fname1 = th.generate_filename_and_folder(
        file_url, str(tmp_path / "dl2"), 0, 1, "42", "Some Post", page_number=1
    )
    assert fname1 == "42_bar.jpg"
    assert th.log.emit.called
