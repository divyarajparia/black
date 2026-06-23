"""
Characterization tests for count_chars_in_width.

These cover behaviour that the PR should NOT change: cases where the
cumulative width does NOT land exactly on the max_width boundary, so the
>= vs > distinction is irrelevant.  Golden values were captured on
verify_base (the state immediately before PR #13 landed).
"""

import pytest
from black.strings import count_chars_in_width


# ── Non-boundary characterization goldens (same on base & PR) ───────────────

def test_empty_string_any_width():
    """Empty string always yields 0 regardless of max_width."""
    assert count_chars_in_width("", 5) == 0
    assert count_chars_in_width("", 0) == 0
    assert count_chars_in_width("", 88) == 0


def test_all_ascii_fits_entirely():
    """When total width < max_width, all characters are returned."""
    assert count_chars_in_width("hello", 10) == 5


def test_max_width_zero_returns_zero():
    """max_width=0 means no character can fit; result must be 0."""
    assert count_chars_in_width("abc", 0) == 0
    assert count_chars_in_width("hello", 0) == 0


def test_fullwidth_char_does_not_fit_at_width_one():
    """A fullwidth (width=2) char cannot fit in max_width=1; returns 0."""
    fw = "\u4e2d"  # 中, display width 2
    assert count_chars_in_width(fw, 1) == 0


def test_ascii_then_fullwidth_partial():
    """
    'a' + fullwidth_char with max_width=2:
    - 'a' (width 1) fits, total=1
    - fullwidth (width 2) would make total 3 > 2 → return 1
    Same on both base and PR (cumulative never equals max_width exactly
    at the boundary step).
    """
    fw = "\u4e2d"
    assert count_chars_in_width("a" + fw, 2) == 1
