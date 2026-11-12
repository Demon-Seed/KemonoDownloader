"""One-off: split test_creator_downloader_more.py into topic modules."""

import ast
import pathlib
import re

SOURCE = pathlib.Path("tests/test_creator_downloader_more.py")

BUCKETS = {
    "tests/test_creator_fetch_and_preview.py": [
        "test_filter_thread_run",
        "test_checkbox_toggle_thread",
        "test_logs_window_update_and_clear",
        "test_preview_thread_error",
        "test_creator_download_thread_run_no_files",
        "DummySignal",
        "test_get_desc_folder_for_post_strategies",
        "test_check_post_completion_emits_post_completed",
        "test_download_post_text_if_needed_calls_once",
        "test_get_headers_and_session_proxy_behavior",
        "test_preview_thread_uses_cache",
        "test_post_detection_thread_invalid_url_emits_error",
        "test_fetch_and_detect_files_respects_response",
        "test_fetch_and_detect_files_handles_rate_limit",
        "make_gzipped_json",
        "test_post_detection_thread_handles_gzipped_posts",
        "test_post_detection_thread_handles_posts_key_and_data_key",
        "test_file_preparation_detect_files_various_cases",
        "test_fetch_and_detect_files_success",
    ],
    "tests/test_creator_download_core.py": [
        "test_download_file_short_circuit_with_hash",
        "FakeResp",
        "test_download_size_mismatch_marks_failed",
        "test_download_retries_on_request_exception_then_succeeds",
        "make_thread_for_download",
        "test_download_file_makedirs_failure",
        "test_download_file_requests_exception",
        "test_check_post_completion_triggers_post_completed",
        "test_download_size_mismatch_deletion_raises",
        "FakeResponse",
        "FakeSession",
        "test_download_file_success_writes_and_stores",
        "test_cleanup_thread_transfers_failed_files",
        "test_streamed_download_writes_file_and_updates_hashdb",
    ],
    "tests/test_creator_download_retries.py": [
        "test_creator_download_run_processes_queue",
        "FakeSessionAlwaysError",
        "test_hash_db_size_mismatch_triggers_redownload",
        "FakeResponseMismatch",
        "FakeSessionMismatch",
        "FakeResponseCancel",
        "FakeSessionCancel",
        "test_size_mismatch_deletes_incomplete_and_records_failure",
        "test_cancellation_during_streaming_deletes_incomplete_and_records_failure",
        "test_download_file_retries_records_failure",
        "test_run_returns_immediately_when_stopped",
        "test_creator_download_thread_run_loop",
        "_make_thread_for_runloop",
        "test_download_worker_times_out_and_exits",
        "test_run_no_files_logs_warning",
    ],
    "tests/test_creator_run_flow.py": [
        "test_creator_download_thread_run_with_fake_workers",
        "test_generate_filename_respects_existing_creator_folder",
        "test_run_handles_makedirs_oserror",
        "DummySettingsTab",
        "DummySettings",
        "test_creator_folder_not_duplicated",
        "FakeFileResponse",
        "FakeAPIResponse",
        "FakeSessionMulti",
        "FakeHashDB",
        "test_creator_run_downloads_all_files",
        "test_creator_skips_existing_hash_entry",
        "test_stress_run_reduced_concurrency_does_not_crash",
        "test_download_worker_invokes_download_file",
        "test_safe_emit_ignores_when_destroyed",
        "test_file_preparation_thread_run",
        "test_creator_download_thread_run_simulated",
    ],
}

TITLES = {
    "tests/test_creator_fetch_and_preview.py": (
        "Detection, fetching and preview paths for the Creator tab."
    ),
    "tests/test_creator_download_core.py": (
        "Single-file download behaviour: names, sizes, streaming and the hash DB."
    ),
    "tests/test_creator_download_retries.py": (
        "Retry, cancellation and run-loop behaviour of the download thread."
    ),
    "tests/test_creator_run_flow.py": (
        "Whole-run behaviour: folders, hash DB reuse, stress and file preparation."
    ),
}

# Helpers that now live in tests.factories (definitions dropped, calls rewritten).
DROP = {
    "make_settings",
    "make_thread",
    "make_settings__from_creator_download_run_loop",
    "make_settings__from_creator_downloader_hashdb_mismatch",
    "make_settings__from_creator_downloader_retries_and_cancellation",
    "make_settings__from_creator_downloader_retry_and_cancel",
    "make_settings__from_creator_downloader_streamed_download",
    "make_settings__from_creator_folder_and_run_errors",
    "make_settings__from_creator_run_and_hashdb",
    "make_settings__from_creator_validation_and_worker",
    "FakeSessionAlwaysError__from_creator_downloader_retry_and_cancel",
    "FakeResponse__from_creator_downloader_streamed_download",
    "FakeSession__from_creator_downloader_streamed_download",
    "DummySignal__from_creator_run_loop",
    "DummySettingsTab__from_creator_stress_safety",
    "DummySettings__from_creator_stress_safety",
}

REPLACEMENTS = [
    (
        "make_settings__from_creator_download_run_loop()",
        "make_settings(simultaneous_downloads=2)",
    ),
    (
        "make_settings__from_creator_downloader_hashdb_mismatch(tmp_path)",
        "make_settings(file_download_max_retries=2)",
    ),
    (
        "make_settings__from_creator_downloader_retries_and_cancellation()",
        "make_settings()",
    ),
    (
        "make_settings__from_creator_downloader_retry_and_cancel(tmp_path)",
        "make_settings()",
    ),
    (
        "make_settings__from_creator_downloader_streamed_download(tmp_path)",
        "make_settings()",
    ),
    ("make_settings__from_creator_folder_and_run_errors()", "make_settings()"),
    ("make_settings__from_creator_run_and_hashdb()", "make_settings()"),
    ("make_settings__from_creator_validation_and_worker()", "make_settings()"),
    (
        "FakeSessionAlwaysError__from_creator_downloader_retry_and_cancel()",
        "AlwaysFailingSession()",
    ),
    ("DummySignal__from_creator_run_loop()", "RecordingSignal()"),
    (
        "DummySettings__from_creator_stress_safety()",
        'make_settings(template="{post_id}_{orig_name}")',
    ),
]

FACTORY_NAMES = [
    "make_settings",
    "make_thread",
    "AlwaysFailingSession",
    "SessionReturning",
    "StreamingResponse",
    "RecordingSignal",
]


def node_start(node):
    line = node.lineno
    for decorator in getattr(node, "decorator_list", []):
        line = min(line, decorator.lineno)
    return line


def main():
    source = SOURCE.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=False)
    tree = ast.parse(source)

    imports = []
    nodes = {}
    order = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append("\n".join(lines[node.lineno - 1 : node.end_lineno]))
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            nodes[node.name] = "\n".join(lines[node_start(node) - 1 : node.end_lineno])
            order.append(node.name)

    assigned = [name for names in BUCKETS.values() for name in names]
    missing = [name for name in assigned if name not in nodes]
    unassigned = [name for name in order if name not in assigned and name not in DROP]
    if missing or unassigned:
        raise SystemExit(f"missing={missing} unassigned={unassigned}")

    for path, names in BUCKETS.items():
        sections = []
        for name in names:
            body = nodes[name]
            for old, new in REPLACEMENTS:
                body = body.replace(old, new)
            body = re.sub(
                r"FakeSession__from_creator_downloader_streamed_download\(\s*chunks\s*\)",
                "SessionReturning(StreamingResponse(chunks))",
                body,
            )
            sections.append(body)
        text = "\n\n\n".join(sections)
        used = [name for name in FACTORY_NAMES if name + "(" in text]
        header = f'"""{TITLES[path]}"""\n\n' + "\n".join(imports)
        if used:
            header += "\nfrom tests.factories import " + ", ".join(sorted(used))
        pathlib.Path(path).write_text(
            header + "\n\n\n" + text + "\n", encoding="utf-8", newline=""
        )
        print(f"{path}: {len(names)} node(s), factories={used}")

    SOURCE.unlink()
    print("removed", SOURCE)


if __name__ == "__main__":
    main()

