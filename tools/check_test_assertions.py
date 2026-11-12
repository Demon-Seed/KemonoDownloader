"""Fail when a change lowers the test suite's assertion count without src.

Rationale: in an AI-maintained repo the tests are the only independent oracle,
and editing an assertion is editing the specification. A behaviour change may
update the tests, but it must also change the code that behaviour lives in.

Moves are allowed: the rule compares the total assertion count, so splitting a
test module (assertions leave one file and appear in another) passes, while
deleting or weakening assertions without touching `src/` fails.

Usage:
    python tools/check_test_assertions.py --base origin/main
    python tools/check_test_assertions.py --staged
"""

import argparse
import ast
import os
import subprocess
import sys


def git(*args):
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def rev_exists(rev):
    return git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").returncode == 0


def changed_files(base, head=None, staged=False):
    if staged:
        out = git("diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB")
    else:
        out = git(
            "diff", "--name-only", "--diff-filter=ACDMRTUXB", base, head or "HEAD"
        )
    return [line for line in out.stdout.splitlines() if line.strip()]


def file_at(rev, path, staged=False):
    if staged and rev is None:
        result = git("show", f":{path}")
    else:
        result = git("show", f"{rev}:{path}")
    return result.stdout if result.returncode == 0 else ""


def count_asserts(text):
    if not text:
        return 0
    try:
        return sum(isinstance(node, ast.Assert) for node in ast.walk(ast.parse(text)))
    except SyntaxError:
        return text.count("assert ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("BASE_REF", "HEAD~1"))
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()

    base = args.base
    if not args.staged and not rev_exists(base):
        fallback = "HEAD~1"
        if base == fallback or not rev_exists(fallback):
            print(f"base {base!r} not found and no previous commit; skipping")
            return 0
        print(f"base {base!r} not found; using {fallback}")
        base = fallback

    files = changed_files(base, args.head, args.staged)
    if not files:
        print("no changed files")
        return 0

    src_changed = any(path.startswith("src/") for path in files)
    total_before = total_after = 0
    drops = []
    for path in files:
        if not (path.startswith("tests/") and path.split("/")[-1].startswith("test_")):
            continue
        before = count_asserts(file_at(base, path))
        after = count_asserts(
            file_at(None, path, staged=True)
            if args.staged
            else file_at(args.head, path)
        )
        total_before += before
        total_after += after
        if after < before:
            drops.append((path, before, after))

    delta = total_after - total_before
    print(f"test assertions: {total_before} -> {total_after} ({delta:+d})")
    for path, before, after in drops:
        print(f"  dropped {before - after:3d} in {path} ({before} -> {after})")

    if delta >= 0 or not drops:
        return 0
    if src_changed:
        print("assertions dropped, but src changed: name the behaviour change in")
        print("the commit message and make sure each dropped test is gone on purpose.")
        return 0
    if os.environ.get("ALLOW_ASSERT_DROP") == "1":
        print("ALLOW_ASSERT_DROP=1: assertion drop allowed by the caller")
        return 0

    print(
        "FAIL: this change removes test assertions without touching src/.\n"
        "Never weaken an assertion to make a failure pass. Change the code the\n"
        "behaviour lives in, or set ALLOW_ASSERT_DROP=1 for a deliberate,\n"
        "documented test-only cleanup."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
