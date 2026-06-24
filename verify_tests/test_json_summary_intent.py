"""
Intent-aware tests for PR #30: --json-summary / Report.to_json().

These tests:
- FAIL on verify_base (main before PR) because to_json() does not exist there
  and the --json-summary CLI flag is absent.
- PASS on verify_pr (the PR head) because the feature is fully implemented.
"""
import json
import subprocess
import sys
import tempfile
import os
import pytest
from pathlib import Path

from black.report import Report, Changed


# ---------------------------------------------------------------------------
# Direct Report.to_json() tests (unit level, calling internal API directly
# because to_json() is genuinely NEW and only reachable this way pre-CLI).
# ---------------------------------------------------------------------------

def test_to_json_exists():
    """Report.to_json must be present (fails on base where it's absent)."""
    r = Report()
    assert hasattr(r, "to_json"), "Report.to_json() not found — PR not applied"
    assert callable(r.to_json)


def test_to_json_empty_run_is_parseable():
    """to_json() on an empty report produces valid JSON with zeros and empty lists."""
    r = Report()
    js = r.to_json()
    data = json.loads(js)  # must not raise
    assert data["reformatted"] == 0
    assert data["unchanged"] == 0
    assert data["failed"] == 0
    assert data["total"] == 0
    assert data["reformatted_files"] == []
    assert data["unchanged_files"] == []
    assert data["failed_files"] == []
    assert isinstance(data["duration_seconds"], float)
    assert data["duration_seconds"] >= 0.0
    assert data["return_code"] == 0


def test_to_json_counts_and_lists_match_after_done_and_failed():
    """After done/failed calls, JSON counts must equal list lengths and sum to total."""
    r = Report()
    r.done(Path("a.py"), Changed.YES)
    r.done(Path("b.py"), Changed.NO)
    r.done(Path("c.py"), Changed.NO)
    r.failed(Path("d.py"), "oops")

    js = r.to_json()
    data = json.loads(js)

    assert data["reformatted"] == 1
    assert data["unchanged"] == 2
    assert data["failed"] == 1
    assert data["total"] == data["reformatted"] + data["unchanged"] + data["failed"]
    assert len(data["reformatted_files"]) == data["reformatted"]
    assert len(data["unchanged_files"]) == data["unchanged"]
    assert len(data["failed_files"]) == data["failed"]
    assert "a.py" in data["reformatted_files"]
    assert "b.py" in data["unchanged_files"]
    assert "c.py" in data["unchanged_files"]
    assert "d.py" in data["failed_files"]


def test_to_json_indent_none_produces_compact_json():
    """to_json(indent=None) must produce compact, parseable JSON (no newlines/extra spaces)."""
    r = Report()
    r.done(Path("x.py"), Changed.YES)
    js = r.to_json(indent=None)
    data = json.loads(js)  # must parse
    assert "\n" not in js  # compact = no newlines
    assert data["reformatted"] == 1


def test_to_json_default_indent_is_2():
    """Default indent=2 must produce indented JSON (multiple lines)."""
    r = Report()
    r.done(Path("x.py"), Changed.YES)
    js = r.to_json()
    assert "\n" in js  # indented has newlines


def test_to_json_return_code_123_on_failure():
    """return_code in JSON must be 123 when there are failures."""
    r = Report()
    r.failed(Path("broken.py"), "syntax error")
    data = json.loads(r.to_json())
    assert data["return_code"] == 123


# ---------------------------------------------------------------------------
# CLI test: --json-summary flag emits JSON to stdout
# ---------------------------------------------------------------------------

def _run_black(*args):
    """Run black via subprocess, return (stdout, stderr, returncode)."""
    result = subprocess.run(
        [sys.executable, "-m", "black"] + list(args),
        capture_output=True,
        text=True,
    )
    return result.stdout, result.stderr, result.returncode


def test_cli_json_summary_flag_emits_json_to_stdout():
    """--json-summary causes a JSON object to appear on stdout; without flag stdout is empty."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("x = 1\n")
        fname = f.name
    try:
        # Without --json-summary: stdout should be empty (human output goes to stderr)
        stdout_no_flag, _, _ = _run_black("--check", fname)
        assert stdout_no_flag == "", (
            f"Without --json-summary, stdout must be empty; got: {stdout_no_flag!r}"
        )

        # With --json-summary: stdout must contain valid JSON
        stdout_flag, _, _ = _run_black("--check", "--json-summary", fname)
        data = json.loads(stdout_flag)  # must not raise
        assert "total" in data
        assert "reformatted" in data
        assert "unchanged" in data
        assert "failed" in data
        assert "duration_seconds" in data
        assert "return_code" in data
    finally:
        os.unlink(fname)


def test_cli_json_summary_unchanged_file():
    """--json-summary on an already-formatted file reports 1 unchanged, 0 reformatted."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("x = 1\n")
        fname = f.name
    try:
        stdout, _, rc = _run_black("--check", "--json-summary", fname)
        data = json.loads(stdout)
        assert data["unchanged"] == 1
        assert data["reformatted"] == 0
        assert data["failed"] == 0
        assert data["total"] == 1
        assert data["return_code"] == 0
        assert fname in data["unchanged_files"]
    finally:
        os.unlink(fname)
