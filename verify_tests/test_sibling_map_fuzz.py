"""
DIFFERENTIAL FUZZ / STABILITY test for PR #34.

Seeded RNG (Random(1234)) generates ~60 (input, config) combinations that
exercise node-tree mutations at every child position.  For each combination it
asserts:
  1. No unexpected internal error (AttributeError, IndexError, KeyError,
     RecursionError, AssertionError from inside blib2to3).
  2. next_map_no_none_key invariant: after insert_child(0) the none-slot in
     next_sibling_map must NOT have been overwritten to the newly inserted child
     (the key corruption the PR fixes).
  3. sibling_map_consistency invariant: every child's sibling pointers are correct.
  4. idempotent_round_trip: black.format_str applied twice == applied once.
  5. output_reparseable: formatted output can be round-tripped through
     black.format_str without raising.

VERIFY_STRESS_GRID env-var (JSON) overrides the parameter grid; falls back to
ANALYSIS.stress_params values.
"""

import json
import os
import random
import itertools

import pytest
import black
from blib2to3.pytree import Node, Leaf

# ---------------------------------------------------------------------------
# Config grid (from env or fallback)
# ---------------------------------------------------------------------------

_raw_grid = os.environ.get("VERIFY_STRESS_GRID", "{}")
_grid = json.loads(_raw_grid) if _raw_grid.strip() else {}

INSERTION_INDICES = _grid.get("child_insertion_index", [0, 1, 2])
REMOVAL_COUNTS    = _grid.get("child_count_at_removal", [1, 2, 3])
REPLACE_POSITIONS = _grid.get("replaced_child_position", ["first", "middle", "last"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOKEN = 1
SYM   = 256
RNG   = random.Random(1234)


def _leaf(val: str) -> Leaf:
    return Leaf(TOKEN, val)


def _warm(node: Node) -> None:
    """Force sibling-map initialisation by reading first child's next_sibling."""
    if node.children:
        _ = node.children[0].next_sibling


def _none_slot(node: Node):
    """Return next_sibling_map[id(None)] — the sentinel slot."""
    nmap = node.next_sibling_map
    if nmap is None:
        return None
    return nmap.get(id(None))


def _check_consistency(node: Node) -> None:
    """Assert full sibling-map consistency for node."""
    children = node.children
    nmap = node.next_sibling_map
    pmap = node.prev_sibling_map
    if nmap is None or pmap is None:
        return
    for i, ch in enumerate(children):
        want_next = children[i + 1] if i + 1 < len(children) else None
        want_prev = children[i - 1] if i > 0 else None
        got_next = nmap.get(id(ch))
        got_prev = pmap.get(id(ch))
        assert got_next is want_next, (
            f"next_map[child@{i}] = {got_next!r}, want {want_next!r}"
        )
        assert got_prev is want_prev, (
            f"prev_map[child@{i}] = {got_prev!r}, want {want_prev!r}"
        )


# ---------------------------------------------------------------------------
# Black-level invariants
# ---------------------------------------------------------------------------

_EXPECTED_ERRORS = (black.InvalidInput,)


def _assert_black_invariants(src: str) -> None:
    """Assert idempotency and reparseability for a Python source snippet."""
    try:
        once = black.format_str(src, mode=black.Mode())
    except _EXPECTED_ERRORS:
        return
    except (AttributeError, IndexError, KeyError, RecursionError, AssertionError) as e:
        raise AssertionError(f"Unexpected internal error on first format: {e}") from e

    try:
        twice = black.format_str(once, mode=black.Mode())
    except _EXPECTED_ERRORS:
        raise AssertionError("Second format rejected output of first format.")
    except (AttributeError, IndexError, KeyError, RecursionError, AssertionError) as e:
        raise AssertionError(f"Unexpected internal error on second format: {e}") from e

    assert once == twice, (
        f"Idempotency violation:\nFirst:  {once!r}\nSecond: {twice!r}"
    )


# ---------------------------------------------------------------------------
# Seed Python source snippets
# ---------------------------------------------------------------------------

SEED_SOURCES = [
    "def f(a):\n    return a\n",
    "def g(a, b, c):\n    x = a + b\n    return x + c\n",
    "class C:\n    def m(self):\n        pass\n    def n(self):\n        return 1\n",
    "def outer(x):\n    def inner(y):\n        return x + y\n    return inner\n",
    "import os\nx = 1\ny = 2\nz = x + y\n",
    "if x:\n    a = 1\nelif y:\n    a = 2\nelse:\n    a = 3\n",
    "result = [i * 2 for i in range(10) if i % 2 == 0]\n",
    "@decorator\ndef f():\n    pass\n",
]


def _mutate_source(src: str, seed: int) -> str:
    rng = random.Random(seed)
    mutations = [
        lambda s: s.replace("a", rng.choice(["alpha", "a1", "x"])),
        lambda s: s + "\n# comment after\n",
        lambda s: "\n# comment before\n" + s,
        lambda s: s + "z = None\n",
        lambda s: "x = 1\n" + s,
    ]
    chosen = rng.choice(mutations)
    try:
        return chosen(src)
    except Exception:
        return src


def _generate_sources(n: int) -> list:
    sources = list(SEED_SOURCES)
    for i in range(n):
        base = RNG.choice(SEED_SOURCES)
        sources.append(_mutate_source(base, i))
    return sources


# ---------------------------------------------------------------------------
# Fuzz test: pytree-level mutation invariants
# ---------------------------------------------------------------------------

def _build_cases_pytree():
    cases = []
    for ins in INSERTION_INDICES:
        for rem in REMOVAL_COUNTS:
            for rep in REPLACE_POSITIONS:
                cases.append((ins, rem, rep))
    RNG2 = random.Random(42)
    RNG2.shuffle(cases)
    return cases[:20]


class TestFuzzSiblingMaps:
    """Seeded fuzz over pytree-level mutations."""

    @pytest.mark.parametrize("ins_idx,rem_count,rep_pos", _build_cases_pytree())
    def test_mutation_combo(self, ins_idx, rem_count, rep_pos):
        # ---- INSERT at ins_idx ----
        n = max(ins_idx + 1, 3)
        children = [_leaf(f"v{i}") for i in range(n)]
        node = Node(SYM, children)
        _warm(node)
        original_none_slot = _none_slot(node)   # points to original first child

        new_leaf = _leaf("NEW")
        safe_ins = min(ins_idx, len(node.children))
        node.insert_child(safe_ins, new_leaf)

        if safe_ins == 0:
            # The PR's fix: none-slot must NOT be overwritten to new_leaf
            current_none_slot = _none_slot(node)
            assert current_none_slot is not new_leaf, (
                f"None-slot overwritten to new_leaf after insert_child(0) "
                f"(base bug). Got: {current_none_slot!r}"
            )
        _check_consistency(node)

        # ---- REMOVE first child ----
        node2 = Node(SYM, [_leaf(f"r{i}") for i in range(rem_count)])
        _warm(node2)
        first = node2.children[0]
        original_first = first
        first.remove()
        # After removal, maps should be consistent
        _check_consistency(node2)
        # Removed child should not appear in map
        nmap2 = node2.next_sibling_map
        if nmap2 is not None:
            assert id(original_first) not in nmap2, (
                "Removed first child still has an entry in next_sibling_map"
            )

        # ---- REPLACE at rep_pos ----
        r_children = [_leaf(f"p{i}") for i in range(3)]
        node3 = Node(SYM, r_children)
        _warm(node3)
        none_slot_before = _none_slot(node3)
        idx_map = {"first": 0, "middle": 1, "last": 2}
        rep_idx = idx_map.get(rep_pos, 0)
        replacement = _leaf("REP")
        node3.set_child(rep_idx, replacement)

        if rep_idx == 0:
            # The PR's fix: none-slot must NOT be overwritten to replacement
            current_none_slot = _none_slot(node3)
            assert current_none_slot is not replacement, (
                f"None-slot overwritten to replacement after set_child(0) "
                f"(base bug). Got: {current_none_slot!r}"
            )
        _check_consistency(node3)


# ---------------------------------------------------------------------------
# Fuzz test: black-level idempotency and reparseability
# ---------------------------------------------------------------------------

def _build_black_cases():
    sources = _generate_sources(50)
    return sources[:40]


class TestFuzzBlackInvariants:
    """Seeded fuzz: black.format_str idempotency and no internal crash."""

    @pytest.mark.parametrize("src", _build_black_cases())
    def test_idempotent_and_reparseable(self, src):
        _assert_black_invariants(src)
