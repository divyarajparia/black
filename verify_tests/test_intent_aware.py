"""
Intent-aware tests for PR #25: fix off-by-one in count_chars_in_width.

The PR changes `>=` to `>` in the stopping condition, so a character whose
cumulative width lands EXACTLY on max_width is now counted as fitting.

These tests MUST:
  - FAIL on verify_base  (old `>=` operator under-counts by 1 at boundary)
  - PASS on verify_pr    (new `>` operator counts correctly)

Verified manually:
  verify_base: count_chars_in_width('a', 1) == 0  (wrong, causes test to fail)
  verify_pr:   count_chars_in_width('a', 1) == 1  (correct, test passes)
"""

import pytest
from black.strings import count_chars_in_width


# ---------------------------------------------------------------------------
# Boundary: ASCII char exactly fills max_width
# ---------------------------------------------------------------------------

def test_single_ascii_char_exactly_fills_max_width():
    """
    A single ASCII char (width 1) should fit exactly in max_width=1.

    Old code (>=): i=0, width+total=1+0=1 >= 1 -> return 0  (WRONG)
    New code (>):  1 > 1 is False -> loop ends -> return len('a')=1  (CORRECT)
    """
    result = count_chars_in_width("a", 1)
    assert result == 1, (
        f"Expected 1 (single ASCII char fits in width 1), got {result}. "
        "This indicates the old >= operator is still in use."
    )


def test_two_ascii_chars_exactly_fill_max_width():
    """
    Two ASCII chars (total width 2) should both fit in max_width=2.

    Old code (>=): i=1, w+tot=1+1=2 >= 2 -> return 1  (WRONG — stops early)
    New code (>):  2 > 2 is False -> continues -> return len('ab')=2  (CORRECT)
    """
    result = count_chars_in_width("ab", 2)
    assert result == 2, (
        f"Expected 2 (two ASCII chars fit exactly in width 2), got {result}. "
        "This indicates the old >= operator is still in use."
    )


def test_single_cjk_char_exactly_fills_max_width():
    """
    A single CJK char (width=2) should fit exactly in max_width=2.

    Old code (>=): i=0, 2+0=2 >= 2 -> return 0  (WRONG)
    New code (>):  2 > 2 is False -> return 1  (CORRECT)
    """
    cjk = "\u4e2d"  # U+4E2D, East Asian wide char, width=2
    result = count_chars_in_width(cjk, 2)
    assert result == 1, (
        f"Expected 1 (CJK char of width 2 fits in max_width=2), got {result}. "
        "This indicates the old >= operator is still in use."
    )


def test_two_cjk_chars_exactly_fill_max_width():
    """
    Two CJK chars (total width 4) should both fit in max_width=4.

    Old code (>=): i=1, 2+2=4 >= 4 -> return 1  (WRONG)
    New code (>):  4 > 4 is False -> return 2  (CORRECT)
    """
    cjk2 = "\u4e2d\u6587"  # two CJK, each width 2
    result = count_chars_in_width(cjk2, 4)
    assert result == 2, (
        f"Expected 2 (two CJK chars of total width 4 fit in max_width=4), got {result}. "
        "This indicates the old >= operator is still in use."
    )


def test_ascii_long_string_last_char_at_exact_boundary():
    """
    A string of 88 ASCII chars should fit entirely in max_width=88.

    Old code (>=): returns 87 at i=87 when cum hits 88  (WRONG — stops 1 early)
    New code (>):  88 > 88 is False -> returns 88  (CORRECT)
    """
    s = "x" * 88
    result = count_chars_in_width(s, 88)
    assert result == 88, (
        f"Expected 88 (88 ASCII chars fit in width 88), got {result}. "
        "This indicates the old >= operator is still in use."
    )
