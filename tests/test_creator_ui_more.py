from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


def test_pagination_display_controls(qapp, tmp_path):
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path)
    parent.other_files_folder = str(tmp_path)
    parent.download_folder = str(tmp_path)

    tab = cd.CreatorDownloaderTab(parent)

    # Create many filtered posts (post_title, post_id, thumbnail, is_checked)
    total = 450
    tab.filtered_posts = [(f"Post {i}", f"id{i}", None, False) for i in range(total)]
    # Use small posts_per_page to force multiple pages
    tab.posts_per_page = 200
    tab.current_page = 1
    # Ensure total_pages is computed (normally set by filter step)
    tab.total_pages = max(
        1, (len(tab.filtered_posts) + tab.posts_per_page - 1) // tab.posts_per_page
    )
    tab.display_current_page()

    assert tab.total_pages > 1
    assert tab.next_page_btn.isEnabled() is True
    assert tab.prev_page_btn.isEnabled() is False

    tab.next_page()
    assert tab.current_page == 2
    assert tab.prev_page_btn.isEnabled() is True


def test_toggle_checkbox_state_applies_to_selection(qapp, tmp_path):
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path)
    parent.other_files_folder = str(tmp_path)
    parent.download_folder = str(tmp_path)

    tab = cd.CreatorDownloaderTab(parent)

    # Prepare two items and add them via add_list_item
    items = [("Alpha", "pA"), ("Beta", "pB")]
    for title, pid in items:
        unique = f"{title} (ID: {pid})"
        tab.post_url_map[unique] = (pid, None)
        tab.add_list_item(unique, None, False)

    # Select first item
    item_widget, widget = tab.post_widget_cache["Alpha (ID: pA)"]
    item_widget.setSelected(True)

    # Ensure initial checked state is False
    assert tab.checked_urls.get("pA", False) is False

    # Toggle checkbox for the selected item
    tab.toggle_checkbox_state("Alpha (ID: pA)")

    # Should have updated checked_urls for pA
    assert tab.checked_urls.get("pA", False) is True


def test_cancel_creator_download_no_active_threads(qapp, tmp_path):
    parent = SimpleNamespace()
    parent.cache_folder = str(tmp_path)
    parent.other_files_folder = str(tmp_path)
    parent.download_folder = str(tmp_path)

    tab = cd.CreatorDownloaderTab(parent)

    # Ensure no active threads
    tab.active_threads = []

    # Cancel downloads when none active should append a warning to console
    tab.cancel_creator_download()
    text = tab.creator_console.toPlainText()
    assert text.strip() != ""
