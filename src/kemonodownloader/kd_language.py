"""UI strings for Kemono Downloader.

The application ships a single language, so ``STRINGS`` is a flat
``key -> text`` table; the old per-language nesting is gone.
"""

# The filename help is a body plus a fallback line.  Keeping them apart lets
# the shared ("In Creator Folder") dialog slot its warning paragraph between
# them without duplicating the placeholder list.
_FILENAME_HELP_BODY = (
    "<b>Placeholders:</b><br>{post_id} - post id<br>{post_title} - post title<br>"
    "{orig_name} - server file name<br>{ext} - extension (no dot)<br>"
    "{file_number} - file's place in its post (1, 2, 3)<br>"
    "{file_index} - file's place in the whole run<br>"
    "{post_file_count} - files in this post<br>{total_files} - files in the whole run<br>"
    "{post_date} - publish date (YYYY-MM-DD)<br>{post_time} - publish time (HHMM)<br>"
    "{creator_id} - creator id<br>{creator_name} - creator name<br>"
    "{service} - site (patreon, fanbox, ...)<br>"
    "<b>Use any separator between placeholders, or none.</b><br><br>"
    "Zero-pad for sorting: add :0>width to any placeholder - 0 fills the left "
    "with zeros, > right-aligns, width is the total length (not a count of zeros).<br>"
    "{file_number:0>3} = 001, {post_id:0>10} = 0174925070."
)
_FILENAME_HELP_FALLBACK = "<b>Fallback: {post_id}_{orig_name}.</b>"

# One wording for the keyword inputs: sorting rules and both skip boxes use
# the same comma/quote/wildcard language. The full table lives in the
# Keyword syntax help topic; Sort's inline help appends it directly.
# Punctuation at literal edges is governed by the separate Punctuation
# Matching Behavior setting.
_KEYWORD_SYNTAX_HTML = (
    "<h3>Keyword syntax</h3>"
    "<ul>"
    "<li>Separate values with commas. If a value contains a comma, put it in "
    "double quotes: <code>\"Hello, world\"</code>. The quotes are not part of "
    "the value.</li>"
    "<li><code>*</code> = any text (including none); <code>?</code> = exactly "
    "one character.</li>"
    "<li>Case does not matter: <code>BlackCat</code> and <code>blackcat</code> "
    "are the same.</li>"
    "<li>A value made only of <code>*</code> or <code>?</code> is ignored; add "
    "some text to it.</li>"
    "</ul>"
    "<table border='1' cellspacing='0' cellpadding='4'>"
    "<tr><th>Pattern</th><th>Matches</th><th>Does not match</th></tr>"
    "<tr><td><code>cat</code></td><td>the word/tag cat</td>"
    "<td>cats, Catgirl, bobcat</td></tr>"
    "<tr><td><code>cat*</code></td><td>cats, Catgirl</td><td>bobcat</td></tr>"
    "<tr><td><code>*cat</code></td><td>bobcat</td>"
    "<td>cats, Catgirl, scatter</td></tr>"
    "<tr><td><code>*cat*</code></td><td>bobcat, Catgirl, scatter</td>"
    "<td>dog</td></tr>"
    "<tr><td><code>c?t</code></td><td>cat, cot, cut</td><td>cart</td></tr>"
    "</table>"
)


STRINGS = {
    "add_creator_and_load_tooltip": "Add this link and load it",
    "add_links_from_file_title": "Import from TXT File",
    "added_attachment": "Added attachment: {0}",
    "added_content_image": "Added content image: {0}",
    "added_main_file": "Added main file: {0}",
    "added_to_queue": "Added to queue",
    "all_api_endpoints_failed": "All API endpoints failed for creator {0}",
    "all_downloads_cancelled": "All downloads cancelled by user",
    "all_files_attempted": "All files attempted (successful or failed), triggering download finished",
    "all_files_attempted_for_creator": "All files attempted for current creator. Finalizing.",
    "all_posts_and_files_completed": "All posts and files completed for current creator.",
    "all_posts_hidden_downloaded": "Every post from this creator is already downloaded.",
    "allowed_extensions_for_download": "Allowed extensions for download: {0}",
    "api_request_max_retries": "Creator Name Max Retries:",
    "app_title": "Kemono Downloader",
    "apply_changes": "Apply Changes",
    "attachments": "Attachments",
    "back": "Back",
    "base_api_url": "Base API URL: {0}",
    "browse": "Browse",
    "bulk_add_complete": "Bulk Add Complete",
    "bulk_add_summary": "Added {0} link(s) to queue. Skipped {1} link(s).",
    "cancel": "Cancel",
    "cancellation_process_completed": "Cancellation process completed",
    "cancelling_downloads": "Cancelling all downloads...",
    "cancelling_post_detection": "Cancelling post detection...",
    "check_all": "Check Page",
    "check_all_all": "Check All",
    "check_all_state_updated": "Check state updated to {0}",
    "check_page_tooltip": "Tick every post on this page. A partly ticked box ticks the rest; use Deselect to clear.",
    "check_all_tooltip": "Tick every post from this creator. A partly ticked box ticks the rest; use Deselect to clear.",
    "check_updates_on_github": "Check for updates on the GitHub repository (VoxDroid/KemonoDownloader)",
    "checkbox_toggle_already_in_progress": "Checkbox toggle already in progress. Please wait.",
    "checkbox_toggle_completed": "Checkbox toggle completed: Check ALL = {0}, Affected posts: {1}, Total checked: {2}",
    "checkbox_toggle_finished": "Checkbox toggle finished, checked posts: {0}, visible posts: {1}",
    "checkbox_toggled_for_post": "Checkbox toggled for post {0} (ID: {1}) to {2}",
    "checking_attachment": "Checking attachment: {0} ({1})",
    "checking_content_image": "Checking content image: {0} ({1})",
    "checking_creator_with_url": "Checking creator with URL: {0}",
    "checking_main_file": "Checking main file: {0} ({1})",
    "clear_logs": "Clear Logs",
    "close": "Close",
    "confirm_removal": "Confirm Removal",
    "confirm_removal_message": "Are you sure you want to remove {0} from the queue?",
    "confirm_removal_post_link_message": "Are you sure you want to remove {0} post link from the queue?",
    "confirm_removal_post_links_message": "Are you sure you want to remove {0} post links from the queue?",
    "confirm_reset_message": "Are you sure you want to reset all settings to their default values?",
    "confirm_settings_change": "Confirm Settings Change",
    "confirm_settings_message": "Are you sure you want to apply these settings?",
    "config_load_failed": "Could not read a saved config: {0}",
    "config_no_creator_text": "Open a creator first: a creator config has to be attached to one.",
    "config_save_failed": "Could not save the config: {0}",
    "config_save_invalid_text": "Fix these entries first:\n{0}",
    "config_save_invalid_title": "Config Not Saved",
    "config_saved_log": "Page config saved.",
    "config_saved_text": "Saved {0} options and {1} filter field(s).",
    "config_saved_title": "Config Saved",
    "config_unavailable": "Saved configs are unavailable - check the Data Directory.",
    "content_images": "Content Images",
    "copy_link": "Copy Link",
    "created_directory": "Created directory: {0}",
    "creator_config_loaded": "Using the saved config for creator {0}.",
    "creator_config_saved_log": "Config saved for creator {0}.",
    "creator_config_saved_text": "Saved {0} options and {1} filter field(s) for creator {2}.",
    "creator_config_saved_title": "Creator Config Saved",
    "creator_download_thread_started": "CreatorDownloadThread started for service: {0}, creator_id: {1}",
    "creator_downloader_settings": "Creator Downloader",
    "creator_downloader_tab": "Creator Downloader",
    "creator_posts_max_attempts": "Creator Posts Max Pages:",
    "creator_queue": "Queue",
    "creator_queue_input_placeholder": "Enter Creator / Post",
    "creator_queue_input_tooltip": "Creator or post URL. A post link loads only its linked posts.",
    "custom_proxy_url": "Custom Proxy URL:",
    "custom_proxy_url_empty": "Custom proxy URL cannot be empty.",
    "date_filter_help_text": "Filter posts by their own publish date (not the date they were imported/scraped). Enter dates as YYYY-MM-DD in 'From' and/or 'To' — both bounds are inclusive and both are optional; leave either blank to disable that bound. Posts with an unknown publish date are always kept.",
    "date_filter_help_title": "Post Date Filter Help",
    "data_directory": "Data Directory:",
    "data_directory_tooltip": "Where the app keeps its own working files: the duplicate-check database, download history and saved config profiles. Pointing it somewhere other than the Save Directory keeps those out of your collection.",
    "date_range_filter": "Date Range",
    "date_range_from": "From",
    "date_range_from_placeholder": "YYYY-MM-DD",
    "date_range_to": "To",
    "date_range_to_placeholder": "YYYY-MM-DD",
    "deleted_incomplete_file": "Deleted incomplete file: {0}",
    "deselect": "Deselect",
    "deselect_all": "Deselect All",
    "deselect_page": "Deselect Page",
    "deselect_tooltip": "Clear the ticks for this page or for every post from this creator",
    "deleting_thread": "Deleting thread {0}",
    "detected_file": "Detected file: {0} from {1}",
    "detecting_files_for_post": "Detecting files for post with allowed extensions: {0}",
    "detecting_linked_posts": "Loading linked posts...",
    "detecting_posts": "Detecting posts from link...",
    "disabled": "Disabled",
    "displayed_page_posts": "Displayed page {0} with {1} posts",
    "download": "Download",
    "discarded_stale_filter_pass": "Discarded a filter pass started for another creator",
    "download_completed_with_failed_files": "Download completed with {0} failed files:",
    "download_failed_retrying": "Download failed for {0}, attempt {1}/{2}: {3}",
    "download_file_failed_with_error": "Failed to download {0}: {1}",
    "download_forbidden_giving_up": "Giving up on {0}: the file host answered 403 {1} times in a row.",
    "download_logs": "Download Logs",
    "download_options": "Download Options",
    "download_process_completed": "Download process finished",
    "download_retry_budget_exhausted": "Giving up on {0} after {1}s of retries: {2}",
    "download_settings": "Download Settings",
    "download_text": "Download Post Text",
    "download_tor": "Download Tor",
    "downloader_box_info_text": "Key: Post Title | (Publish Date) | [Last Downloaded Date]\nRight-click to open a post in your browser, and Double Click to view a post.",
    "downloader_box_info_title": "Downloader Box Help",
    "downloading": "Downloading...",
    "downloading_tor": "Downloading Tor...",
    "downloads_complete": "Downloads Complete",
    "downloads_terminated": "Downloads Terminated",
    "empty_response_at_offset": "Empty response at offset {0}. No more posts available.",
    "enabled": "Enabled",
    "endpoint_error_with_exception": "Endpoint error: {0} - {1}",
    "endpoint_failed_with_status": "Endpoint failed: {0} - Status: {1}",
    "endpoint_returned_status_likely_end": "Endpoint returned {0} (likely reached end of data): {1}",
    "endpoint_successful": "Endpoint successful: {0}",
    "endpoint_unavailable_likely_end": "Endpoint unavailable (likely reached end of data): {0} - {1}",
    "english": "English",
    "error": "Error",
    "error_downloading_after_retries": "Failed to download {0} after {1} retries: {2}",
    "download_file_unavailable": "Download failed for {0}: the host answered {1} and retrying cannot fix it",
    "direct_server_failed": "Direct server failed for {0} ({1}); using the usual address",
    "error_fetching_creator_name": "Error fetching creator name: {0}",
    "error_fetching_post": "Error fetching post {0} (attempt {1}/{2}): {3}. Retrying...",
    "error_fetching_post_max_attempts": "Error fetching post {0} after {1} attempts: {2}",
    "error_fetching_title_for_post": "Error fetching title for post {0}: {1}",
    "error_in_async_download_loop": "Error in async download loop: {0}",
    "error_in_download_worker": "Error in download worker: {0}",
    "error_loading_image": "Error loading image",
    "error_processing_url": "Error processing URL",
    "failed_save_post_description": "Failed to save description for post {0}: {1}",
    "failed_to_create_creator_folder": "Failed to create creator folder {0}: {1}",
    "failed_to_create_post_folder": "Failed to create post folder {0}: {1}. Likely due to invalid folder name.",
    "failed_to_delete_incomplete_file": "Failed to delete incomplete file {0}: {1}",
    "failed_to_download_file": "Failed to download {0}: {1}",
    "failed_to_fetch_api": "Failed to fetch {0} - Status code: {1}",
    "failed_to_fetch_creator_name": "Failed to fetch creator name, using default: {0}",
    "failed_to_fetch_title_for_post": "Failed to fetch title for post {0}, using default",
    "failed_to_parse_response": "Failed to parse response: {0}",
    "fetched_posts_at_offset": "Fetched {0} posts at offset {1}",
    "fetched_title_for_post": "Fetched title for post {0}: {1}",
    "file_already_downloaded": "File {0} already downloaded at {1}, skipping.",
    "file_completed": "File completed: {0}, Total completed: {1}/{2}",
    "file_count_filter": "File Count From",
    "file_count_from_placeholder": "Min",
    "file_count_help_text": "Filter posts by how many files they hold: the main file, attachments and content images all count. Enter a minimum in 'File Count From' and/or a maximum in 'To' — both bounds are inclusive and both are optional; leave either blank to disable that bound. This count is independent of the file type tickboxes.\n\nKeep Archives: posts that contain a compressed file (ZIP, 7Z, RAR) always stay in the list, whatever their file count, so archive posts are never filtered out.\n\nApplies to the loaded list straight away, so there is nothing to re-apply by hand.",
    "file_count_help_title": "File Count Filter Help",
    "file_count_keep_compressed": "Keep Archives",
    "file_count_to": "To",
    "file_count_to_placeholder": "Max",
    "file_download_max_retries": "File Download Max Retries:",
    "file_extensions": "Filetypes",
    "filter_no_selected_filetypes": "Filter posts without selected filetypes",
    "filter_no_selected_filetypes_help_text": 'Hides posts holding none of the ticked filetypes. With no filetypes ticked, nothing is shown. Posts with no files are hidden too, unless "Download Post Text" is on. Applies to the loaded list straight away.',
    "filter_no_selected_filetypes_help_title": "Filter Posts Without Selected Filetypes Help",
    "filters_group_title": "Filters",
    "file_failed": "File failed: {0}, Total failed: {1}",
    "file_preparation_deadline_warning": "File preparation timed out with {0} post(s) still running; any files they found were not queued.",
    "file_preparation_in_progress": "File preparation already in progress. Please wait.",
    "file_progress": "File Progress {0}%",
    "file_read_error": "Error reading file: {0}",
    "file_read_error_title": "File Read Error",
    "filename_template": "Filename Template (In Post Folder):",
    "filename_template_error": "Filename template failed to format, using fallback: {0}",
    "filename_template_fallback": _FILENAME_HELP_FALLBACK,
    "filename_template_help_body": _FILENAME_HELP_BODY,
    "filename_template_help_text": (
        _FILENAME_HELP_BODY + "<br><br>" + _FILENAME_HELP_FALLBACK
    ),
    "filename_template_help_title": "Filename Template Help",
    "filename_template_shared": "Filename Template (In Creator Folder):",
    "filename_template_shared_warning": "'In Creator Folder' names files pooled with other posts ('Single creator folder', 'Subfolders by file type', or a skipped post folder). Warning: a combo without {post_id} or {post_date} can give two posts' files the same name.",
    "files_skipped_by_keyword": "Skipped {0} file(s) matching skip-keywords: {1}",
    "filtering_already_in_progress": "Filtering already in progress. Please wait.",
    "filtering_completed_displayed_posts": "Filtering completed, displayed {0} posts",
    "filtering_posts": "Filtering posts...",
    "folder_name_template": "Folder Name Template:",
    "folder_name_template_error": "Folder name template failed to format, using fallback: {0}",
    "folder_name_template_help_text": "<b>Placeholders:</b><br>{post_id} - post id<br>{post_title} - post title<br>{creator_id} - creator id<br>{creator_name} - creator name<br><br>Zero-pad for sorting: add :0>width to any placeholder - 0 fills the left with zeros, > right-aligns, width is the total length (not a count of zeros).<br>{post_id:0>10} = 0174925070.<br>Only used when Folder Structure is 'Per-post folders'.<br><br><b>Fallback: {post_id}_{post_title}.</b>",
    "folder_name_template_help_title": "Folder Name Template Help",
    "folder_settings": "Folder Settings",
    "folder_strategy": "Folder Structure:",
    "font": "Font:",
    "font_settings": "Font Settings",
    "force_folder_for_compressed": "Always Post Folder for Compressed Files",
    "full_logs": "Full Logs",
    "gzip_decompression_failed": "Gzip decompression failed, trying plain text: {0}",
    "hide_downloaded": "Hide Downloaded",
    "hide_downloaded_excluded": "Hide Downloaded: {0} linked post(s) are already downloaded and stay hidden.",
    "hide_downloaded_hidden": "{0} already downloaded post(s) are hidden.",
    "hide_downloaded_tooltip": "Leave posts that are already in the download history out of the list.",
    "idle": "Idle",
    "image_load_error": "Image Load Error",
    "images_skipped_archive_present": "[SKIP-IMAGE] Skipped {0} image file(s); a compressed archive is present",
    "incremental_filtering_added_posts": "Incremental filtering: added {0} post(s) to display",
    "invalid_creator_url": "Invalid creator URL or failed to fetch: {0}",
    "invalid_date_from_ignored": "Invalid 'Date Range: From' value ignored (use YYYY-MM-DD)",
    "invalid_date_to_ignored": "Invalid 'Date Range: To' value ignored (use YYYY-MM-DD)",
    "invalid_file_count_ignored": "Invalid 'File Count' value ignored (use a whole number)",
    "invalid_input": "Invalid Input",
    "invalid_posts_data_type": "Invalid posts data type: {0}",
    "invalid_url_format": "Invalid URL format. Expected: https://pawchive.pw/[service]/user/[user_id]/post/[post_id]",
    "invalid_url_format_from_txt": "Invalid URL format, skipping",
    "invalid_url_type": "Invalid URL type: {0}. Expected string.",
    "language": "Language:",
    "language_changed": "Language changed to English",
    "last_downloaded_creator": "Last Downloaded from Creator: {0}",
    "last_page_reached_with_counts": "Last page reached (received {0} posts, expected {1}). Total posts fetched: {2}",
    "link_copied": "Copied link: {0}",
    "link_removed": "Link ({0}) is removed from the queue.",
    "linked_post_fetch_failed": "Could not load linked post {0}: {1}",
    "linked_posts_menu": "Linked posts",
    "load_full_creator_tooltip": "Load the full creator with the linked posts selected",
    "loading_image": "Loading Image... ({0}%)",
    "loading_image_simple": "Loading Image...",
    "loading_post": "Loading post...",
    "log_debug": "[DEBUG] {0}",
    "log_error": "[ERROR] {0}",
    "log_info": "[INFO] {0}",
    "log_panel_toggle": "Log",
    "log_panel_toggle_count": "Log ({0})",
    "log_warning": "[WARNING] {0}",
    "main_file": "Main File",
    "mapped_title_to_id_and_thumbnail": "Mapped title '{0}' to ID: {1}, Thumbnail: {2}",
    "media_preview": "Media Preview",
    "never_downloaded": "Never",
    "no_active_downloads_to_cancel": "No active downloads to cancel",
    "no_creator_viewed": "No creator currently viewed to download.",
    "no_creators_queue": "No creators in queue to download.",
    "no_current_creator_url_set": "No current creator URL set.",
    "no_files_detected": "No files detected for selected posts. Skipping.",
    "no_files_selected_for_download": "No files selected for download.",
    "no_matching_creator_urls": "No matching creator URLs found for selected posts.",
    "no_more_active_threads": "No more active threads or creators. Finishing.",
    "no_more_posts_at_offset": "No more posts to fetch at offset {0}. Stopping pagination.",
    "no_post_id_found_for_title": "No post ID found for title: {0}",
    "no_posts_available": "No posts available for download. Skipping.",
    "no_posts_match_filters": "No posts match the current filters",
    "no_posts_selected": "No posts selected for download.",
    "no_posts_to_toggle": "No posts to toggle.",
    "no_selectable_posts_to_toggle": "Every post is already downloaded (Hide Downloaded is on).",
    "no_settings_changed": "No settings changed.",
    "no_url_entered": "No URL entered.",
    "no_visible_posts_to_toggle": "No visible posts to toggle.",
    "not_available": "N/A",
    "open_creator_folder": "Open Folder",
    "open_creator_folder_missing": "Folder is no longer there: {0}",
    "open_creator_folder_tooltip": "Open the folder this run is saving into",
    "open_creator_folder_waiting": "No creator folder yet - it appears once the first file is saved",
    "open_log_tooltip": "Open the full log window",
    "open_post_in_browser": "Open Post in Browser",
    "option_off": "Off",
    "option_on": "On",
    "option_on_both": "On (Both)",
    "option_on_file": "On (File)",
    "option_on_folder": "On (Folder)",
    "overall_progress": "Overall Progress ({0}/{1} files, {2}/{3} posts)",
    "page_info": "Page {0} of {1}",
    "parsed_url_service_creator": "Parsed URL - Service: {0}, Creator ID: {1}",
    "per_post_folders": "Per-post folders (default)",
    "populated_posts_for_creator": "Populated {0} posts for creator {1}",
    "populating_posts": "Populating posts...",
    "post_data_for_id": "Post data for {0}: {1}",
    "post_data_max_retries": "Post Data Max Retries:",
    "post_detection_in_progress": "Post detection already in progress. Please wait.",
    "post_fully_downloaded": "Post {0} fully downloaded.",
    "post_id_and_title": "Post ID: {0}, Title: {1}",
    "post_id_mismatch": "Post ID mismatch: Expected {0}, got {1}",
    "post_preview_image_failed": "Image unavailable",
    "post_preview_images_count": "{0} image(s)",
    "post_preview_images_failed": "{0} of {1} image(s) could not be loaded.",
    "post_preview_load_failed": "Could not load this post: {0}",
    "post_preview_loading_images": "Loading images... ({0}/{1})",
    "post_preview_no_images": "This post has no images.",
    "post_preview_retry": "Retry",
    "post_preview_tags": "Tags: {0}",
    "post_preview_title": "Post Preview",
    "posts_count": "Posts: {0}",
    "posts_skipped_by_date_filter": "Skipped {0} post(s) outside the selected date range.",
    "posts_skipped_by_file_count_filter": "Skipped {0} post(s) outside the selected file count range.",
    "posts_skipped_by_filetypes_filter": "Skipped {0} post(s) holding none of the selected file types.",
    "posts_skipped_by_keyword": "Skipped {0} post(s) matching skip-keywords: {1}",
    "posts_to_download": "Posts to Download",
    "posts_to_download_num": "Posts to download: {0}",
    "posts_without_details_not_filtered": "Left {0} post(s) unfiltered: no stored details for them. Re-fetch this creator to filter them too.",
    "preparation_rate_limited": "Rate limited while preparing {0}; Retry-After: {1}",
    "prepared_files_for_download": "Prepared {0} files for download",
    "prepared_posts_for_population": "Prepared {0} posts for population, unique titles: {1}",
    "preparing_files": "Preparing files to download...",
    "preparing_files_creator": "Preparing files for currently viewed creator: {0}",
    "proxy_settings": "Proxy Settings",
    "proxy_test_failed": "Proxy test failed: {0}",
    "proxy_test_successful": "Proxy test successful!",
    "proxy_custom_url_empty_error": "A custom proxy is enabled but no address is set. Enter one (or turn the proxy off) before downloading.",
    "proxy_tor_not_running_error": "Tor is enabled as the proxy but is not running. Start Tor (or turn the proxy off) before downloading.",
    "proxy_type": "Proxy Type:",
    "punctuation_matching_help_text": "Controls punctuation at the start or end of a keyword or sorting value. Default treats brackets and quotes as their own boundaries, so '[JP]' matches '123[JP] art'; other punctuation still needs a real boundary, so '.5' does not match '1.5'. Relaxed treats any edge punctuation as a boundary. A '*' at an edge is unrestricted; whole-tag matches are unaffected.",
    "punctuation_matching_help_title": "Punctuation Matching Behavior Help",
    "punctuation_matching_rules": "Punctuation Matching Behavior:",
    "punctuation_rules_default": "Default",
    "punctuation_rules_relaxed": "Relaxed",
    "tag_matching_behavior": "Tag Matching Behavior:",
    "tag_matching_default": "Default",
    "tag_matching_lenient": "Lenient",
    "tag_matching_help_title": "Tag Matching Behavior Help",
    "tag_matching_help_text": "Default compares tags as whole values. For example, ブルーアーカイブ does not match アイン(ブルーアーカイブ) in Posts to Download, Skip Posts, Skip Files or Keyword Rules.\n\nLenient restores substring matching: ブルーアーカイブ matches any tag containing it. This applies to all tag searching and rules.",
    "queue_input_behavior_help_text": "Controls what happens after a link is added to the Queue.\n\nDefault: only the link is added.\n\nLoad First: the first link is opened. Once something is open, adding more only queues them.\n\nLoad Every: every link is opened straight away, replacing the current view.\n\nA post link added while that creator's linked posts are already open updates the view immediately. The eye button always adds and opens the link.",
    "queue_input_behavior_help_title": "Queue Input Field Behavior Help",
    "queue_input_default": "Default",
    "queue_input_field_behavior": "Queue Input Field Behavior:",
    "queue_input_load_every": "Load Every",
    "queue_input_load_first": "Load First",
    "queue_more_posts": "+{0} more",
    "rate_limit_hit": "Rate limit hit for {0} (attempt {1}/{2}). Retrying...",
    "rate_limit_summary": "File host answered {0} x HTTP 403 and {1} x HTTP 429 this run.",
    "rate_limit_summary_preparation": "Preparing files: the file API answered {0} x HTTP 403 and {1} x HTTP 429.",
    "queued_post_hidden_by_filters": "{0} of the posts you queued are hidden by the current filters or search, so they will not be downloaded.",
    "reached_last_page": "Reached last page for creator {0}. Total posts fetched: {1}",
    "received_less_than_page_size": "Received {0} posts (less than page size {1}), indicating last page reached",
    "recommended_keywords": "Recommended Keywords",
    "recommended_keywords_add_skip": "Add to Skip Keywords",
    "recommended_keywords_added": "Added to skip keywords: {0}",
    "recommended_keywords_column_keyword": "Keyword",
    "recommended_keywords_column_mentions": "Mentions",
    "recommended_keywords_column_posts": "Posts",
    "recommended_keywords_copy": "Copy",
    "recommended_keywords_empty": "No keywords matched. Try lowering the minimum post count or selecting more scopes.",
    "recommended_keywords_help_text": (
        "<h2>Recommended Keywords</h2>"
        "<p>This window scans the posts already loaded for the current creator. "
        "It does not fetch anything, so it never adds requests to the API.</p>"
        "<h3>How a phrase is built</h3>"
        "<ul>"
        "<li><b>Tags</b> are counted whole: <code>3D art</code> is one keyword.</li>"
        "<li><b>Title</b>, <b>Description</b> and <b>Filenames</b> are split into "
        "words, then 1 to 3 neighbouring words form a phrase. Words only join "
        "when a space sits between them, so punctuation (a comma, a full stop, "
        "a hyphen) ends a phrase and a suggested phrase can be used as a literal "
        "search or skip keyword.</li>"
        "<li>File names split on <code>_ - .</code> and camelCase "
        "(<code>BlackCat_01</code> gives <code>BlackCat</code>). Extensions are "
        "not counted; the filetype boxes own those.</li>"
        "</ul>"
        "<h3>Counting</h3>"
        "<p>A keyword counts once per post, however often it occurs there. "
        "<b>Posts</b> is the number of posts it appears in; <b>Mentions</b> is "
        "the raw occurrence total. The minimum applies to Posts.</p>"
        "<h3>Noise controls</h3>"
        "<ul>"
        "<li><b>In at least N posts</b> hides one-offs. Two is a good default; "
        "raise it for a large library.</li>"
        "<li><b>Ignore common words</b> drops English function words and "
        "contractions such as <code>the</code> or <code>don't</code>.</li>"
        "<li><b>Ignore accents</b> counts <code>café</code> and <code>cafe</code> "
        "together; both spellings are added when the keyword is applied. It "
        "never touches Japanese kana.</li>"
        "</ul>"
        "<h3>Using a keyword</h3>"
        "<p><b>Search</b> puts the keyword in the search box and turns on the "
        "scopes selected here. <b>Add to Skip Keywords</b> appends it to the skip "
        "box and enables the matching Filter By scope, so a tag keyword actually "
        "filters on tags.</p>"
    ),
    "recommended_keywords_help_title": "Recommended Keywords Help",
    "recommended_keywords_ignore_accents": "Ignore accents",
    "recommended_keywords_ignore_common": "Ignore common words",
    "recommended_keywords_intro": "Scans the posts already loaded for this creator. Tags are counted whole; longer phrases are built from words that sit next to each other.",
    "recommended_keywords_min_posts": "In at least",
    "recommended_keywords_no_posts": "Load a creator first: there are no posts to scan.",
    "recommended_keywords_phrase_length": "Phrase length:",
    "recommended_keywords_posts_suffix": "posts",
    "recommended_keywords_refresh": "Refresh",
    "recommended_keywords_scopes": "Search in:",
    "recommended_keywords_scanning": "Scanning posts...",
    "recommended_keywords_search": "Search",
    "recommended_keywords_summary": "{0} keyword(s) from {1} post(s)",
    "recommended_keywords_title": "Recommended Keywords",
    "recommended_keywords_tooltip": "Find words and tags that repeat across the loaded posts",
    "remove_thread": "Removed thread {0} from active threads",
    "reset_to_defaults": "Reset to Defaults",
    "response_content_first_500_chars": "Response content (first 500 chars): {0}",
    "retry_already_downloading": "A download is already running",
    "retry_failed_downloads": "Retry Failed Downloads",
    "retry_failed_downloads_tooltip": "Download only the files that failed in the last run",
    "retry_settings": "Retry Settings",
    "retry_unavailable": "Nothing to retry",
    "retrying_failed_files": "Retrying {0} failed file(s)",
    "retrying_creator_name_fetch": "Could not read the creator name ({0}); retrying",
    "save_config_btn": "Save Config",
    "save_config_btn_tooltip": "Save this page's options and filters as the default for every creator.",
    "save_creator_config_btn": "Save Creator Config",
    "save_creator_config_btn_tooltip": "Save this page's options and filters for this creator only; it replaces the default whenever this creator is loaded.",
    "save_directory": "Save Directory:",
    "saved_post_description": "Saved description for post {0}",
    "search_posts": "Search posts...",
    "search_scope": "Search by",
    "search_scope_description_toggle": "Description",
    "search_scope_filenames_toggle": "Filenames",
    "search_scope_tags_toggle": "Tags",
    "search_scope_title_toggle": "Title",
    "select_links_file": "Select .txt file containing creator URLs",
    "select_tor_executable": "Select Tor executable",
    "server_error_retrying": "Server error {1} for {0} (attempt {2}/{3}). Retrying...",
    "settings_applied": "Settings Applied",
    "settings_applied_message": "Settings have been successfully applied!",
    "settings_reset_message": "Settings have been reset to defaults. Click 'Apply Changes' to save them.",
    "settings_tab": "Settings",
    "show_only_found_filetypes": "Filetype Display:",
    "filetype_display_help_text": "Lists only the extension boxes this creator has files of. 'Show found only (with counts)' also shows how many files of each type the creator has. A ticked type always stays visible. Types are collected while the post list loads.",
    "filetype_display_help_title": "Filetype Display Help",
    "filetype_filter_off": "Show all",
    "filetype_filter_on": "Show found only",
    "filetype_filter_on_with_count": "Show found only (with counts)",
    "signaled_stop_for_thread": "Signaled stop for thread {0}",
    "simultaneous_downloads": "Simultaneous Downloads:",
    "single_creator_folder": "All files in creator folder",
    "size_mismatch_error": "Downloaded size ({0} bytes) does not match expected size ({1} bytes) for {2}",
    "related_help": "Related:",
    "run_summary": "Run Summary",
    "keyword_syntax_help_text": (
        "<p>These rules apply to Skip Posts, Skip Files and sorting values.</p>"
        + _KEYWORD_SYNTAX_HTML
        + "<p>Punctuation at a value's edge follows the "
        "Punctuation Matching Behavior setting.</p>"
    ),
    "keyword_syntax_help_title": "Keyword Syntax Help",
    "skip_files_keywords": "Skip Files Containing",
    "skip_files_keywords_help_text": "<p>Skip individual files whose name matches any of these keywords. Only the matched file is skipped; the rest of the post is still downloaded. The file extension is ignored when matching.</p><p>Plain keywords are case-insensitive and whole-word. Use <code>*...*</code> to match part of a file name. Separate values with commas; quote a value that contains a comma; use <code>*</code> and <code>?</code> as wildcards. The full table is under Keyword syntax in Related.</p><p>Punctuation at their edges follows the Punctuation Matching Behavior setting.</p><p>Leave the box blank to disable.</p>",
    "skip_files_keywords_help_title": "Skip Files Help",
    "skip_files_keywords_placeholder": "e.g. JP, EN (comma-separated)",
    "skip_folder_for_few_images": "Skip Post Folder",
    "skip_folder_info_text": "When enabled, posts with a number of files less than or equal to the selected value will have their files saved directly in the creator folder instead of creating a separate subfolder for that post.\n\nFor example, if set to 1, single-image posts will not get their own folder — the image will be placed directly in the creator's folder.\n\nThis only applies when Folder Structure is set to 'Per-post folders'.\n\nThe archive icon toggle next to this button ignores compressed files (ZIP, 7z, RAR) when deciding whether to skip the post folder — those files will always be saved in their own post folder, even if Skip Post Folder would otherwise apply to that post.",
    "skip_folder_info_title": "Skip Post Folder Help",
    "skip_images_if_compressed": "Skip Images if Compressed",
    "skip_images_info_text": "When enabled, a post's image files (JPG, JPE, PNG, GIF, WEBP) are not downloaded if the same post also offers a compressed archive (ZIP, 7Z, RAR).\n\nThe archive has to be one of the files being downloaded — if ZIP/7Z/RAR is unticked above, the images are kept.\n\nApplies to the main file, attachments and content images.",
    "skip_images_info_title": "Skip Images Help",
    "skip_keyword_matched_after_rejoin": "[SKIP-KEYWORD] '{0}' matched the description after re-joining inline tags",
    "skip_keywords_scope": "Filter By",
    "skip_posts_keywords": "Skip Posts Containing",
    "skip_posts_keywords_help_text": '<p>Skip whole posts whose title, file names, description or tags match any of these keywords.</p><p>Use the <b>Filter By</b> boxes to choose which fields are checked. A post is skipped when a keyword matches in any enabled field:</p><ul><li><b>Title</b> - the post title</li><li><b>Filenames</b> - the main file and attachment names (extension ignored)</li><li><b>Description</b> - the post body text</li><li><b>Tags</b> - the post tags</li></ul><p>Plain keywords are case-insensitive and whole-word, so <code>black</code> matches "Black" but not "BlackCat". Use <code>*black*</code> to match part of a word. Separate values with commas; quote a value that contains a comma; use <code>*</code> and <code>?</code> as wildcards. The full table is under Keyword syntax in Related.</p><p>Punctuation at their edges follows the Punctuation Matching Behavior setting.</p><p>Leave the box blank to disable.</p>',
    "skip_posts_keywords_help_title": "Skip Posts Help",
    "skip_posts_keywords_placeholder": "e.g. JP, EN (comma-separated)",
    "skip_scope_description_toggle": "Description",
    "skip_scope_filenames_toggle": "Filenames",
    "skip_scope_tags_toggle": "Tags",
    "skip_scope_title_toggle": "Title",
    "skip_tooltip_file_keywords": "Files skipped by keyword:",
    "skip_tooltip_files_note": "Archived images are counted when a download runs, not from the list.",
    "skip_tooltip_no_keywords": "No keyword skips",
    "skip_tooltip_post_keywords": "Posts skipped by keyword:",
    "skipped_individual_file": "Skipped individual file (keyword match): {0}",
    "sort_apply": "Apply",
    "sort_download_unsorted": "Download Unsorted",
    "sort_download_unsorted_tooltip": "Include posts that match no sorting rule.",
    "sort_set_unsorted": "Set Unsorted",
    "sort_clear_unsorted": "Clear Unsorted",
    "sort_set_unsorted_tooltip": "Use the selected rule's folder for unmatched posts, or create an Unsorted rule when nothing is selected.",
    "sort_clear_unsorted_tooltip": "Clear the current unsorted folder.",
    "sort_unsorted_marker": "Unsorted",
    "sort_unsorted_folder": "Unsorted",
    "sort_rule_settings": "Rule Settings",
    "sort_run_settings": "Run Settings",
    "sort_by_keyword": "Sort posts by keyword",
    "sort_by_keyword_tooltip": "Put posts that match a rule into <creator folder>/<rule folder>",
    "sort_config_duplicate_folder": "Two sorting rules use the same folder name.",
    "sort_config_invalid_folder": "A sorting rule has no usable folder name.",
    "sort_config_missing_values": "A sorting rule has no usable values.",
    "sort_config_wildcard_only": "A sorting rule contains a value made only of * or ?.",
    "sort_duplicate_folder": 'Rule {0}: the folder "{1}" is already used by another rule.',
    "sort_help_back": "Back",
    "sort_help_text": "<h2>Sort posts by keyword</h2><p>Posts that match a rule go into <code>&lt;creator folder&gt;/&lt;rule folder&gt;</code>. Everything else about the download stays the same.</p><h3>Rules</h3><p>Rules are checked in order and the first match wins. A post that matches no rule goes to the creator folder.</p><h3>Values and Match</h3><p><b>Any value</b> (OR): the rule matches when at least one value matches in any selected <b>Look in</b> field.</p><p><b>All values</b> (AND): the rule matches only when every value matches somewhere in the selected fields. Different values can match different fields; they do not all have to appear in the same field.</p><p>Example: values <code>cat, dog</code> with <b>Tags</b> and <b>Title</b> selected:</p><ul><li><b>Any value</b> - a post with tag cat OR title dog matches.</li><li><b>All values</b> - a post needs both cat and dog somewhere in those fields.</li></ul><h3>Look in</h3><ul><li><b>Tags</b> - the whole tag must match by default; with Tag Matching Behavior: Lenient, a value can match any part of a tag. A tag such as <code>アイン(ブルーアーカイブ)</code> is not the same as <code>ブルーアーカイブ</code>; use <code>*ブルーアーカイブ*</code> in a rule value to match part of a tag.</li><li><b>Title</b>, <b>Filenames</b>, <b>Description</b> - the pattern must match a word.</li></ul><p><b>Filenames</b> covers main files and attachments only; content images are not checked.</p>"
    + _KEYWORD_SYNTAX_HTML
    + "<h3>Hardlinks</h3><p>With <b>Hardlink across matching folders</b>, every matching folder gets a hardlink. Hardlinks share the same bytes and cost no extra space, but some cloud-sync clients upload each name separately.</p><h3>Unsorted posts</h3><p>Posts that match no rule go to the creator folder. Turn off <b>Download Unsorted</b> to leave them out of the run, or select a rule and use <b>Set Unsorted</b> to put them in that rule's folder. With no rule selected, <b>Set Unsorted</b> creates an <b>Unsorted</b> rule that needs no values. The button changes to <b>Clear Unsorted</b>; clear it before choosing another rule.</p><h3>Preview</h3><p>The preview uses the details from the current fetch. A post with no details can still match on its title; other scopes need the details.</p><p>The Punctuation Matching Behavior setting applies to literal edges in sorting values too; a <code>*</code> edge is unrestricted.</p><p>Apply changes on this page; use Save Config or Save Creator Config to keep the rules.</p>",
    "sort_help_title": "Sort posts by keyword - Help",
    "sort_invalid_folder": "Rule {0}: the folder name is empty or unusable.",
    "sort_invalid_text": "Fix these before applying:\n{0}",
    "sort_invalid_title": "Sort rules",
    "sort_keyword_rules": "Keyword Folder Sorting",
    "sort_keyword_rules_tooltip": "Edit the keyword folder sorting rules",
    "sort_link_all": "Hardlink across matching folders",
    "sort_link_all_tooltip": "Hardlinks share the same bytes on disk, so they cost no extra space. Some cloud-sync clients upload each name as a separate file.",
    "sort_link_failed": 'Could not hardlink {0} into "{1}": {2}',
    "sort_links_summary": "Auto-sort: created {0} extra hardlink(s), {1} failed.",
    "sort_log_counts": "{0}: {1}",
    "sort_log_multi": "Auto-sort: {0} post(s) match more than one rule; link mode keeps every match.",
    "sort_log_no_rules": "Auto-sort is on, but no rule is enabled.",
    "sort_log_none": "Auto-sort is on, but no selected post matched a rule.",
    "sort_log_summary": "Auto-sort: {0}; {1} unsorted, {2} with no details.",
    "sort_missing_values": "Rule {0}: add at least one value.",
    "sort_new_folder": "New Folder",
    "sort_no_rules_hint": "Add a rule to start.",
    "sort_no_sorted_posts": "No selected posts matched a sorting rule; enable Download Unsorted or add a rule.",
    "sort_preview_extra_links": "Extra folders per file: {0}",
    "sort_preview_label": "Preview",
    "sort_preview_line": "{0}: {1}",
    "sort_preview_missing": "No details: {0}",
    "sort_preview_multi": "Match more than one rule: {0}",
    "sort_preview_none": "No posts to preview.",
    "sort_preview_unsorted": "Unsorted: {0}",
    "sort_preview_unsorted_skipped": "Unsorted (not downloaded): {0}",
    "sort_rule_add": "Add Rule",
    "sort_rule_all": "All values",
    "sort_rule_any": "Any value",
    "sort_rule_down": "Move Down",
    "sort_rule_folder": "Folder:",
    "sort_rule_folder_placeholder": "e.g. Ado",
    "sort_rule_no_values": "(no values)",
    "sort_rule_remove": "Remove",
    "sort_rule_scopes": "Look in:",
    "sort_rule_summary": "{0}. {1} - {2}",
    "sort_rule_up": "Move Up",
    "sort_rule_values": "Values:",
    "sort_rule_values_placeholder": "e.g. JP, EN (comma-separated)",
    "sort_rules_label": "Rules",
    "sort_rules_saved": "Keyword rules: {0} rule(s) configured.",
    "sort_scope_description": "Description",
    "sort_scope_filenames": "Filenames",
    "sort_scope_tags": "Tags",
    "sort_scope_title": "Title",
    "sort_status_off": "Sorting is Off - toggle it with the switch on the page.",
    "sort_status_on": "Sorting is On - toggle it with the switch on the page.",
    "sort_title": "Sort posts by keyword",
    "sort_wildcard_only_value": 'Rule {0}: "{1}" is only wildcards; add some text.',
    "wildcard_only_keyword_ignored": "A keyword made only of * or ? was ignored; add some text.",
    "start_tor": "Start Tor",
    "starting_cancellation_of_active_threads": "Starting cancellation of active threads",
    "starting_download": "Starting download of file {0}/{1}: {2} to {3}",
    "stop_tor": "Stop Tor",
    "subfolders_by_file_type": "Subfolders by file type",
    "successfully_decompressed_gzipped_response": "Successfully decompressed gzipped response",
    "successfully_downloaded": "Successfully downloaded: {0}",
    "summary_downloaded": "Downloaded: {0}",
    "summary_failed": "Failed: {0}",
    "summary_failed_files_one_post": "Failed: {0} files ({1} post)",
    "summary_failed_files_posts": "Failed: {0} files ({1} posts)",
    "summary_skip_files": "File keywords {0}",
    "summary_skip_images": "Archived images {0}",
    "summary_skip_post_date": "Date {0}",
    "summary_skip_post_file_count": "File count {0}",
    "summary_skip_post_filetypes": "Filetypes {0}",
    "summary_skip_post_keywords": "Post keywords {0}",
    "summary_skipped_posts": "Skipped Posts: {0}",
    "summary_skipped_files": "Skipped Files: {0}",
    "supported_filetypes_not_present": "Supported Filetypes Not Present",
    "terminated_lingering_thread": "Terminated lingering thread: {0}",
    "terminated_thread": "Terminated thread: {0}",
    "test_proxy": "Test Proxy",
    "test_tor": "Test Tor",
    "thread_already_deleted": "Thread {0} already deleted",
    "thread_already_deleted_during_termination": "Thread {0} already deleted during termination",
    "thread_deleted_during_cancellation_wait": "A thread was deleted during cancellation wait",
    "thread_not_exited_gracefully": "Thread {0} did not exit gracefully, attempting termination.",
    "ticked_posts_hidden_by_filters": "{0} ticked post(s) are hidden by the current filters or search, so they will not be downloaded.",
    "toggling_checkbox": "Toggling checkbox...",
    "tor_already_running": "Tor is already running.",
    "tor_auto_detected": "Tor automatically detected at: {0}",
    "tor_download_failed": "Tor download failed: {0}",
    "tor_download_successful": "Tor downloaded successfully!",
    "tor_exe_not_found": "tor.exe not found in downloaded files.",
    "tor_executable_ok_but_proxy_not_running": "Tor executable is valid, but proxy service is not running. Please start Tor first.",
    "tor_not_configured": "Tor is not configured or tor.exe not found.",
    "tor_not_running": "Tor is not currently running.",
    "tor_output": "Tor Output:",
    "tor_path": "Tor Path:",
    "tor_proxy_working": "Tor proxy is working correctly!",
    "tor_running": "Tor is now running and ready to use.",
    "tor_starting": "Starting Tor...",
    "tor_status_running": "Tor Status: Running",
    "tor_status_starting": "Tor Status: Starting...",
    "tor_status_stopped": "Tor Status: Stopped",
    "tor_stopped": "Tor has been stopped.",
    "tor_test_failed": "Tor test failed.",
    "tor_test_successful": "Tor test successful!",
    "total_files_detected": "Total files detected: {0}",
    "total_files_to_download": "Total files to download: {0}",
    "total_posts": "Total posts: {0}",
    "total_posts_fetched_for_creator": "Total posts fetched for creator {0}: {1} (filtered out: {2})",
    "total_selected_files_to_download": "Total selected files to download: {0}",
    "transferred_from": "Transferred {0} from {1}",
    "trying_again_in": "Trying again in {0}",
    "trying_endpoint": "Trying endpoint: {0}",
    "unexpected_error": "Unexpected error while processing file from",
    "unexpected_error_detecting": "Unexpected error while detecting posts: {0}",
    "unexpected_error_downloading": "Unexpected error downloading {0}: {1}",
    "unexpected_error_text": "Kemono Downloader hit an unexpected error but is still running. The details below can be copied into a bug report.",
    "unexpected_error_title": "Unexpected Error",
    "unexpected_response_structure": "Unexpected response structure: {0}",
    "unique_filenames": "Name Dedup:",
    "unique_filenames_help_text": (
        "Which names get a _1, _2, ... suffix rather than replacing what is "
        "already there.\n\n"
        "On (File) - protects file names.\n"
        "On (Folder) - protects post folder names, so two posts with the same "
        "title keep separate folders.\n"
        "On (Both) - protects both.\n\n"
        "Re-downloading the same file still repairs it in place. Nothing "
        "changes while the templates keep names apart ({post_id}/{file_number} "
        "in the filename templates, {post_id} in the folder one)."
    ),
    "unique_filenames_help_title": "Name Dedup Help",
    "update_settings": "Updates",
    "updated_checked_posts_count": "Updated checked posts count: {0}, checked_urls: {1}, all_detected: {2}, selected IDs: {3}",
    "updating_checkboxes": "Updating checkboxes...",
    "url_already_in_queue": "URL is already in the download queue",
    "url_not_found": "URL ({0}) not found in queue.",
    "use_proxy": "Use Proxy",
    "verbose_logging": "Verbose logging",
    "verbose_logging_tooltip": "Show internal debug lines in the log. Off by default, so the log keeps only events, warnings and errors.",
    "using_cached_posts_fallback": "Fetching failed, using cached posts for {0}",
    "viewing_creator": "Viewing creator: {0}",
    "waiting_for_remaining_files": "Waiting for remaining files: {0}/{1}, Failed: {2}, Active threads: {3}",
    "waiting_retry_after": "Waiting {0} s, as the file API asked, before preparing the next post.",
}

DEFAULT_LANGUAGE = "english"
LANGUAGES = [DEFAULT_LANGUAGE]


class KDLanguage:
    """English string table behind the ``translate()`` helper."""

    def __init__(self):
        self.translations = STRINGS
        self.current_language = DEFAULT_LANGUAGE

    def get_text(self, key, language=None, *args):
        """Return the text for *key*, formatted with *args* when given."""
        text = self.translations.get(key)
        if text is None:
            return key
        if args:
            try:
                return text.format(*args)
            except Exception:
                return text
        return text

    def set_language(self, language):
        """Accept only the language this build actually ships."""
        if language not in LANGUAGES:
            return False
        if language != self.current_language:
            self.current_language = language
            return True
        return False

    def get_current_language(self):
        return self.current_language

    def get_language(self):
        return self.get_current_language()

    def get_language_name(self, language=None):
        return self.get_text(language or self.current_language)

    def get_available_languages(self):
        return list(LANGUAGES)


language_manager = KDLanguage()


def translate(key, *args):
    """Return the English text for *key* (falls back to the key)."""
    return language_manager.get_text(key, None, *args)
