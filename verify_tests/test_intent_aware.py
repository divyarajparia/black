"""
Intent-aware regression tests for the PR changing normalize_string_quotes.

The PR changes the guard condition from checking new_body[-1:] (original, correct)
to checking new_body[-2:] (PR head, incorrect).

Impact: the original guard prevented a four-consecutive-double-quote sequence
that makes the output unparseable. The PR's condition never fires for the real
edge case (trailing bare dq), so converting triple-single to triple-double with
a trailing bare dq produces broken output.

These tests MUST:
  - FAIL on verify_pr  (the PR head introduces the broken guard)
  - PASS on verify_base (original guard is correct)
"""
import ast
import pytest
import black
from black import InvalidInput


def fmt(src: str) -> str:
    return black.format_str(src, mode=black.Mode())


def assert_valid_python(code: str, context: str = "") -> None:
    try:
        ast.parse(code)
    except SyntaxError as e:
        msg = f"Output is not valid Python: {e!r}"
        if context:
            msg += f"\nContext: {context}"
        msg += f"\nOutput: {code!r}"
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Intent-aware: trailing bare-dq guard must produce parseable output
# ---------------------------------------------------------------------------

def test_intent_triple_single_trailing_bare_dq_output_is_valid_python():
    """
    Formatting a triple-single-quoted string whose body ends with a bare double-quote
    must produce syntactically valid Python output.

    On verify_pr: the guard is broken (checks -2 slice for backslash+dq instead of
    -1 slice for bare dq), so the formatter emits triple-double-quote with body
    ending in a bare dq, forming a four-dq sequence that is INVALID — black's
    own lib2to3 parser raises InvalidInput or the output is malformed.

    On verify_base: the guard fires correctly, output stays as triple-single (valid).
    """
    # triple-single with body = 'x"' (trailing bare double-quote)
    src = "x = '''x\"'''\n"
    # On verify_pr this raises InvalidInput (black crashes on its own broken output).
    # On verify_base it succeeds and produces valid Python.
    try:
        out = fmt(src)
    except InvalidInput as e:
        pytest.fail(
            f"black raised InvalidInput on its OWN formatted output: {e}\n"
            f"This is the regression introduced by the PR's broken guard."
        )
    assert_valid_python(out, context=f"src={src!r}")


def test_intent_triple_single_only_dq_body_output_is_valid_python():
    """
    Triple-single-quoted string whose entire body is a single bare double-quote
    must produce valid Python output (not raise InvalidInput or emit malformed text).

    On verify_pr: raises InvalidInput because the formatter tries to emit
    triple-double-quoted with a bare dq body, which is malformed.
    On verify_base: stays triple-single, fully valid.
    """
    src = "x = '''\"'''\n"
    try:
        out = fmt(src)
    except InvalidInput as e:
        pytest.fail(
            f"black raised InvalidInput on its OWN output (body=single dq): {e}\n"
            f"Regression from PR's broken trailing-dq guard."
        )
    assert_valid_python(out, context=f"src={src!r}")


def test_intent_triple_single_trailing_bare_dq_value_preserved():
    """
    The string VALUE after formatting a triple-single with trailing bare dq
    must equal the original value.

    x = '''x\"'''  evaluates to  'x"'
    The formatted output must also evaluate to 'x"'.

    On verify_base: correct (stays triple-single, value preserved).
    On verify_pr: crashes before we can even check the value.
    """
    src = "x = '''x\"'''\n"
    try:
        out = fmt(src)
    except InvalidInput as e:
        pytest.fail(f"black raised InvalidInput: {e}")
    assert_valid_python(out)
    ns: dict = {}
    exec(compile(out, "<string>", "exec"), ns)
    assert ns["x"] == 'x"', (
        f"Value changed after formatting: expected 'x\"', got {ns['x']!r}\n"
        f"Formatted output was: {out!r}"
    )


def test_intent_triple_single_only_dq_value_preserved():
    """
    Triple-single body = bare double-quote char. After formatting, value must
    still be a single double-quote.

    On verify_base: stays triple-single, value is '"'. Valid.
    On verify_pr: crashes — InvalidInput from black's own broken output.
    """
    src = "x = '''\"'''\n"
    try:
        out = fmt(src)
    except InvalidInput as e:
        pytest.fail(f"black raised InvalidInput: {e}")
    assert_valid_python(out)
    ns: dict = {}
    exec(compile(out, "<string>", "exec"), ns)
    assert ns["x"] == '"', (
        f"Value changed: expected '\"', got {ns['x']!r}\nOutput was: {out!r}"
    )
