"""
Intent-aware tests for PR #13: fix off-by-one in count_chars_in_width.

The PR changes `width + total_width >= max_width` to `width + total_width > max_width`
so that a character whose cumulative width exactly equals max_width is
INCLUDED (counted) rather than excluded.

Each test here MUST:
  - FAIL on verify_base  (old >= operator)
  - PASS on verify_pr    (new >  operator)

Verified by running both branches before finalising.
"""

import pytest
from black.strings import count_chars_in_width


def test_single_ascii_char_fits_exactly():
    """
    'a' has width 1; max_width=1.
    After fix: 1+0 > 1 is False → 'a' is counted → result=1.
    On base:   1+0 >= 1 is True  → returns 0 (wrong).
    """
    result = count_chars_in_width("a", 1)
    assert result == 1, (
        f"Expected 1 (character whose width exactly equals max_width must be included), "
        f"got {result}"
    )


def test_two_ascii_chars_fit_exactly():
    """
    'ab' has total width 2; max_width=2.
    After fix: both chars are included → result=2.
    On base:   second char is excluded → result=1 (wrong).
    """
    result = count_chars_in_width("ab", 2)
    assert result == 2, (
        f"Expected 2 (both chars fit exactly in max_width=2), got {result}"
    )


def test_ascii_truncated_at_exact_boundary():
    """
    'hello' (width=5), max_width=3.
    After fix: chars h(1),e(2),l(3) are all included → result=3.
    On base:   third char 'l' brings total to 3 which >= 3 → excluded → result=2 (wrong).
    """
    result = count_chars_in_width("hello", 3)
    assert result == 3, (
        f"Expected 3 chars fit within max_width=3, got {result}"
    )


def test_fullwidth_char_fits_exactly():
    """
    Single fullwidth char '中' (width=2), max_width=2.
    After fix: 2+0 > 2 is False → char is counted → result=1.
    On base:   2+0 >= 2 is True  → returns 0 (wrong).
    """
    fw = "\u4e2d"  # 中, display width 2
    result = count_chars_in_width(fw, 2)
    assert result == 1, (
        f"Expected 1 (fullwidth char width==max_width must be included), got {result}"
    )


def test_ascii_plus_fullwidth_exact_boundary():
    """
    'a' + '中': widths 1+2=3, max_width=3.
    After fix: both chars fit exactly → result=2.
    On base:   fullwidth char is excluded at boundary → result=1 (wrong).
    """
    fw = "\u4e2d"
    result = count_chars_in_width("a" + fw, 3)
    assert result == 2, (
        f"Expected 2 chars fit exactly in max_width=3 (1+2==3), got {result}"
    )


def test_two_fullwidth_chars_fit_exactly():
    """
    '中中': widths 2+2=4, max_width=4.
    After fix: both fullwidth chars are included → result=2.
    On base:   second char excluded → result=1 (wrong).
    """
    fw = "\u4e2d"
    result = count_chars_in_width(fw * 2, 4)
    assert result == 2, (
        f"Expected 2 fullwidth chars fit exactly in max_width=4, got {result}"
    )
