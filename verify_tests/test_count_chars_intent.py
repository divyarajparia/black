"""
Intent-aware tests for PR #17 — count_chars_in_width off-by-one fix.

These tests assert the NEW (correct) behavior after the PR.  They FAIL on
verify_base (which has `>=`, causing boundary characters to be excluded) and
PASS on verify_pr (which has `>`, correctly including boundary characters).

The claimed fix: when sum of character widths exactly equals max_width the
character at that position must be INCLUDED (counted), not excluded.  The `>=`
operator was returning i (the current index) before accumulating, which
under-counted by 1 at every exact-boundary position.
"""
import pytest
from black.strings import count_chars_in_width


class TestBoundaryInclusionFixed:
    """Characters whose cumulative width == max_width must be included."""

    CJK = "你好世界"   # 4 × width-2 chars

    def test_single_wide_char_exactly_at_max_width(self):
        """One CJK char (width=2) with max_width=2: must return 1 (included).

        On verify_base (>=): i=0, width=2, 2+0=2 >= 2 → return 0  ← WRONG
        On verify_pr  (>):   i=0, width=2, 2+0=2  > 2 → False; total=2; return 1 ← CORRECT
        """
        result = count_chars_in_width(self.CJK, 2)
        assert result == 1, (
            f"Expected 1 (boundary char included), got {result}. "
            "Likely running on verify_base (>= bug present)."
        )

    def test_two_wide_chars_exactly_at_max_width(self):
        """Two CJK chars (total width=4) with max_width=4: must return 2.

        On verify_base: i=1, width=2, 2+2=4 >= 4 → return 1  ← WRONG
        On verify_pr:   4 > 4? No; total=4; i=2, 2+4=6 > 4 → return 2  ← CORRECT
        """
        result = count_chars_in_width(self.CJK, 4)
        assert result == 2, (
            f"Expected 2 (boundary chars included), got {result}."
        )

    def test_three_wide_chars_exactly_at_max_width(self):
        """Three CJK chars (total width=6) with max_width=6: must return 3.

        On verify_base: i=2, 2+4=6 >= 6 → return 2  ← WRONG
        On verify_pr:   6 > 6? No; total=6; i=3, 2+6=8 > 6 → return 3  ← CORRECT
        """
        result = count_chars_in_width(self.CJK, 6)
        assert result == 3, (
            f"Expected 3 (boundary chars included), got {result}."
        )

    def test_all_wide_chars_exactly_at_max_width(self):
        """All four CJK chars (total width=8) with max_width=8: must return 4.

        On verify_base: i=3, 2+6=8 >= 8 → return 3  ← WRONG
        On verify_pr:   8 > 8? No; loop ends; return len=4  ← CORRECT
        """
        result = count_chars_in_width(self.CJK, 8)
        assert result == 4, (
            f"Expected 4 (all chars fit exactly), got {result}."
        )

    def test_ascii_exact_boundary(self):
        """'hello' (5 ASCII chars, each width=1) with max_width=5: must return 5.

        On verify_base: i=4, 1+4=5 >= 5 → return 4  ← WRONG
        On verify_pr:   5 > 5? No; loop ends; return 5  ← CORRECT
        """
        result = count_chars_in_width("hello", 5)
        assert result == 5, (
            f"Expected 5 (boundary inclusion), got {result}."
        )

    def test_monotone_in_max_width(self):
        """Widening max_width must never decrease the character count.

        This invariant holds on both branches for non-boundary inputs but the
        `>=` bug can cause non-monotone results at consecutive boundary values
        if there is mixed-width content. The PR restores a strictly monotone
        response curve.
        """
        s = "你A好B"   # alternating wide (2) and ASCII (1): widths = 2,1,2,1
        prev = 0
        for w in range(0, 10):
            cur = count_chars_in_width(s, w)
            assert cur >= prev, (
                f"Monotone violated: count at max_width={w} ({cur}) < "
                f"count at max_width={w-1} ({prev})"
            )
            prev = cur
