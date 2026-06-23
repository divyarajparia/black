"""
Characterization tests for normalize_string_quotes in src/black/strings.py.
Golden outputs captured on verify_base (commit b74b2301).

These test behaviors the PR should NOT change. A regression means the PR
broke something it shouldn't have touched.
"""
import ast
import pytest
import black


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt(src: str) -> str:
    return black.format_str(src, mode=black.Mode())


def assert_valid_python(src: str) -> None:
    try:
        ast.parse(src)
    except SyntaxError as e:
        pytest.fail(f"Output is not valid Python: {e!r}\nOutput was: {src!r}")


# ---------------------------------------------------------------------------
# Characterization: behaviors that must be identical on base and PR head
# ---------------------------------------------------------------------------

def test_char_plain_single_to_double():
    """Single-quoted string without any double-quotes converts to double-quoted."""
    src = "x = 'hello'\n"
    out = fmt(src)
    assert out == 'x = "hello"\n', f"Unexpected: {out!r}"
    assert_valid_python(out)


def test_char_triple_single_no_double_quote_converts_to_triple_double():
    """Triple-single-quoted string with no double-quotes converts to triple-double."""
    src = "x = '''hello world'''\n"
    out = fmt(src)
    assert out == 'x = """hello world"""\n', f"Unexpected: {out!r}"
    assert_valid_python(out)


def test_char_triple_single_double_quote_in_middle_converts():
    """Triple-single-quoted string with a bare double-quote in the MIDDLE converts."""
    # Body = 'a"b' — bare dq not at end — guard should not fire
    src = "x = '''a\"b'''\n"
    out = fmt(src)
    assert out == 'x = """a"b"""\n', f"Unexpected: {out!r}"
    assert_valid_python(out)


def test_char_triple_single_trailing_bare_dq_stays_triple_single():
    """
    CRITICAL: Triple-single-quoted string whose body ends with a bare double-quote
    must stay as triple-single-quote on the base (original guard fires).
    The guard prevents '\"\"\"x\"\"\"\"' which is malformed.
    Golden captured on verify_base.
    """
    src = "x = '''x\"'''\n"
    out = fmt(src)
    # On verify_base the guard fires: output stays triple-single-quote
    assert out == "x = '''x\"'''\n", f"Unexpected: {out!r}"
    assert_valid_python(out)


def test_char_triple_single_just_dq_stays_triple_single():
    """Triple-single body = single bare double-quote stays as triple-single on base."""
    src = "x = '''\"'''\n"
    out = fmt(src)
    assert out == "x = '''\"'''\n", f"Unexpected: {out!r}"
    assert_valid_python(out)


def test_char_triple_single_escaped_dq_at_end_stays_triple_single():
    """
    Triple-single whose body ends with a backslash-escaped double-quote stays
    triple-single (more escapes introduced would prevent conversion anyway).
    Golden captured on verify_base.
    """
    src = "x = '''abc\\\"'''\n"
    out = fmt(src)
    assert out == "x = '''abc\\\"'''\n", f"Unexpected: {out!r}"
    assert_valid_python(out)


def test_char_already_triple_double_unchanged():
    """Already-triple-double-quoted strings are returned unchanged."""
    src = 'x = """already double"""\n'
    out = fmt(src)
    assert out == src, f"Unexpected: {out!r}"
    assert_valid_python(out)


def test_char_output_always_valid_python_basic():
    """A range of basic string literals always produce valid Python output."""
    cases = [
        "x = 'simple'\n",
        "x = \"already double\"\n",
        "x = '''triple single'''\n",
        'x = """triple double"""\n',
        "x = 'with \\'escaped\\' single'\n",
        "x = 'no special chars'\n",
    ]
    for src in cases:
        out = fmt(src)
        assert_valid_python(out)
