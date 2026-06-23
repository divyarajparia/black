"""
Seeded differential fuzz / stability test for count_chars_in_width.

Runs on BOTH verify_base and verify_pr.  A crash or invariant violation
that appears only on the PR head is reported as a regression by the runner.

Seeds are drawn from the boundary-focused patterns the PR specifically
targets (exact-width matches, fullwidth chars, mixed ASCII+fullwidth).
The grid of (max_width) values is read from VERIFY_STRESS_GRID env var
so the external runner can mandate extremes; falls back to ANALYSIS
stress_params if the env var is absent.
"""

import itertools
import json
import os
import random
import unicodedata

import pytest
from black.strings import count_chars_in_width


# ── Helper ───────────────────────────────────────────────────────────────────

def _char_display_width(ch: str) -> int:
    """Return East-Asian display width (1 or 2) for a single character."""
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ("W", "F") else 1


def _string_display_width(s: str) -> int:
    return sum(_char_display_width(c) for c in s)


# ── Config grid (from env or ANALYSIS defaults) ──────────────────────────────

_env_grid = os.environ.get("VERIFY_STRESS_GRID", "")
if _env_grid:
    _grid = json.loads(_env_grid)
else:
    _grid = {}

MAX_WIDTH_VALUES: list = _grid.get("max_width", [0, 1, 2, 88, 10000])

# ── Seed inputs ───────────────────────────────────────────────────────────────

# Primary seeds: inputs that reach the exact-boundary path (PR's target)
_ASCII_SEEDS = [
    "",
    "a",
    "ab",
    "hello",
    "x" * 88,
    "hello world this is a longer string for testing purposes",
]

_FULLWIDTH_SEEDS = [
    "\u4e2d",          # 中 (width=2)
    "\u4e2d\u6587",    # 中文 (two fullwidth)
    "a\u4e2d",         # ASCII + fullwidth
    "\u4e2da",         # fullwidth + ASCII
    "\u4e2d" * 44,     # 44 fullwidth = width 88
]

_BASE_SEEDS = _ASCII_SEEDS + _FULLWIDTH_SEEDS


def _generate_inputs(rng: random.Random, n: int = 200) -> list:
    """
    Generate ~n valid string inputs by mutating _BASE_SEEDS.
    All characters are printable with known widths; no random bytes.
    """
    ascii_chars = [chr(c) for c in range(0x20, 0x7F)]  # printable ASCII
    fw_chars = ["\u4e2d", "\u6587", "\u65e5", "\u672c", "\u8bed", "\u5b66"]

    inputs = list(_BASE_SEEDS)  # start with seeds

    while len(inputs) < n:
        choice = rng.randint(0, 5)

        if choice == 0:
            # Random ASCII string of random length
            length = rng.randint(0, 30)
            inputs.append("".join(rng.choices(ascii_chars, k=length)))

        elif choice == 1:
            # Random fullwidth-only string
            length = rng.randint(0, 15)
            inputs.append("".join(rng.choices(fw_chars, k=length)))

        elif choice == 2:
            # Mixed: some ASCII then some fullwidth
            a_len = rng.randint(0, 15)
            f_len = rng.randint(0, 8)
            s = "".join(rng.choices(ascii_chars, k=a_len))
            s += "".join(rng.choices(fw_chars, k=f_len))
            inputs.append(s)

        elif choice == 3:
            # String whose total width is EXACTLY a random max_width (boundary)
            target_w = rng.choice(MAX_WIDTH_VALUES) if MAX_WIDTH_VALUES else rng.randint(1, 20)
            if target_w == 0:
                inputs.append("")
                continue
            s = ""
            remaining = target_w
            while remaining > 0:
                if remaining >= 2 and rng.random() < 0.4:
                    s += rng.choice(fw_chars)
                    remaining -= 2
                else:
                    s += rng.choice(ascii_chars)
                    remaining -= 1
            inputs.append(s)

        elif choice == 4:
            # Mutate an existing seed: insert/append chars
            base = rng.choice(_BASE_SEEDS) if _BASE_SEEDS else ""
            extra_a = rng.randint(0, 5)
            extra_f = rng.randint(0, 3)
            s = base + "".join(rng.choices(ascii_chars, k=extra_a))
            s += "".join(rng.choices(fw_chars, k=extra_f))
            inputs.append(s)

        else:
            # Place the target construct in different positions
            ctx_pre = "".join(rng.choices(ascii_chars, k=rng.randint(0, 10)))
            fw_mid = "".join(rng.choices(fw_chars, k=rng.randint(0, 5)))
            ctx_post = "".join(rng.choices(ascii_chars, k=rng.randint(0, 10)))
            inputs.append(ctx_pre + fw_mid + ctx_post)

    return inputs[:n]


# ── Invariant checkers ────────────────────────────────────────────────────────

def _check_return_le_len(s: str, w: int, result: int) -> None:
    """result must be in [0, len(s)]."""
    assert 0 <= result <= len(s), (
        f"return_le_len violated: count_chars_in_width({s!r}, {w}) = {result}, "
        f"len(s)={len(s)}"
    )


def _check_prefix_fits_in_width(s: str, w: int, result: int) -> None:
    """string_width(s[:result]) <= max_width."""
    prefix_width = _string_display_width(s[:result])
    assert prefix_width <= w, (
        f"prefix_fits_in_width violated: "
        f"count_chars_in_width({s!r}, {w}) = {result}, "
        f"but s[:{result}]={s[:result]!r} has display_width={prefix_width} > {w}"
    )


def _check_one_more_exceeds(s: str, w: int, result: int) -> None:
    """If result < len(s), then string_width(s[:result+1]) > max_width."""
    if result < len(s):
        next_width = _string_display_width(s[:result + 1])
        assert next_width > w, (
            f"one_more_char_exceeds_width violated: "
            f"count_chars_in_width({s!r}, {w}) = {result}, "
            f"but s[:{result+1}]={s[:result+1]!r} has display_width={next_width} <= {w}"
        )


def _check_ascii_fast_path(s: str, w: int, result: int) -> None:
    """For pure-ASCII input, result must equal the naive char-by-char sum."""
    if not all(ord(c) < 0x80 for c in s):
        return
    naive = 0
    for i, c in enumerate(s):
        if naive + 1 > w:
            assert result == i, (
                f"ascii_fast_path_consistency violated at max_width={w}: "
                f"naive logic says return {i}, got {result}"
            )
            return
        naive += 1
    assert result == len(s), (
        f"ascii_fast_path_consistency violated: naive says all {len(s)} chars fit "
        f"in max_width={w}, got {result}"
    )


# ── Main fuzz test ────────────────────────────────────────────────────────────

_UNEXPECTED_ERRORS = (
    AttributeError, IndexError, KeyError, RecursionError, AssertionError,
    TypeError, ValueError,  # ValueError can be intentional; keep for safety
)

MAX_ITERS = 300  # cap so the test finishes quickly


def test_fuzz_invariants_across_stress_grid():
    """
    Seeded fuzz: generate ~200 inputs, cross-product with all max_width values
    from VERIFY_STRESS_GRID (or ANALYSIS defaults).  For each (input, max_width)
    assert all four invariants hold.  Any unexpected exception is a failure.
    Runs identically on verify_base and verify_pr — the runner diffs the verdicts.
    """
    rng = random.Random(1234)
    inputs = _generate_inputs(rng, n=200)

    combos = list(itertools.product(inputs, MAX_WIDTH_VALUES))
    rng.shuffle(combos)
    combos = combos[:MAX_ITERS]

    failures = []
    for s, w in combos:
        try:
            result = count_chars_in_width(s, w)
        except Exception as exc:
            if not isinstance(exc, _UNEXPECTED_ERRORS):
                raise
            failures.append(
                f"Unexpected internal error for ({s!r}, {w}): {type(exc).__name__}: {exc}"
            )
            continue

        try:
            _check_return_le_len(s, w, result)
            _check_prefix_fits_in_width(s, w, result)
            _check_one_more_exceeds(s, w, result)
            _check_ascii_fast_path(s, w, result)
        except AssertionError as ae:
            failures.append(str(ae))

    if failures:
        summary = "\n".join(failures[:10])
        if len(failures) > 10:
            summary += f"\n... and {len(failures) - 10} more"
        pytest.fail(f"{len(failures)} invariant violations:\n{summary}")
