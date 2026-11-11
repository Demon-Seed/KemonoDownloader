"""One filename template per kind of folder.

Files that land in a post's own folder use the post-folder template. Files that
land in a folder shared with other posts - ``single_folder``, ``by_file_type``,
or a per-post download whose post folder was skipped - use the shared template,
which is what tells one post's files from another (``{post_id}`` or
``{post_date}``). Nothing is prepended behind the user's back any more, and the
defaults reproduce the old "Rename & Sort by File order" output.
"""

import os
from types import SimpleNamespace

from kemonodownloader.creator_downloader import CreatorDownloadThread

POST = "174816708"
OLDER_POST = "174700000"

FILES = {
    POST: ["https://kemono.cr/files/a1.jpg", "https://kemono.cr/files/a2.jpg"],
    OLDER_POST: ["https://kemono.cr/files/b1.jpg"],
}

POST_TEMPLATE = "{file_number}_{post_id}_{orig_name}"
SHARED_TEMPLATE = "{post_id}_{file_number}_{orig_name}"


def make_settings(
    strategy="per_post",
    template=POST_TEMPLATE,
    shared=SHARED_TEMPLATE,
    unique=True,
):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: template,
        get_creator_filename_template_shared=lambda: shared,
        get_creator_folder_strategy=lambda: strategy,
        get_creator_unique_filenames=lambda: unique,
    )
    return SimpleNamespace(settings_tab=settings_tab)


def make_thread(
    tmp_path,
    strategy="per_post",
    template=POST_TEMPLATE,
    shared=SHARED_TEMPLATE,
    posts=(POST, OLDER_POST),
    post_files=None,
    skip_folder_enabled=False,
    skip_folder_threshold=1,
    force_folder_for_compressed=False,
    post_dates_map=None,
    data_dir="other",
    unique=True,
):
    if post_files is None:
        post_files = FILES
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
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=str(tmp_path / data_dir),
        post_titles_map={("svc", "42", pid): f"Post {pid}" for pid in posts},
        settings=make_settings(strategy, template, shared, unique),
        max_concurrent=1,
        skip_folder_enabled=skip_folder_enabled,
        skip_folder_threshold=skip_folder_threshold,
        force_folder_for_compressed=force_folder_for_compressed,
        post_dates_map=post_dates_map,
    )
    thread.creator_name = "Creator"
    return thread


def enqueue_plan(thread):
    """Replicate the queue seeding in ``CreatorDownloadThread.run()``.

    Returns ``(file_index, file_url, post_id, file_number)`` tuples in download
    order, where ``file_number`` is the per-post counter the template reads.
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


def names(thread, folder):
    return [name for name, _ in generate(thread, folder)]


def test_post_folder_uses_the_post_template(tmp_path):
    thread = make_thread(tmp_path, strategy="per_post")
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "1_174816708_a1.jpg",
        "2_174816708_a2.jpg",
        "1_174700000_b1.jpg",
    ]
    # Each post keeps its own folder, so the folder name starts with the post's
    # id (the rest comes from the folder-name template).
    assert [
        os.path.basename(folder).split("_")[0] for _, folder in results
    ] == [POST, POST, OLDER_POST]


def test_single_folder_uses_the_shared_template(tmp_path):
    thread = make_thread(tmp_path, strategy="single_folder")
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "174816708_1_a1.jpg",
        "174816708_2_a2.jpg",
        "174700000_1_b1.jpg",
    ]
    for _, folder in results:
        assert os.path.basename(folder) == "42_Creator"


def test_by_file_type_uses_the_shared_template(tmp_path):
    post_files = {
        POST: ["https://kemono.cr/files/a1.jpg", "https://kemono.cr/files/a2.png"],
        OLDER_POST: ["https://kemono.cr/files/b1.jpg"],
    }
    thread = make_thread(tmp_path, strategy="by_file_type", post_files=post_files)
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "174816708_1_a1.jpg",
        "174816708_2_a2.png",
        "174700000_1_b1.jpg",
    ]
    assert [os.path.basename(folder) for _, folder in results] == ["jpg", "png", "jpg"]


def test_skipped_post_folder_uses_the_shared_template(tmp_path):
    # A one-file post drops into the creator folder, so it needs the shared
    # template to stay apart from the other post's files.
    thread = make_thread(
        tmp_path,
        strategy="per_post",
        skip_folder_enabled=True,
        skip_folder_threshold=1,
    )
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "1_174816708_a1.jpg",
        "2_174816708_a2.jpg",
        "174700000_1_b1.jpg",
    ]
    assert [
        os.path.basename(folder).split("_")[0] for _, folder in results
    ] == [POST, POST, "42"]


def test_forced_archive_keeps_the_post_template(tmp_path):
    # The archive keeps its own post folder while the rest of the post is
    # skipped into the creator folder, so the two use different templates.
    post_files = {
        POST: [
            "https://kemono.cr/files/a.rar",
            "https://kemono.cr/files/b1.jpg",
            "https://kemono.cr/files/b2.jpg",
        ]
    }
    thread = make_thread(
        tmp_path,
        strategy="per_post",
        posts=(POST,),
        post_files=post_files,
        skip_folder_enabled=True,
        skip_folder_threshold=3,
        force_folder_for_compressed=True,
    )
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "1_174816708_a.rar",
        "174816708_2_b1.jpg",
        "174816708_3_b2.jpg",
    ]
    # The archive sits in the post folder, the siblings in the creator folder.
    creator_folder = os.path.join(str(tmp_path / "dl"), "42_Creator")
    assert os.path.dirname(results[0][1]) == creator_folder
    assert os.path.basename(results[0][1]).startswith(POST)
    for _, folder in results[1:]:
        assert folder == creator_folder


def test_selection_order_does_not_change_the_names(tmp_path):
    """Re-downloading a different set must not rename an already-saved post."""
    first = make_thread(tmp_path, strategy="single_folder", posts=(POST,))
    first_names = names(first, str(tmp_path / "dl"))

    second = make_thread(tmp_path, strategy="single_folder", posts=(OLDER_POST, POST))
    again = [name for name in names(second, str(tmp_path / "dl")) if POST in name]

    assert first_names == ["174816708_1_a1.jpg", "174816708_2_a2.jpg"]
    assert again == first_names


def test_a_wiped_data_folder_reproduces_the_same_names(tmp_path):
    """Templates are stateless: there is no numbering to lose with the database."""
    before = make_thread(tmp_path, strategy="single_folder", data_dir="db_one")
    after = make_thread(tmp_path, strategy="single_folder", data_dir="db_two")

    assert names(before, str(tmp_path / "dl")) == names(after, str(tmp_path / "dl"))


def test_new_placeholders_render(tmp_path):
    template = "{post_date}_{service}_{post_file_count}_{file_number}_{orig_name}"
    thread = make_thread(
        tmp_path,
        strategy="per_post",
        template=template,
        post_dates_map={POST: "2026-03-04"},
    )
    results = generate(thread, str(tmp_path / "dl"))

    assert [name for name, _ in results] == [
        "2026-03-04_svc_2_1_a1.jpg",
        "2026-03-04_svc_2_2_a2.jpg",
        "svc_1_1_b1.jpg",
    ]


def test_missing_templates_fall_back_to_the_numbered_defaults(tmp_path):
    shared = make_thread(
        tmp_path, strategy="single_folder", template=None, shared=None
    )
    assert names(shared, str(tmp_path / "dl")) == [
        "174816708_1_a1.jpg",
        "174816708_2_a2.jpg",
        "174700000_1_b1.jpg",
    ]

    per_post = make_thread(
        tmp_path, strategy="per_post", template=None, shared=None, posts=(POST,)
    )
    assert names(per_post, str(tmp_path / "dl")) == [
        "1_174816708_a1.jpg",
        "2_174816708_a2.jpg",
    ]


def test_settings_tab_without_the_shared_getter_still_names_files(tmp_path):
    """An older settings object must not break the download thread."""
    thread = make_thread(tmp_path, strategy="single_folder")
    thread.settings = SimpleNamespace(
        settings_tab=SimpleNamespace(
            get_creator_filename_template=lambda: "{orig_name}",
            get_creator_folder_strategy=lambda: "single_folder",
        )
    )

    assert names(thread, str(tmp_path / "dl")) == [
        "174816708_1_a1.jpg",
        "174816708_2_a2.jpg",
        "174700000_1_b1.jpg",
    ]


def test_a_taken_name_gets_a_number_suffix(tmp_path):
    """Two files that resolve to one name must not overwrite each other."""
    thread = make_thread(tmp_path, strategy="per_post", posts=(POST,))
    folder = tmp_path / "dl" / "42_Creator"
    folder.mkdir(parents=True)
    existing = folder / "cover.jpg"
    existing.write_bytes(b"first")

    first = thread._unique_path(str(existing), None)
    second = thread._unique_path(str(existing), None)

    assert first == str(folder / "cover_1.jpg")
    # The name handed out above is reserved for the rest of the run, so a
    # concurrent sibling cannot take it before the file lands on disk.
    assert second == str(folder / "cover_2.jpg")
    assert existing.read_bytes() == b"first"


def test_the_numbering_guard_can_be_switched_off(tmp_path):
    thread = make_thread(tmp_path, strategy="per_post", posts=(POST,), unique=False)
    folder = tmp_path / "dl" / "42_Creator"
    folder.mkdir(parents=True)
    existing = folder / "cover.jpg"
    existing.write_bytes(b"first")

    assert thread._unique_path(str(existing), None) == str(existing)


def test_a_repair_target_is_never_renamed(tmp_path):
    """Re-downloading a damaged file must fix it in place, not add a copy."""
    thread = make_thread(tmp_path, strategy="per_post", posts=(POST,))
    folder = tmp_path / "dl" / "42_Creator"
    folder.mkdir(parents=True)
    existing = folder / "cover.jpg"
    existing.write_bytes(b"broken")

    entry = {"file_path": str(existing), "file_hash": "x", "file_size": 6}

    assert thread._unique_path(str(existing), entry) == str(existing)


def test_a_name_held_by_another_file_still_gets_a_suffix(tmp_path):
    """The recorded path is exempt; a name another file took is not."""
    thread = make_thread(tmp_path, strategy="per_post", posts=(POST,))
    folder = tmp_path / "dl" / "42_Creator"
    folder.mkdir(parents=True)
    taken = folder / "cover.jpg"
    taken.write_bytes(b"another post's file")
    elsewhere = folder / "old_place" / "cover.jpg"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"older")

    entry = {"file_path": str(elsewhere), "file_hash": "x", "file_size": 5}

    assert thread._unique_path(str(taken), entry) == str(folder / "cover_1.jpg")


def test_the_numbering_guard_is_on_when_the_setting_is_missing(tmp_path):
    """A settings tab from before the option existed still protects files."""
    thread = make_thread(tmp_path, strategy="per_post", posts=(POST,))
    thread.settings = SimpleNamespace(
        settings_tab=SimpleNamespace(
            get_creator_filename_template=lambda: POST_TEMPLATE,
            get_creator_filename_template_shared=lambda: SHARED_TEMPLATE,
            get_creator_folder_strategy=lambda: "per_post",
        )
    )
    folder = tmp_path / "dl" / "42_Creator"
    folder.mkdir(parents=True)
    existing = folder / "cover.jpg"
    existing.write_bytes(b"first")

    assert thread._unique_path(str(existing), None) == str(folder / "cover_1.jpg")
