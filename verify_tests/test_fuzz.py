"""
Seeded differential fuzz / stability test for normalize_string_quotes.

Tests the invariants defined in the ANALYSIS across a large set of generated
inputs. Runs identically on verify_base and verify_pr — any invariant that
holds on base but fails on the PR head surfaces as a regression.

Seeds are crafted around the exact edge case the PR modifies:
  triple-single-quoted strings whose body ends with one or two bare double-quotes.

Invariants checked per (input, config):
  - output_reparseable: output is valid Python
  - no_content_dropped: string value unchanged
  - idempotent: fmt(fmt(x)) == fmt(x)
  - triple_double_quote_body_safe: if output uses \"\"\", body must not end
    with bare double-quote (prevents \"\"\"\"\"\"\" = malformed)
"""
from __future__ import annotations
import ast
import json
import os
import random
import itertools
from typing import Any
import pytest
import black
from black import InvalidInput, NothingChanged

# ---------------------------------------------------------------------------
# Config grid (from environment or ANALYSIS stress_params fallback)
# ---------------------------------------------------------------------------

_DEFAULT_GRID: dict[str, list[Any]] = {
    "string_prefix": ["", "r", "R", "b", "B", "rb", "bR"],
    # We don't use new_quote / input_string_trailing_quote as Mode params;
    # those are embedded in the input strings themselves.
    # We vary line_length to stress the formatter's layout decisions.
    "line_length": [88, 79, 40],
    "magic_trailing_comma": [True, False],
}

_ENV_GRID = json.loads(os.environ.get("VERIFY_STRESS_GRID", "{}"))
_GRID = _ENV_GRID if _ENV_GRID else _DEFAULT_GRID


def _all_configs() -> list[dict[str, Any]]:
    keys = sorted(_GRID.keys())
    combos = list(itertools.product(*[_GRID[k] for k in keys]))
    return [dict(zip(keys, combo)) for combo in combos]


def _make_mode(cfg: dict[str, Any]) -> black.Mode:
    kwargs: dict[str, Any] = {}
    if "line_length" in cfg:
        kwargs["line_length"] = int(cfg["line_length"])
    if "magic_trailing_comma" in cfg:
        kwargs["magic_trailing_comma"] = bool(cfg["magic_trailing_comma"])
    return black.Mode(**kwargs)


# ---------------------------------------------------------------------------
# Seed inputs: directly targeting the changed guard
# ---------------------------------------------------------------------------

def _make_seeds() -> list[str]:
    """Return a list of triple-single-quoted source strings that exercise the guard."""
    seeds = []

    # Primary seeds: bodies ending with bare double-quote(s)
    base_bodies = [
        '"',           # just a dq
        'x"',          # trailing bare dq
        '"x',          # leading bare dq
        'x"y',         # dq in middle
        '""',          # two bare dqs
        'x""',         # two trailing bare dqs
        'x"""',        # three bare dqs
        'abc"def"',    # multiple non-trailing
        'foo "bar"',   # quoted word
        'hello\\"',    # escaped dq at end (backslash before dq)
        'abc\\"def',   # escaped dq in middle
        '',            # empty body
        'no_special',  # control: no dq at all
        'a b c',
        'line1\nline2',
        'line1\nline2"',   # multiline ending in dq
        'line1\n"',        # multiline ending in bare dq
        '"line1\nline2',   # multiline starting in dq
        'x' * 80 + '"',    # long body ending in dq
        '"' * 5,           # five consecutive dqs
    ]

    for body in base_bodies:
        # triple-single-quote
        seeds.append(f"x = '''{body}'''\n")

    return seeds


# ---------------------------------------------------------------------------
# Mutator: vary the seed structurally
# ---------------------------------------------------------------------------

def _mutate(rng: random.Random, seed: str, idx: int) -> str | None:
    """Apply a deterministic structural mutation. Returns None if result would
    be syntactically invalid (we skip those)."""
    mutations = [
        # Wrap in assignment with different variable names
        lambda s: s.replace("x = ", f"var_{idx} = "),
        # Add a comment before
        lambda s: f"# comment {idx}\n" + s,
        # Add a trailing statement
        lambda s: s + f"y_{idx} = 1\n",
        # Add the string in a function body
        lambda s: f"def f_{idx}():\n    " + s.replace("\n", "\n    ").rstrip() + "\n",
        # Put the string in a list
        lambda s: f"lst_{idx} = [" + s.strip() + "]\n",
        # Keep as-is
        lambda s: s,
        # Duplicate body character at end
        lambda s: _extend_body(s),
    ]
    fn = mutations[idx % len(mutations)]
    try:
        result = fn(seed)
        ast.parse(result)  # Verify the mutated input is valid Python
        return result
    except (SyntaxError, Exception):
        return None  # Skip invalid mutations


def _extend_body(src: str) -> str:
    """Try to extend the body of the first string literal found."""
    try:
        import tokenize, io
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        for tok in tokens:
            if tok.type == tokenize.STRING:
                val = tok.string
                if val.startswith("'''"):
                    body = val[3:-3]
                    new_body = body + "a"
                    return src.replace(val, f"'''{new_body}'''", 1)
    except Exception:
        pass
    return src


# ---------------------------------------------------------------------------
# Invariant checkers
# ---------------------------------------------------------------------------

def _check_output_reparseable(out: str, ctx: str) -> None:
    try:
        ast.parse(out)
    except SyntaxError as e:
        pytest.fail(f"[output_reparseable] {ctx}\nOutput not valid Python: {e}\n{out!r}")


def _check_no_content_dropped(src: str, out: str, ctx: str) -> None:
    """The string value must not change. Only check simple single-statement cases."""
    try:
        src_ns: dict = {}
        out_ns: dict = {}
        exec(compile(src, "<src>", "exec"), src_ns)
        exec(compile(out, "<out>", "exec"), out_ns)
        # Find string values
        src_strs = [v for v in src_ns.values() if isinstance(v, str)]
        out_strs = [v for v in out_ns.values() if isinstance(v, str)]
        if src_strs and out_strs:
            if sorted(src_strs) != sorted(out_strs):
                pytest.fail(
                    f"[no_content_dropped] {ctx}\n"
                    f"  src values: {src_strs}\n"
                    f"  out values: {out_strs}"
                )
    except Exception:
        # Complex inputs (functions, lists) — skip value check
        pass


def _check_idempotent(out: str, cfg: dict, ctx: str) -> None:
    mode = _make_mode(cfg)
    try:
        out2 = black.format_str(out, mode=mode)
    except (InvalidInput, NothingChanged):
        return  # acceptable
    except Exception as e:
        # Unexpected error on second pass = regression
        if type(e).__name__ not in ("InvalidInput", "NothingChanged", "CannotTransform"):
            pytest.fail(f"[idempotent] unexpected error on second pass: {e!r}\n{ctx}")
        return
    if out2 != out:
        pytest.fail(
            f"[idempotent] not idempotent {ctx}\n"
            f"  first:  {out!r}\n"
            f"  second: {out2!r}"
        )


def _check_triple_double_body_safe(out: str, ctx: str) -> None:
    """If output uses triple-double-quote, body must not end with bare dq."""
    import tokenize, io
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(out).readline))
    except tokenize.TokenError:
        return  # already caught by reparseable check
    for tok in tokens:
        if tok.type == tokenize.STRING:
            val = tok.string
            if val.startswith('"""') and val.endswith('"""') and len(val) >= 6:
                body = val[3:-3]
                if body.endswith('"') and not body.endswith('\\"'):
                    pytest.fail(
                        f"[triple_double_quote_body_safe] {ctx}\n"
                        f"  triple-double body ends with bare dq: {val!r}"
                    )


_UNEXPECTED_ERRORS = (
    AttributeError, IndexError, KeyError, RecursionError, AssertionError,
    TypeError, ValueError, OverflowError,
)


# ---------------------------------------------------------------------------
# The fuzz test
# ---------------------------------------------------------------------------

def test_fuzz_normalize_string_quotes_stability():
    """
    Seeded fuzz: generate ~150 inputs by mutating seeds, run across config grid,
    assert all invariants hold. Fixed seed = fully reproducible.
    """
    rng = random.Random(1234)
    seeds = _make_seeds()
    configs = _all_configs()

    # Generate inputs by mutating seeds
    inputs: list[str] = []
    for i, seed in enumerate(seeds):
        inputs.append(seed)  # always include raw seed
        for j in range(6):   # 6 mutations per seed
            mut = _mutate(rng, seed, i * 10 + j)
            if mut is not None:
                inputs.append(mut)

    # Shuffle for diversity, cap at 200 for time budget
    rng.shuffle(inputs)
    inputs = inputs[:200]

    failures: list[str] = []
    total = 0
    skipped = 0

    for src in inputs:
        # Verify input is parseable (defensive)
        try:
            ast.parse(src)
        except SyntaxError:
            skipped += 1
            continue

        for cfg in configs:
            mode = _make_mode(cfg)
            ctx = f"src={src!r} cfg={cfg}"
            total += 1

            try:
                out = black.format_str(src, mode=mode)
            except InvalidInput:
                # Documented contract: black refuses invalid input — acceptable
                continue
            except NothingChanged:
                continue
            except _UNEXPECTED_ERRORS as e:
                failures.append(f"UNEXPECTED_ERROR: {type(e).__name__}: {e}\n  {ctx}")
                continue
            except Exception as e:
                # Other black-internal errors (CannotTransform, etc.) may be acceptable
                # but an internal crash is not
                ename = type(e).__name__
                if "Internal" in ename or "Assert" in ename:
                    failures.append(f"INTERNAL_ERROR: {ename}: {e}\n  {ctx}")
                # black.InvalidInput / parsing errors: acceptable
                continue

            # --- invariant checks ---
            try:
                _check_output_reparseable(out, ctx)
            except Exception as e:
                failures.append(str(e))
                continue

            try:
                _check_triple_double_body_safe(out, ctx)
            except Exception as e:
                failures.append(str(e))

            try:
                _check_no_content_dropped(src, out, ctx)
            except Exception as e:
                failures.append(str(e))

            try:
                _check_idempotent(out, cfg, ctx)
            except Exception as e:
                failures.append(str(e))

    if failures:
        summary = f"{len(failures)} invariant failure(s) out of {total} cases:\n"
        summary += "\n\n".join(failures[:10])  # show first 10
        pytest.fail(summary)

    assert total > 0, f"No test cases ran (skipped={skipped})"


