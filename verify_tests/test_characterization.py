"""
Characterization tests for count_chars_in_width.

These assert behavior that should NOT change between verify_base and verify_pr.
Goldens were captured by running the function on verify_base (the pre-PR state).
Only non-boundary inputs are included here — inputs where base and PR agree.
"""

import pytest
from black.strings import count_chars_in_width


# ---------------------------------------------------------------------------
# Non-boundary ASCII inputs (base == PR for all of these)
# ---------------------------------------------------------------------------

def test_empty_string_any_width():
    """Empty string always returns 0 regardless of max_width."""
    assert count_chars_in_width("", 0) == 0
    assert count_chars_in_width("", 5) == 0
    assert count_chars_in_width("", 10000) == 0


def test_ascii_strictly_below_boundary():
    """Returns correct count when cumulative width never reaches max_width."""
    # 'abc' has total width 3; max_width=10 -> all 3 chars fit
    assert count_chars_in_width("abc", 10) == 3
    # 'hello world' (width 11) with max_width=88 -> all 11 chars fit
    assert count_chars_in_width("hello world", 88) == 11
    # 'hello world' with very large max -> all fit
    assert count_chars_in_width("hello world", 10000) == 11


def test_ascii_width_zero_returns_zero():
    """max_width=0 always returns 0 — no chars fit in zero width."""
    assert count_chars_in_width("abc", 0) == 0
    assert count_chars_in_width("z", 0) == 0


def test_ascii_truncated_strictly_below():
    """When max_width < total but not at exact boundary, truncation is stable."""
    # 'abc' (width=3), max_width=2 -> first char 'a' (cum=1) fits,
    # second char 'b' would push to cum=2 which is < 3, but third 'c' pushes to 3.
    # On base (>=): returns i=1 when cum=2 >= 2 (i=1 is second char iteration)
    # Wait: base uses >=, so at i=1, width=1, total_width=1, width+total=2 >= 2 -> return 1
    # PR uses >: 2 > 2 is False, so continues; at i=2, width+total=3 > 2 -> return 2
    # For max_width=2, 'abc': BASE=1, PR=2 — this IS a boundary, skip it here.
    #
    # Use max_width=1 for 'abc': base: i=0,width=1,total=0, 1+0=1 >= 1 -> return 0
    # PR: 1 > 1 is False, continues; i=1, 1+1=2 > 1 -> return 1
    # ALSO a boundary. We test only strictly-interior cases:
    # 'abcde' max_width=3: i=0 cum=1<3(base>=: no), i=1 cum=2<3(no), i=2 cum=3 -> base returns 2, PR: 3>3=False, i=3 cum=4>3 -> return 3
    # ALSO boundary at i=2. Use max_width=4: i=3 cum=4 -> boundary again.
    # Use 'abcde' max_width=6: total=5, all fit; both return 5. Non-boundary.
    assert count_chars_in_width("abcde", 6) == 5
    assert count_chars_in_width("abcde", 100) == 5


def test_cjk_strictly_below_boundary():
    """CJK chars (width=2 each) when max_width > total width -> all chars fit."""
    cjk2 = "\u4e2d\u6587"  # two CJK, total width 4
    assert count_chars_in_width(cjk2, 5) == 2
    assert count_chars_in_width(cjk2, 10) == 2
    assert count_chars_in_width(cjk2, 10000) == 2


def test_cjk_strictly_truncated():
    """CJK truncation at a width that is strictly between char boundaries."""
    # '\u4e2d\u6587' (widths 2,2): max_width=3
    # base: i=0,w=2,tot=0 -> 2+0=2 not>=3; tot=2; i=1,w=2,tot=2 -> 4>=3 -> return 1
    # PR:   i=0 -> 2>3? No; tot=2; i=1 -> 4>3? Yes -> return 1
    # Both return 1 — non-boundary case, safe as characterization golden.
    assert count_chars_in_width("\u4e2d\u6587", 3) == 1


def test_cjk_zero_width_budget():
    """max_width=0 returns 0 even for wide chars."""
    assert count_chars_in_width("\u4e2d", 0) == 0
    assert count_chars_in_width("\u4e2d\u6587", 0) == 0


def test_mixed_ascii_cjk_non_boundary():
    """Mixed ASCII+CJK string with budget that triggers mid-string (not at boundary)."""
    # 'a' + CJK + 'b': widths 1, 2, 1; max_width=3
    # base: i=0,w=1,tot=0->1<3; tot=1; i=1,w=2,tot=1->3>=3->return 1
    # PR:   i=1 -> 3>3? No; tot=3; i=2,w=1,tot=3->4>3->return 2
    # Boundary at i=1 (cum hits exactly 3). Skip; use max_width=2:
    # i=0,w=1,tot=0->1<2; tot=1; i=1,w=2,tot=1->3>=2->return 1 (base)
    # PR: 3>2? Yes -> return 1. SAME result (not a boundary of >=/>).
    # max_width=2: both return 1.
    assert count_chars_in_width("a\u4e2db", 2) == 1
