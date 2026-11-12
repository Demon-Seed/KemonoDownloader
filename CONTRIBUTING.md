# Contributing to KemonoDownloader

This repository is a **100% AI-coded fork** of KemonoDownloader: the
application code, the tests and most of the documentation are written by AI
agents working under human direction. People decide what the app must do and
how it will be proven; the agent writes the code, the tests and the evidence.

Because this is a personal fork, there is no external contribution process:
one maintainer directs the work and reviews it, and the rules below are the
working agreement between the maintainer and the agents.

That changes what a good change looks like. It is not accepted because the
diff reads plausibly. It is accepted when the suite exercises the behaviour,
the diff touches the code that behaviour lives in, and the author ran the
checks instead of claiming they would pass.

The maintainer is still accountable for everything merged. "The AI wrote it"
is not a defence for a regression.

## Table of Contents
- [How This Repository Is Built](#how-this-repository-is-built)
- [Non-Negotiable Rules](#non-negotiable-rules)
- [The Verification Contract](#the-verification-contract)
- [Working on a Change](#working-on-a-change)
- [Test Architecture](#test-architecture)
- [Reviewing AI-Generated Changes](#reviewing-ai-generated-changes)
- [Development Environment](#development-environment)
- [For AI Agents Working in This Repository](#for-ai-agents-working-in-this-repository)

## How This Repository Is Built

Work moves in one loop:

1. The maintainer states the behaviour and, where possible, the acceptance
   criteria.
2. An AI agent reads the code and writes a failing test for that behaviour.
3. The agent changes `src/` until the test passes and the full suite is green.
4. The maintainer reads the tests first, then the diff, then the evidence.

| Role | Who | Does |
|---|---|---|
| Director | maintainer | decides behaviour, acceptance criteria and priorities |
| Implementer | AI agent | reads the code, writes `src/` and tests, runs the checks, reports evidence |
| Reviewer | maintainer | reads tests before code, challenges unverifiable claims, accepts the change |

What is **not** useful: a large diff with a confident summary, a fix with no
test, or a green run whose assertions were edited to get there.

## Non-Negotiable Rules

These are the rules the tooling and the review process exist to enforce.

1. **Never weaken an assertion to make a failure pass.** An assertion may only
   change together with the source behaviour it describes. If the behaviour did
   not change, the test is right and the code is wrong.
   *Near-miss from this repo:* a cancellation test flipped
   `file_url in failed_files` to `not in`. That was correct only because
   `download_file` never records a cancel as a failure — and that had to be
   checked in `src/`, not assumed from a green run.
2. **A test change needs its source change.** If behaviour changes on purpose,
   `src/` and the tests change in the same commit, and the commit message names
   the behaviour. `tools/check_test_assertions.py` fails a change that lowers
   the suite's assertion count without touching `src/`.
3. **No vacuous tests.** Every test asserts something that can fail. No
   `assert True`, no assertion-free bodies, no test that only constructs an
   object. If a test cannot fail, delete it or make it test something.
4. **No hiding.** No `pytest.skip`/`xfail`, no `except Exception: pass`, no
   commented-out assertions, no quietly relaxed timeout to get green. A skip
   is allowed only for a platform limitation and must link an issue.
5. **No dead code or placeholders.** No `pass  # TODO`, no stub functions, no
   parameters added "for later". Delete what is not used; git remembers it.
6. **Tests are hermetic.** No network, no real `QSettings`, no writes outside
   `tmp_path`, no dependence on test order. The suite chdirs to a temporary
   directory for exactly this reason; keep it that way.
7. **The tree stays clean.** No generated artifacts, databases, logs, caches or
   recursively-created mock directories in a commit. `git status` must be clean
   apart from the files you meant to change.

## The Verification Contract

Run these from the repository root. A change is done when all of them pass and
the outputs are recorded in the commit message or the session report.

| Command | What it proves |
|---|---|
| `python -m pytest -q` | the suite still passes (1,099 tests at the time of writing) |
| `python -m pytest -q --cov=kemonodownloader --cov-report=term-missing --cov-fail-under=90` | coverage has not regressed (baseline 94.41%) |
| `python tools/check_test_assertions.py --staged` | no assertions were deleted or weakened silently |
| `pyright --project ./pyrightconfig.json` | types are clean (0 errors expected) |
| `pre-commit run --all-files` | black, isort, ruff and the local hooks are clean |
| `mutmut run --paths-to-mutate src/kemonodownloader/retry_policy.py` | the tests for a refactored module can actually fail |

CI runs the same set: the test matrix (Ubuntu, Windows and macOS across Python
3.9, 3.10 and 3.11), pyright, a coverage job with the 90% floor, and the
assertion guard against the base ref. A green local run is evidence; it is not
a substitute for CI.

### When a Guard Fires

- **Coverage floor**: add the test for the new branch. Do not lower the floor
  as a first move.
- **Assertion guard**: if behaviour changed on purpose, make sure `src/` is in
  the commit and add a `Behavior:` line to the message. If it was a test-only
  cleanup, justify it in the message and set `ALLOW_ASSERT_DROP=1`. If neither
  is true, the test is right and the change is wrong.
- **A surviving mutant**: the test that should have caught it is vacuous or
  missing. Fix the test; do not delete the mutant.

## Working on a Change

For an AI agent, in this order:

1. **Read before writing.** Open the modules and tests the change touches, plus
   `tests/factories.py` and the neighbouring topic file. Match existing naming
   and structure; do not introduce a second way to do the same thing.
2. **Write the reproduction first.** For a bug, add a test that fails for the
   stated reason, then change `src/` until it passes. A bug fix without a
   failing-first test is a guess.
3. **Keep the change small.** One behaviour per commit, one topic per test
   file. If a function needs 400 lines of new tests, it probably needs
   splitting first.
4. **Run the whole suite, not the touched file.** The failure you cause is
   usually in a test you did not open.
5. **Report what you actually ran.** Paste the commands and their output.
   "Tests should pass" is not a result; "1,099 passed in 50.02s" is.
6. **Say what you are unsure about.** A named uncertainty is useful; a
   confident summary of code you did not read is a defect.

### Commit Messages

```
fix(creator): stop recording cancellations as failures

Behavior: a cancelled download is deleted and is not added to failed_files;
it is retried on the next run instead of being reported as an error.

Tests: tests/test_creator_download_retries.py
```

- Subject: imperative, scoped (`creator`, `settings`, `paths`, `tests`, `ci`).
- `Behavior:` is required whenever tests or assertions change. It must name
  the user-visible rule, not the diff ("rename helper" is not a behaviour).
- `Tests:` is optional but appreciated: point at the test that would have
  caught the old behaviour.
- Separate refactors from behaviour changes. A rename commit that also changes
  behaviour is unreviewable.

## Test Architecture

The suite was consolidated from 132 files into topic modules; keep it that way.

- **`tests/factories.py`** — one factory per shape (`make_tab_parent`,
  `make_settings`, `make_thread`, response/session doubles). Tests import them.
  Do not copy a factory back into a test file, and do not name helpers after
  the module they came from.
- **Topic files** — `test_creator_fetch_and_preview.py`,
  `test_creator_download_core.py`, `test_creator_download_retries.py`,
  `test_creator_run_flow.py`. A module that grows past ~800 lines is a signal
  to split by behaviour, not to keep appending.
- **Naming** — `test_<behaviour>_<condition>`. No numeric suffixes, no duplicate
  test names, no `test_1`.
- **Isolation** — `tests/conftest.py` chdirs to `tmp_path` for every test and
  redirects `QSettings` to a temporary INI. Do not opt out.
- **Assertions** — assert the contract (what the caller observes), not the
  implementation (that a mock was called three times when the count is not the
  behaviour). If call order *is* the behaviour, assert it explicitly and say
  why.

### What "Covered" Means Here

Coverage is a floor, not a goal: 90% is enforced, the suite sits at 94.41%. A
line can be covered by a test that asserts nothing about it, which is why the
assertion guard and mutation testing exist. When you refactor a module
(`kd_paths`, `sqlite_store`, `retry_policy` are good first targets), run
`mutmut` before and after and compare the surviving mutants.

## Reviewing AI-Generated Changes

Read in this order:

1. **The request.** Is there a stated behaviour or acceptance criterion? A
   change with no defined behaviour cannot be reviewed.
2. **The tests.** Do they encode the requested behaviour, with assertions that
   would fail if it broke? Are they in the right topic file, using the
   factories?
3. **The source diff.** Does it touch the module the behaviour lives in? Does
   it do anything beyond the stated change?
4. **The evidence.** Are the commands and outputs present? Re-run them if
   anything looks off; CI is the shared oracle.

Reject the change regardless of green CI when:

- assertions were removed or loosened without a `Behavior:` line,
- a bug fix has no test that fails without the fix,
- a new `skip`, `xfail` or `except Exception: pass` appears,
- a test only proves that a mock was configured,
- generated files, credentials or user data are in the diff.

## Development Environment

1. Python **3.9+**.
2. Install runtime and test dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Install [Briefcase](https://briefcase.readthedocs.io/) to run the packaged
   app:
   ```bash
   pip install briefcase
   briefcase run
   ```
4. Headless runs (SSH, containers, CI) need the offscreen Qt platform:
   ```bash
   QT_QPA_PLATFORM=offscreen python -m pytest -q
   ```
   On Ubuntu, also install the Qt system libraries listed in
   `.github/workflows/ci.yml`.

**Tests must never touch real app settings.** `SettingsTab` opens
`QSettings("VoxDroid", "KemonoDownloader")`, which on Windows is the live
registry key (`HKCU\Software\VoxDroid\KemonoDownloader`). The autouse
`isolate_qsettings` fixture redirects every instance to a temporary INI, so
keep it autouse and never construct that `QSettings` in a test. To check for a
leak, snapshot the key with
`reg query "HKCU\Software\VoxDroid\KemonoDownloader"` before and after the
suite and compare.

## For AI Agents Working in This Repository

This section is part of your context on purpose.

1. Read this file and the module you are about to change before writing code.
2. Never edit an assertion to make a failure disappear. If a test fails, find
   out which side is wrong; change `src/` only when you can name the behaviour
   that is changing.
3. Do not add a test you cannot make fail. If you cannot write a failing
   version of a test, you do not understand the behaviour yet.
4. Run the full suite, the coverage command, pyright and the assert guard.
   Paste the real output.
5. Do not invent evidence. If a command was not run, say so.
6. Leave the repository clean: no scratch scripts, logs, databases or
   generated directories.
7. When you are done, write the `Behavior:` line first and the summary second.
   If you cannot write it, the change is probably a refactor — say that
   instead.

This fork is maintained for personal use. Upstream KemonoDownloader remains at
https://github.com/VoxDroid/KemonoDownloader; the MIT license and the
[LICENSE](LICENSE) file here still apply.
