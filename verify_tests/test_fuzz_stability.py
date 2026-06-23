"""
Seeded fuzz / stability test for count_chars_in_width (PR #25).

Runs on BOTH verify_base and verify_pr unchanged — any crash or invariant
violation surfaces as a regression on the PR head.

Design:
  - Fixed RNG seed (1234) for full reproducibility.
  - Seeds from PR diff context: boundary-probing strings (ASCII exact-boundary,
    CJK exact-boundary, mixed, empty).
  - Mutates seeds across ~200 inputs varying length, char class, and context.
  - Sweeps max_width from VERIFY_STRESS_GRID env var (or falls back to
    ANALYSIS stress_params values: [0, 1, 2, 88, 10000]).
  - Asserts four invariants per (input, max_width):
      1. result_in_range:       0 <= r <= len(s)
      2. fits_within_budget:    sum(char_width) of first r chars <= max_width
      3. greedy_maximality:     if r < len(s), cumulative width of r+1 chars > max_width
      4. monotone_in_width:     r(s,w1) <= r(s,w2) for w1 <= w2 (checked over grid)
"""

import json
import os
import random
import pytest
from black.strings import count_chars_in_width
from black._width_table import WIDTH_TABLE  # used to verify char_width indirectly


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def char_width(char: str) -> int:
    """Mirror of black.strings.char_width logic for use in assertions."""
    # Black uses wcwidth-style table; we reproduce using the same import path.
    # Fall back to unicodedata if needed.
    try:
        from black.strings import char_width as _cw
        return _cw(char)
    except ImportError:
        import unicodedata
        cat = unicodedata.east_asian_width(char)
        return 2 if cat in ("W", "F") else 1


def prefix_width(s: str, n: int) -> int:
    """Sum of char_width for first n characters of s."""
    return sum(char_width(c) for c in s[:n])


def assert_invariants(s: str, max_width: int) -> None:
    """Run count_chars_in_width and check all four invariants."""
    try:
        r = count_chars_in_width(s, max_width)
    except (AttributeError, IndexError, KeyError, RecursionError, AssertionError) as e:
        pytest.fail(
            f"Unexpected internal error on input {s!r}, max_width={max_width}: "
            f"{type(e).__name__}: {e}"
        )

    # Invariant 1: result_in_range
    assert 0 <= r <= len(s), (
        f"result_in_range violated: r={r}, len={len(s)}, max_width={max_width}, s={s!r}"
    )

    # Invariant 2: fits_within_budget
    used = prefix_width(s, r)
    assert used <= max_width, (
        f"fits_within_budget violated: prefix_width({r} chars)={used} > max_width={max_width}, "
        f"s={s!r}"
    )

    # Invariant 3: greedy_maximality — next char (if any) would exceed budget
    if r < len(s):
        next_used = prefix_width(s, r + 1)
        assert next_used > max_width, (
            f"greedy_maximality violated: prefix_width({r+1} chars)={next_used} "
            f"<= max_width={max_width}, but function returned r={r}; s={s!r}"
        )


# ---------------------------------------------------------------------------
# Config grid from env (VERIFY_STRESS_GRID) or ANALYSIS fallback
# ---------------------------------------------------------------------------

def get_max_width_values():
    raw = os.environ.get("VERIFY_STRESS_GRID", "")
    if raw:
        try:
            grid = json.loads(raw)
            if "max_width" in grid:
                return list(grid["max_width"])
        except (json.JSONDecodeError, KeyError):
            pass
    # ANALYSIS.stress_params fallback
    return [0, 1, 2, 88, 10000]


# ---------------------------------------------------------------------------
# Seed inputs — crafted to probe the PR's exact change
# ---------------------------------------------------------------------------

# Boundary-probing seeds derived from PR diff context
SEEDS = [
    "",                       # empty
    "a",                      # single ASCII, width=1
    "ab",                     # two ASCII, width=2
    "\u4e2d",                 # single CJK, width=2
    "\u4e2d\u6587",           # two CJK, width=4
    "a\u4e2d",                # mixed: ASCII+CJK, widths 1+2=3
    "a\u4e2db",               # mixed: ASCII+CJK+ASCII, widths 1+2+1=4
    "hello world",            # plain ASCII phrase
    "x" * 88,                 # exactly Black's default line length
    "x" * 89,                 # one over
    "\u4e2d" * 44,            # 44 CJK = width 88
    "\u4e2d" * 45,            # 45 CJK = width 90 (over default)
    "a" * 5 + "\u4e2d" * 3,  # mixed tail
    "\u4e2d" + "a" * 5,      # wide char at start
]

ASCII_CHARS = "abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
CJK_CHARS = ["\u4e2d", "\u6587", "\u65e5", "\u672c", "\u8bed"]
WIDE_CHARS = CJK_CHARS


def generate_inputs(rng: random.Random, n: int = 200):
    """Yield n mutated inputs derived from seeds."""
    inputs = list(SEEDS)

    while len(inputs) < n:
        base = rng.choice(SEEDS)
        op = rng.randint(0, 5)

        if op == 0:
            # Extend with random ASCII
            extra = "".join(rng.choices(ASCII_CHARS, k=rng.randint(1, 20)))
            inputs.append(base + extra)
        elif op == 1:
            # Extend with CJK
            extra = "".join(rng.choices(CJK_CHARS, k=rng.randint(1, 10)))
            inputs.append(base + extra)
        elif op == 2:
            # Prepend CJK
            extra = "".join(rng.choices(CJK_CHARS, k=rng.randint(1, 5)))
            inputs.append(extra + base)
        elif op == 3:
            # Interleave ASCII and CJK
            parts = []
            for _ in range(rng.randint(1, 8)):
                if rng.random() < 0.5:
                    parts.append(rng.choice(ASCII_CHARS))
                else:
                    parts.append(rng.choice(CJK_CHARS))
            inputs.append("".join(parts))
        elif op == 4:
            # Repeat a seed
            k = rng.randint(1, 5)
            inputs.append(base * k)
        else:
            # Random length ASCII
            inputs.append("".join(rng.choices(ASCII_CHARS, k=rng.randint(0, 50))))

    return inputs[:n]


# ---------------------------------------------------------------------------
# The fuzz test
# ---------------------------------------------------------------------------

def test_seeded_fuzz_invariants():
    """
    Fuzz test: for ~200 inputs × all max_width values, assert all four
    invariants. Fixed seed 1234 ensures reproducibility.

    Also checks monotone_in_width across the full grid for each input.
    """
    rng = random.Random(1234)
    max_width_values = get_max_width_values()
    inputs = generate_inputs(rng, n=200)

    total_checks = 0
    for s in inputs:
        prev_r = None
        prev_w = None

        for max_width in sorted(max_width_values):
            assert_invariants(s, max_width)
            total_checks += 1

            # Invariant 4: monotone_in_width
            r = count_chars_in_width(s, max_width)
            if prev_r is not None:
                assert r >= prev_r, (
                    f"monotone_in_width violated: r({s!r},{max_width})={r} < "
                    f"r({s!r},{prev_w})={prev_r}"
                )
            prev_r = r
            prev_w = max_width

    # Sanity: confirm the test actually ran meaningful iterations
    assert total_checks >= 100, f"Too few checks: {total_checks}"


def test_positional_diversity():
    """
    Boundary-triggering string placed in various positions within a larger
    context string. Verifies invariants for each placement.
    """
    rng = random.Random(9999)
    max_width_values = get_max_width_values()

    # Boundary string: single CJK of width 2
    boundary = "\u4e2d"
    contexts = [
        boundary,                              # isolated
        "a" + boundary,                        # before
        boundary + "a",                        # after
        "a" + boundary + "b",                  # between
        "\n".join(["x"] * 3 + [boundary]),     # after newlines (treated as chars)
        boundary * 3 + "abc",                  # repeated then ASCII
        "abc" + boundary * 2,                  # ASCII then repeated CJK
    ]

    for s in contexts:
        for max_width in max_width_values:
            assert_invariants(s, max_width)
