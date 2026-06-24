"""
Differential fuzz / stability test for PR #30 (Report.to_json / --json-summary).

Seeded, reproducible: uses random.Random(1234) so every run is identical.
Tests ~150+ (input, config) combinations for:
  - No unexpected internal errors (AttributeError, KeyError, etc.)
  - JSON parseability invariant
  - counts_match_file_lists invariant
  - total_correct invariant
  - duration_non_negative invariant

Runs on BOTH verify_base and verify_pr. On verify_base, to_json() is absent,
so this test will fail fast — that is correct: it characterizes the post-PR
behaviour and a missing method is itself a regression signal.

VERIFY_STRESS_GRID env var (JSON): overrides the parameter grid.
Falls back to ANALYSIS stress_params values when not set.
"""
import json
import os
import random
import itertools
import pytest
from pathlib import Path

# Try importing the new method; if absent the test fails gracefully.
from black.report import Report, Changed

# ---------------------------------------------------------------------------
# Config grid — read from env or fall back to ANALYSIS stress_params
# ---------------------------------------------------------------------------
_RAW_GRID = os.environ.get("VERIFY_STRESS_GRID", "{}")
try:
    _GRID = json.loads(_RAW_GRID)
except json.JSONDecodeError:
    _GRID = {}

_FILE_COUNT_VALUES = _GRID.get("file_count_per_outcome", [0, 1, 2, 10])
# indent: env grid uses strings for JSON compatibility; convert None-sentinel
_INDENT_RAW = _GRID.get("indent", [None, 0, 2, 4])
_INDENT_VALUES = [None if v is None else int(v) for v in _INDENT_RAW]


# ---------------------------------------------------------------------------
# Seed-based input generation
# ---------------------------------------------------------------------------

_RNG = random.Random(1234)

_SEED_PATHS = [
    "a.py", "b.py", "c/d.py", "some/nested/module.py",
    "test_foo.py", "very_long_module_name_that_goes_on.py",
    "α_unicode.py", "path with spaces/file.py",
]

def _generate_inputs(n: int = 150):
    """
    Yield (reformatted_count, unchanged_count, failed_count) tuples.
    Covers the full matrix of _FILE_COUNT_VALUES crossed with itself x3,
    then fills up to n with randomly mutated variants.
    """
    # Deterministic cross-product seeds first
    for rf, un, fa in itertools.product(_FILE_COUNT_VALUES, repeat=3):
        yield (rf, un, fa)

    # Random fill to reach n total
    yielded = len(_FILE_COUNT_VALUES) ** 3
    while yielded < n:
        rf = _RNG.choice(_FILE_COUNT_VALUES + [_RNG.randint(0, 20)])
        un = _RNG.choice(_FILE_COUNT_VALUES + [_RNG.randint(0, 20)])
        fa = _RNG.choice(_FILE_COUNT_VALUES + [_RNG.randint(0, 5)])
        yield (rf, un, fa)
        yielded += 1


def _build_report(reformatted: int, unchanged: int, failed: int) -> Report:
    """Build a Report by calling done()/failed() the specified number of times."""
    r = Report()
    for i in range(reformatted):
        path = _SEED_PATHS[_RNG.randint(0, len(_SEED_PATHS) - 1)]
        r.done(Path(f"rf_{i}_{path}"), Changed.YES)
    for i in range(unchanged):
        path = _SEED_PATHS[_RNG.randint(0, len(_SEED_PATHS) - 1)]
        r.done(Path(f"un_{i}_{path}"), Changed.NO)
    for i in range(failed):
        path = _SEED_PATHS[_RNG.randint(0, len(_SEED_PATHS) - 1)]
        r.failed(Path(f"fa_{i}_{path}"), f"error_{i}")
    return r


# ---------------------------------------------------------------------------
# Actual fuzz test
# ---------------------------------------------------------------------------

def test_to_json_fuzz_invariants():
    """
    For ~150 (reformatted, unchanged, failed) combinations x all indent values:
    - to_json() must not raise any unexpected exception
    - output must be valid JSON (json_parseable invariant)
    - counts must match file list lengths (counts_match_file_lists invariant)
    - total must equal sum of three counts (total_correct invariant)
    - duration_seconds must be >= 0 (duration_non_negative invariant)
    """
    if not hasattr(Report, "to_json"):
        pytest.fail(
            "Report.to_json does not exist — PR #30 not applied. "
            "This test is expected to fail on verify_base."
        )

    iterations = 0
    MAX_ITERATIONS = 400  # cap to bound runtime

    for (rf, un, fa), indent in itertools.islice(
        itertools.product(_generate_inputs(150), _INDENT_VALUES),
        MAX_ITERATIONS,
    ):
        report = _build_report(rf, un, fa)

        # --- No unexpected internal error ---
        try:
            js = report.to_json(indent=indent)
        except (AttributeError, KeyError, IndexError, RecursionError, AssertionError) as exc:
            pytest.fail(
                f"Unexpected internal error in to_json("
                f"indent={indent!r}) for rf={rf} un={un} fa={fa}: {exc}"
            )

        # --- JSON parseable invariant ---
        try:
            data = json.loads(js)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"to_json(indent={indent!r}) produced non-parseable JSON "
                f"for rf={rf} un={un} fa={fa}: {exc}\nOutput: {js!r}"
            )

        # --- counts_match_file_lists invariant ---
        assert len(report._reformatted_files) == report.change_count, (
            f"_reformatted_files length {len(report._reformatted_files)} != "
            f"change_count {report.change_count} (rf={rf})"
        )
        assert len(report._unchanged_files) == report.same_count, (
            f"_unchanged_files length {len(report._unchanged_files)} != "
            f"same_count {report.same_count} (un={un})"
        )
        assert len(report._failed_files) == report.failure_count, (
            f"_failed_files length {len(report._failed_files)} != "
            f"failure_count {report.failure_count} (fa={fa})"
        )

        # --- total_correct invariant ---
        assert data["total"] == data["reformatted"] + data["unchanged"] + data["failed"], (
            f"total mismatch: {data['total']} != "
            f"{data['reformatted']}+{data['unchanged']}+{data['failed']}"
        )

        # --- duration_non_negative invariant ---
        assert data["duration_seconds"] >= 0.0, (
            f"duration_seconds {data['duration_seconds']} < 0 "
            f"(rf={rf} un={un} fa={fa})"
        )

        # --- JSON list lengths match counts in JSON ---
        assert len(data["reformatted_files"]) == data["reformatted"]
        assert len(data["unchanged_files"]) == data["unchanged"]
        assert len(data["failed_files"]) == data["failed"]

        iterations += 1

    assert iterations > 0, "No iterations were executed — check test logic"


def test_to_json_contextual_diversity():
    """
    Varied file-path shapes including unicode, spaces, deep nesting.
    Ensures to_json handles diverse path representations without error.
    """
    if not hasattr(Report, "to_json"):
        pytest.fail("Report.to_json does not exist — PR #30 not applied.")

    weird_paths = [
        Path("α/β/γ.py"),
        Path("path with spaces/module.py"),
        Path("a" * 200 + ".py"),
        Path("./relative/./path/../cleaned.py"),
        Path("C:\\windows\\style.py"),  # string will just be stored as-is
    ]
    r = Report()
    for p in weird_paths:
        r.done(p, Changed.YES)
    r.failed(Path("😀emoji.py"), "encoding issue")

    js = r.to_json()
    data = json.loads(js)
    assert data["reformatted"] == len(weird_paths)
    assert data["failed"] == 1
    assert data["total"] == len(weird_paths) + 1
