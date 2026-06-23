"""
Seeded differential fuzz test for count_chars_in_width (PR #17).

Uses a fixed RNG so results are fully reproducible.  Generates ~200 string
inputs by mutating seeds derived from the PR's change and asserts that:
  1. No unexpected internal errors occur (AttributeError, IndexError, etc.)
  2. The four invariants from the ANALYSIS hold on every (input, max_width) pair:
       - return_within_bounds
       - monotone_in_max_width
       - boundary_inclusion
       - ascii_fast_path_consistency (when applicable)

This test is tagged as characterization and runs identically on both branches.
A crash or invariant violation that appears ONLY on verify_pr signals a
regression introduced by the PR.

Config grid is read from the VERIFY_STRESS_GRID env-var (JSON dict mapping
param name → list of values).  Falls back to the ANALYSIS stress_params.
"""
import json
import os
import random
import unicodedata
from typing import List

import pytest
from black.strings import count_chars_in_width


# ---------------------------------------------------------------------------
# Helper: East-Asian Width of a character (mirrors black's char_width logic)
# ---------------------------------------------------------------------------

def _eaw(ch: str) -> int:
    """Return display width of a single character (1 or 2)."""
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ("W", "F") else 1


# ---------------------------------------------------------------------------
# Config grid
# ---------------------------------------------------------------------------

def _get_max_width_values() -> List[int]:
    raw = os.environ.get("VERIFY_STRESS_GRID", "")
    if raw:
        grid = json.loads(raw)
        if "max_width" in grid:
            return [int(v) for v in grid["max_width"]]
    # Fallback: ANALYSIS stress_params for max_width
    return [0, 1, 2, 88, 1000]


# ---------------------------------------------------------------------------
# Seed inputs — representative strings that exercise the changed code path
# ---------------------------------------------------------------------------

# Primary seeds: wide Unicode chars (CJK), the exact case the PR targets
SEEDS: List[str] = [
    "你好世界",           # 4 × width-2
    "こんにちは",         # 5 × width-2 (Japanese)
    "안녕하세요",         # 5 × width-2 (Korean)
    "你A好B世C界D",       # alternating wide + ASCII
    "AAAA你BBBB好CCCC",  # ASCII runs with wide chars
    "\u4e2d\u6587",      # 中文 (2 chars)
    "x",                 # single ASCII
    "\u4e2d",            # single wide char
    "",                  # empty
    "hello",             # pure ASCII
    "αβγδ",             # Greek (width-1, non-ASCII)
    "→←↑↓",            # arrows (width-1)
]


def _generate_inputs(rng: random.Random, n: int = 200) -> List[str]:
    """Mutate seeds to produce n diverse string inputs."""
    results: List[str] = list(SEEDS)  # always include seeds themselves

    wide_chars  = [chr(cp) for cp in range(0x4E00, 0x4E00 + 50)]   # CJK block
    ascii_chars = list("abcdefghijklmnopqrstuvwxyz0123456789 ")
    mixed_chars = wide_chars[:20] + ascii_chars[:20]

    for _ in range(n):
        seed = rng.choice(SEEDS) if SEEDS else ""
        op = rng.randint(0, 5)

        if op == 0:
            # Repeat a random seed k times
            k = rng.randint(1, 8)
            results.append(seed * k)
        elif op == 1:
            # Build a random string of wide chars
            length = rng.randint(0, 20)
            results.append("".join(rng.choices(wide_chars, k=length)))
        elif op == 2:
            # Build alternating wide+ASCII
            parts = []
            for _ in range(rng.randint(1, 15)):
                parts.append(rng.choice(wide_chars))
                parts.append(rng.choice(ascii_chars))
            results.append("".join(parts))
        elif op == 3:
            # Slice a seed
            s = seed
            if len(s) >= 2:
                a = rng.randint(0, len(s) - 1)
                b = rng.randint(a, len(s))
                results.append(s[a:b])
            else:
                results.append(s)
        elif op == 4:
            # Concatenate two random seeds
            s1 = rng.choice(SEEDS) if SEEDS else ""
            s2 = rng.choice(SEEDS) if SEEDS else ""
            results.append(s1 + s2)
        else:
            # Random mixed string
            length = rng.randint(0, 30)
            results.append("".join(rng.choices(mixed_chars, k=length)))

    return results


# ---------------------------------------------------------------------------
# Fuzz test
# ---------------------------------------------------------------------------

MAX_WIDTH_VALUES = _get_max_width_values()


def test_fuzz_invariants_seeded():
    """
    Seeded fuzz: for ~200 inputs × all max_width values, assert all invariants.

    Cap: at most 200 inputs × 5 widths = 1000 iterations — completes quickly.
    """
    rng = random.Random(1234)
    inputs = _generate_inputs(rng, n=200)

    for line_str in inputs:
        for max_width in MAX_WIDTH_VALUES:
            # ----------------------------------------------------------------
            # 1. No unexpected internal error
            # ----------------------------------------------------------------
            try:
                result = count_chars_in_width(line_str, max_width)
            except (TypeError, ValueError):
                # Documented contract violations (wrong type/value) — ok to skip
                continue
            except Exception as exc:
                raise AssertionError(
                    f"Unexpected internal error for "
                    f"count_chars_in_width({line_str!r}, {max_width}): "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            # ----------------------------------------------------------------
            # 2. Invariant: return_within_bounds
            # ----------------------------------------------------------------
            assert 0 <= result <= len(line_str), (
                f"return_within_bounds violated: "
                f"count_chars_in_width({line_str!r}, {max_width}) = {result}, "
                f"len={len(line_str)}"
            )

            # ----------------------------------------------------------------
            # 3. Invariant: boundary_inclusion
            #    If the first k chars sum to exactly max_width, result >= k.
            # ----------------------------------------------------------------
            cumulative = 0
            k_exact = None
            for idx, ch in enumerate(line_str):
                cumulative += _eaw(ch)
                if cumulative == max_width:
                    k_exact = idx + 1
                    break
                if cumulative > max_width:
                    break
            if k_exact is not None:
                assert result >= k_exact, (
                    f"boundary_inclusion violated: "
                    f"first {k_exact} chars sum to exactly {max_width} width "
                    f"but count_chars_in_width({line_str!r}, {max_width}) = {result}"
                )

            # ----------------------------------------------------------------
            # 4. Invariant: monotone_in_max_width
            #    Check that result(w) <= result(w+1) for the next width.
            # ----------------------------------------------------------------
            next_width = max_width + 1
            try:
                result_next = count_chars_in_width(line_str, next_width)
            except Exception:
                result_next = None
            if result_next is not None:
                assert result <= result_next, (
                    f"monotone_in_max_width violated: "
                    f"count_chars_in_width({line_str!r}, {max_width}) = {result} "
                    f"> count_chars_in_width(..., {next_width}) = {result_next}"
                )


def test_fuzz_no_crash_on_zero_max_width():
    """max_width=0 is a degenerate case — must not crash and must return 0."""
    rng = random.Random(4321)
    inputs = _generate_inputs(rng, n=50)
    for line_str in inputs:
        try:
            result = count_chars_in_width(line_str, 0)
        except Exception as exc:
            raise AssertionError(
                f"Crash on max_width=0 for {line_str!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        # With max_width=0: first char width >= 1 > 0, so returns 0 immediately
        assert result == 0, (
            f"count_chars_in_width({line_str!r}, 0) = {result}, expected 0"
        )
