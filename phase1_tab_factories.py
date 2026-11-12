"""One-off: move test_creator_tab_flow.py's helpers onto tests.factories."""

import ast
import pathlib

PATH = pathlib.Path("tests/test_creator_tab_flow.py")

DELETE = {
    "make_parent",
    "make_parent__from_creator_detection_ui",
    "make_parent__from_creator_downloader_tab_behavior",
    "make_parent__from_creator_downloader_tab_flow_ui",
    "make_parent__from_creator_tab_handlers",
    "make_parent__from_creator_tab_population_and_filter",
    "make_parent__from_creator_tab_ui_small",
    "FakeSignal",
    "FakeSignal__from_creator_downloader_tab_flow_ui",
    "SimpleSignal",
    "FinishedSignal",
    "DummyParent",
    "StoreParent",
    "StoreParent__from_logs_window",
}

RENAMES = {
    "FakePostDetectionThread__from_creator_downloader_tab_flow_ui": (
        "FakePostDetectionThreadWithBatch"
    ),
    "test_logs_window_download_and_clear__from_logs_window": (
        "test_logs_window_download_and_clear_through_store"
    ),
}

REPLACEMENTS = [
    ("make_parent__from_creator_detection_ui(tmp_path)", "make_tab_parent(tmp_path)"),
    (
        "make_parent__from_creator_downloader_tab_behavior(tmp_path)",
        "make_tab_parent(tmp_path, window=True)",
    ),
    (
        "make_parent__from_creator_downloader_tab_flow_ui(tmp_path)",
        "make_tab_parent(tmp_path, window=True)",
    ),
    (
        "make_parent__from_creator_tab_handlers(tmp_path)",
        "make_tab_parent(tmp_path)",
    ),
    (
        "make_parent__from_creator_tab_population_and_filter(tmp_path)",
        "make_tab_parent(tmp_path, window=True)",
    ),
    (
        "make_parent__from_creator_tab_ui_small(tmp_path)",
        "make_tab_parent(tmp_path, window=True)",
    ),
    ("make_parent(tmp_path)", "make_tab_parent(tmp_path)"),
    ("FakeSignal__from_creator_downloader_tab_flow_ui()", "Signal()"),
    ("FakeSignal()", "Signal()"),
    ("SimpleSignal()", "Signal()"),
    ("FinishedSignal()", "Signal()"),
    ("StoreParent__from_logs_window(", "LogStoreParent("),
    ("StoreParent(", "LogStoreParent("),
    ("DummyParent()", "LogStoreParent()"),
]

IMPORT = (
    "from tests.factories import FakeTabs, LogStoreParent, Signal, make_tab_parent"
)


def node_start(node):
    line = node.lineno
    for decorator in getattr(node, "decorator_list", []):
        line = min(line, decorator.lineno)
    return line


def main():
    source = PATH.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    removals = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in DELETE:
            removals.append((node_start(node) - 1, node.end_lineno))
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            for child in node.body:
                if isinstance(child, ast.ClassDef) and child.name in DELETE:
                    removals.append((node_start(child) - 1, child.end_lineno))

    for start, end in sorted(removals, reverse=True):
        del lines[start:end]

    text = "".join(lines)
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    for old, new in RENAMES.items():
        text = text.replace(old, new)

    lines = text.splitlines(keepends=True)
    last_import = 0
    for node in ast.parse("".join(lines)).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import = max(last_import, node.end_lineno)
    lines.insert(last_import, IMPORT + "\n")
    PATH.write_text("".join(lines), encoding="utf-8", newline="")
    print(f"removed {len(removals)} helper node(s)")


if __name__ == "__main__":
    main()
