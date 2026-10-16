"""Regression tests for the auto-rename prefix when posts share a folder.

The per-post ``page_number`` restarts at 1 for every post. In a folder that
is shared with other posts (``single_folder``, ``by_file_type``, or a
per-post download whose post folder was skipped) the bare page number would
interleave the posts::

    1_a, 1_b, 2_a, 2_b

so the post's *selection order* is prepended, keeping every post a
contiguous, internally ordered block::

    1_1_a, 1_2_a, 2_1_b

In a per-post folder the folder itself already keeps the post together, so
the plain page number is kept. The prefix is intentionally not zero-padded.
"""

import os
from types import SimpleNamespace

from kemonodownloader.creator_downloader import CreatorDownloadThread

FILES = {
    "1": ["https://kemono.cr/files/a1.jpg", "https://kemono.cr/files/a2.jpg"],
    "2": ["https://kemono.cr/files/b1.jpg"],
}


def make_settings(strategy="per_post", template="{orig_name}"):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: template,
        get_creator_folder_strategy=lambda: strategy,
    )
    return SimpleNamespace(settings_tab=settings_tab)


def make_thread(
    tmp_path,
    strategy="per_post",
    template="{orig_name}",
    posts=("1", "2"),
    post_files=None,
    files_to_download=None,
    files_to_posts_map=None,
    auto_rename=True,
    skip_folder_enabled=False,
    skip_folder_threshold=1,
    force_folder_for_compressed=False,
):
    """Build a real thread over *posts* (selection order) and their files.

    Pass *files_to_download* / *files_to_posts_map* explicitly to simulate a
    flat download list whose cross-post order does not match the selection
    order (which is what concurrent detection produces).
    """
    if files_to_download is None:
        post_files = post_files if post_files is not None else FILES
        files_to_download = []
        files_to_posts_map = {}
        for post_id in posts:
            for url in post_files.get(post_id, []):
                files_to_download.append(url)
                files_to_posts_map[url] = post_id

    thread = CreatorDownloadThread(
        service="svc",
        creator_id="42",
        download_folder=str(tmp_path / "dl"),
        selected_posts=list(posts),
        files_to_download=list(files_to_download),
        files_to_posts_map=dict(files_to_posts_map),
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={("svc", "42", pid): f"Post {pid}" for pid in posts},
        auto_rename_enabled=auto_rename,
        settings=make_settings(strategy, template),
        max_concurrent=1,
        skip_folder_enabled=skip_folder_enabled,
        skip_folder_threshold=skip_folder_threshold,
        force_folder_for_compressed=force_folder_for_compressed,
    )
    thread.creator_name = "Creator"
    return thread


def enqueue_plan(thread):
    """Replicate the queue seeding in ``CreatorDownloadThread.run()``.

    Returns ``(file_index, file_url, post_id, page_number)`` tuples in
    download order, where ``page_number`` is the per-post counter that feeds
    the auto-rename prefix.
    """
    counts = {}
    plan = []
    for file_index, file_url in enumerate(thread.files_to_download):
        post_id = thread.files_to_posts_map.get(file_url)
        counts[post_id] = counts.get(post_id, 0) + 1
        plan.append((file_index, file_url, post_id, counts[post_id]))
    return plan


def generate(thread, folder):
    """Return ``(filename, target_folder)`` for every queued file."""
    total = len(thread.files_to_download)
    results = []
    for file_index, file_url, post_id, page_number in enqueue_plan(thread):
        target_folder, filename = thread.generate_filename_and_folder(
            file_url,
            folder,
            file_index,
            total,
            post_id,
            f"Post {post_id}",
            page_number,
        )
        results.append((filename, target_folder))
    return results



def test_single_folder_prepends_post_order(tmp_path):
    thread = make_thread(tmp_path, strategy="single_folder")
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "1_1_a1.jpg",
        "1_2_a2.jpg",
        "2_1_b1.jpg",
    ]
    # Every file of a shared folder goes to the creator folder itself.
    for _, folder in results:
        assert os.path.basename(folder) == "42_Creator"


def test_by_file_type_prepends_post_order(tmp_path):
    post_files = {
        "1": ["https://kemono.cr/files/a1.jpg", "https://kemono.cr/files/a2.png"],
        "2": ["https://kemono.cr/files/b1.jpg"],
    }
    thread = make_thread(tmp_path, strategy="by_file_type", post_files=post_files)
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "1_1_a1.jpg",
        "1_2_a2.png",
        "2_1_b1.jpg",
    ]
    assert [os.path.basename(folder) for _, folder in results] == [
        "jpg",
        "png",
        "jpg",
    ]


def test_per_post_folder_keeps_bare_page_number(tmp_path):
    thread = make_thread(tmp_path, strategy="per_post")
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "1_a1.jpg",
        "2_a2.jpg",
        "1_b1.jpg",
    ]
    # Files stay inside their own post folder.
    assert [os.path.basename(folder) for _, folder in results] == [
        "1_Post_1",
        "1_Post_1",
        "2_Post_2",
    ]



def test_skip_folder_prepends_post_order_for_shared_posts(tmp_path):
    # Per-post strategy, but post "1" has a single file and therefore skips
    # its own folder, so both posts end up in the creator folder.
    post_files = {
        "1": ["https://kemono.cr/files/a1.jpg"],
        "2": ["https://kemono.cr/files/b1.jpg", "https://kemono.cr/files/b2.jpg"],
    }
    thread = make_thread(
        tmp_path,
        strategy="per_post",
        post_files=post_files,
        skip_folder_enabled=True,
        skip_folder_threshold=1,
    )
    results = generate(thread, str(tmp_path / "dl"))

    # Post 1 was skipped into the shared creator folder -> two-level prefix.
    assert results[0] == (
        "1_1_a1.jpg",
        os.path.join(str(tmp_path / "dl"), "42_Creator"),
    )
    # Post 2 kept its own folder -> bare page number.
    assert [name for name, _ in results[1:]] == ["1_b1.jpg", "2_b2.jpg"]
    for _, folder in results[1:]:
        assert os.path.basename(folder) == "2_Post_2"


def test_skip_folder_blocks_compressed_when_forced(tmp_path):
    # force_folder_for_compressed keeps archives in their own per-post folder,
    # even when skip-folder would otherwise apply.
    post_files = {
        "1": ["https://kemono.cr/files/a.zip"],
        "2": ["https://kemono.cr/files/b1.jpg"],
    }
    thread = make_thread(
        tmp_path,
        strategy="per_post",
        post_files=post_files,
        skip_folder_enabled=True,
        skip_folder_threshold=1,
        force_folder_for_compressed=True,
    )
    results = generate(thread, str(tmp_path / "dl"))

    # The archive kept a per-post folder -> bare page number.
    assert results[0] == (
        "1_a.zip",
        os.path.join(str(tmp_path / "dl"), "42_Creator", "1_Post_1"),
    )
    # The image was skipped into the shared creator folder -> two-level prefix.
    assert results[1] == (
        "2_1_b1.jpg",
        os.path.join(str(tmp_path / "dl"), "42_Creator"),
    )


def test_prefix_follows_selection_order_not_flat_file_order(tmp_path):
    # files_to_download is assembled by concurrent detection threads, so its
    # cross-post order is arbitrary. Post "2" comes first in the flat list but
    # second in the selection order, so it must be prefixed 2_.
    files = ["https://kemono.cr/files/b1.jpg", "https://kemono.cr/files/a1.jpg"]
    thread = make_thread(
        tmp_path,
        strategy="single_folder",
        posts=("1", "2"),
        files_to_download=files,
        files_to_posts_map={files[0]: "2", files[1]: "1"},
    )
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == ["2_1_b1.jpg", "1_1_a1.jpg"]


def test_prefix_is_not_zero_padded(tmp_path):
    thread = make_thread(tmp_path, strategy="single_folder")
    results = generate(thread, str(tmp_path / "dl"))
    # No 001_/002_ padding: the viewer's natural sort handles ordering.
    assert not any(name.startswith(("001_", "002_")) for name, _ in results)
    assert results[0][0].startswith("1_1_")


def test_post_order_map_follows_selection_order(tmp_path):
    thread = make_thread(tmp_path, posts=("5", "2", "9"))
    assert thread.post_order_map == {"5": 1, "2": 2, "9": 3}


def test_post_order_map_appends_unlisted_posts(tmp_path):
    # A file whose url is missing from files_to_posts_map falls back to the
    # creator id in download_file, so that id needs a stable slot too.
    thread = make_thread(
        tmp_path,
        posts=("1",),
        files_to_download=["https://kemono.cr/files/a1.jpg"],
        files_to_posts_map={"https://kemono.cr/files/a1.jpg": "1"},
    )
    assert thread.post_order_map == {"1": 1}


def test_get_post_order_is_stable_for_unknown_ids(tmp_path):
    thread = make_thread(tmp_path, posts=("1",))
    assert thread.get_post_order("1") == 1
    assert thread.get_post_order("999") == 2
    # Cached: repeated calls do not keep growing the order.
    assert thread.get_post_order("999") == 2


def test_skip_folder_mixed_post_shared_block_stays_contiguous(tmp_path):
    # One post with mixed contents: the forced archive keeps its own per-post
    # folder while its skipped siblings share the creator folder. The per-post
    # page counter keeps running, so the shared block may start above 1 -- what
    # matters is that it stays contiguous and internally ordered.
    post_files = {
        "1": [
            "https://kemono.cr/files/a.rar",
            "https://kemono.cr/files/b1.jpg",
            "https://kemono.cr/files/b2.jpg",
        ],
    }
    thread = make_thread(
        tmp_path,
        strategy="per_post",
        posts=("1",),
        post_files=post_files,
        skip_folder_enabled=True,
        skip_folder_threshold=3,
        force_folder_for_compressed=True,
    )
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "1_a.rar",
        "1_2_b1.jpg",
        "1_3_b2.jpg",
    ]
    # Archive kept its own folder -> bare page number.
    assert results[0][1] == os.path.join(
        str(tmp_path / "dl"), "42_Creator", "1_Post_1"
    )
    # Siblings were skipped into the shared creator folder -> two-level prefix.
    for _, folder in results[1:]:
        assert folder == os.path.join(str(tmp_path / "dl"), "42_Creator")
