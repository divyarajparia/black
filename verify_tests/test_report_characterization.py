"""
Characterization tests for black.report.Report.__str__ (and related fields).
These assert behavior that the PR must NOT change.
Golden values captured on verify_base (main before PR #30).
"""
import pytest
from pathlib import Path
from black.report import Report, Changed


# Goldens captured on verify_base (main prior to PR #30)
# Format: str(report) with ANSI codes intact

def test_empty_report_str():
    """Empty report renders as a lone dot."""
    r = Report()
    assert str(r) == "."


def test_one_unchanged_str():
    """One unchanged file renders the correct ANSI string."""
    r = Report()
    r.done(Path("foo.py"), Changed.NO)
    golden = "\x1b[34m1 file \x1b[0mleft unchanged."
    assert str(r) == golden


def test_one_reformatted_str():
    """One reformatted file renders the correct ANSI bold/blue string."""
    r = Report()
    r.done(Path("bar.py"), Changed.YES)
    golden = "\x1b[34m\x1b[1m1 file \x1b[0m\x1b[1mreformatted\x1b[0m."
    assert str(r) == golden


def test_one_failed_str():
    """One failed file renders the correct ANSI red string."""
    r = Report()
    r.failed(Path("bad.py"), "syntax error")
    golden = "\x1b[31m1 file failed to reformat\x1b[0m."
    assert str(r) == golden


def test_mixed_str_and_return_code():
    """Mixed outcomes render correct string and return code 123 (failure present)."""
    r = Report()
    r.done(Path("a.py"), Changed.YES)
    r.done(Path("b.py"), Changed.NO)
    r.failed(Path("c.py"), "oops")
    golden = (
        "\x1b[34m\x1b[1m1 file \x1b[0m\x1b[1mreformatted\x1b[0m, "
        "\x1b[34m1 file \x1b[0mleft unchanged, "
        "\x1b[31m1 file failed to reformat\x1b[0m."
    )
    assert str(r) == golden
    assert r.return_code == 123


def test_return_code_zero_when_all_unchanged():
    """Return code is 0 when all files are unchanged."""
    r = Report()
    r.done(Path("a.py"), Changed.NO)
    r.done(Path("b.py"), Changed.NO)
    assert r.return_code == 0


def test_return_code_one_check_mode_with_changed():
    """Return code is 1 in --check mode when a file would be reformatted."""
    r = Report(check=True)
    r.done(Path("dirty.py"), Changed.YES)
    assert r.return_code == 1
