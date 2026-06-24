"""
CHARACTERIZATION tests for PR #34.

These verify behaviour the PR must NOT change: formatting outputs for inputs
that don't exercise the first-child edge case.  Goldens were captured on
verify_base (f806c8f8223160e1b3def1a75c587ec746dbe365) where the unrelated
paths were already correct.

Also tests the sibling_map_consistency invariant: for every child in a Node
the maps accurately reflect its left and right neighbours after mutation via
the non-first positions.
"""

import pytest
import black
from blib2to3.pytree import Node, Leaf

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOKEN = 1
SYM   = 256


def leaf(val: str) -> Leaf:
    return Leaf(TOKEN, val)


def _warm(node: Node) -> None:
    if node.children:
        _ = node.children[0].next_sibling


def _check_consistency(node: Node) -> None:
    """Assert full sibling-map consistency for node."""
    children = node.children
    nmap = node.next_sibling_map
    pmap = node.prev_sibling_map
    if nmap is None or pmap is None:
        return  # maps not yet built — skip
    for i, ch in enumerate(children):
        expected_next = children[i + 1] if i + 1 < len(children) else None
        expected_prev = children[i - 1] if i > 0 else None
        assert nmap.get(id(ch)) is expected_next, (
            f"next_map[child@{i}] wrong: got {nmap.get(id(ch))}, want {expected_next}"
        )
        assert pmap.get(id(ch)) is expected_prev, (
            f"prev_map[child@{i}] wrong: got {pmap.get(id(ch))}, want {expected_prev}"
        )


# ---------------------------------------------------------------------------
# Golden-based formatting characterization
# ---------------------------------------------------------------------------

class TestFormattingGoldens:
    """Goldens captured on verify_base for inputs that don't touch first-child paths."""

    GOLDEN_SIMPLE_FUNC = (
        'def foo(a, b, c):\n'
        '    x = a + b\n'
        '    y = b + c\n'
        '    return x + y\n'
    )

    GOLDEN_CLASS_METHODS = (
        'class MyClass:\n'
        '    def method_a(self):\n'
        '        pass\n'
        '\n'
        '    def method_b(self):\n'
        '        return 1\n'
        '\n'
        '    def method_c(self):\n'
        '        return 2\n'
    )

    def test_simple_function_golden(self):
        """Formatting a simple function matches the captured golden."""
        src = (
            'def foo(a, b, c):\n'
            '    x = a + b\n'
            '    y = b + c\n'
            '    return x + y'
        )
        result = black.format_str(src, mode=black.Mode())
        assert result == self.GOLDEN_SIMPLE_FUNC

    def test_class_with_methods_golden(self):
        """Formatting a class with multiple methods matches the captured golden."""
        src = (
            'class MyClass:\n'
            '    def method_a(self):\n'
            '        pass\n'
            '    def method_b(self):\n'
            '        return 1\n'
            '    def method_c(self):\n'
            '        return 2'
        )
        result = black.format_str(src, mode=black.Mode())
        assert result == self.GOLDEN_CLASS_METHODS

    def test_idempotent_simple_function(self):
        """Formatting twice gives the same result as formatting once."""
        src = 'x = 1+2\ny=3\n'
        once  = black.format_str(src, mode=black.Mode())
        twice = black.format_str(once, mode=black.Mode())
        assert once == twice

    def test_idempotent_class(self):
        """Idempotency holds for a class definition."""
        src = self.GOLDEN_CLASS_METHODS
        once  = black.format_str(src, mode=black.Mode())
        twice = black.format_str(once, mode=black.Mode())
        assert once == twice


# ---------------------------------------------------------------------------
# Sibling-map consistency at non-zero positions (should pass on both branches)
# ---------------------------------------------------------------------------

class TestSiblingMapConsistencyNonFirst:
    """Consistency at positions > 0 was already correct; verify it still holds."""

    def test_insert_at_middle(self):
        a = leaf("a"); b = leaf("b"); c = leaf("c")
        node = Node(SYM, [a, c])
        _warm(node)
        node.insert_child(1, b)   # middle: before=a, after=c
        _check_consistency(node)

    def test_insert_at_end(self):
        a = leaf("a"); b = leaf("b")
        node = Node(SYM, [a])
        _warm(node)
        node.append_child(b)      # tail: before=a, after=None
        _check_consistency(node)

    def test_remove_middle_child(self):
        a = leaf("a"); b = leaf("b"); c = leaf("c")
        node = Node(SYM, [a, b, c])
        _warm(node)
        b.remove()
        _check_consistency(node)

    def test_remove_last_child(self):
        a = leaf("a"); b = leaf("b")
        node = Node(SYM, [a, b])
        _warm(node)
        b.remove()
        _check_consistency(node)

    def test_replace_middle_child(self):
        a = leaf("a"); b = leaf("b"); c = leaf("c")
        node = Node(SYM, [a, b, c])
        _warm(node)
        x = leaf("x")
        node.set_child(1, x)
        _check_consistency(node)

    def test_replace_last_child(self):
        a = leaf("a"); b = leaf("b")
        node = Node(SYM, [a, b])
        _warm(node)
        x = leaf("x")
        node.set_child(1, x)
        _check_consistency(node)
