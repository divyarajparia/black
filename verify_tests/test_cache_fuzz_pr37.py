"""
Seeded differential fuzz / stability test for PR #37 (pickle -> JSON cache).
Reads VERIFY_STRESS_GRID from env; falls back to ANALYSIS stress_params.
Caps at ~120 (input, config) iterations.
"""

import json
import os
import random
import sys
from itertools import islice, product
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def reload_cache(cache_dir):
    for mod in list(sys.modules.keys()):
        if mod == "black.cache" or mod.startswith("black.cache."):
            del sys.modules[mod]
    import importlib
    import black.cache as bc
    importlib.reload(bc)
    bc.CACHE_DIR = Path(cache_dir)
    return bc


# ---------------------------------------------------------------------------
# Load stress grid from env or fall back to ANALYSIS values
# ---------------------------------------------------------------------------
_DEFAULT_GRID = {
    "cache file contents (raw JSON)": [
        "{}",
        '{"path": [1700000000.0, 1234, "abc123"]}',
        '{"path": [1700000000.0, 1234, "abc123", "extra"]}',
        '{"path": null}',
        '{"path": ["not_a_float", 1234, "abc123"]}',
        '"not a dict at top level"',
        "malformed/truncated JSON bytes",
    ],
    "number of cached source paths": [0, 1, 1000],
}

_raw_grid = os.environ.get("VERIFY_STRESS_GRID", "{}")
try:
    _GRID = json.loads(_raw_grid)
    if not _GRID:
        _GRID = _DEFAULT_GRID
except json.JSONDecodeError:
    _GRID = _DEFAULT_GRID

_raw_content_values = _GRID.get(
    "cache file contents (raw JSON)",
    _DEFAULT_GRID["cache file contents (raw JSON)"],
)
_path_counts = _GRID.get(
    "number of cached source paths",
    _DEFAULT_GRID["number of cached source paths"],
)

# ---------------------------------------------------------------------------
# Seed generation
# ---------------------------------------------------------------------------
_RNG = random.Random(1234)

_HEX = "0123456789abcdef"

_SEED_VALID = [
    {},
    {"path/to/file.py": [1700000000.0, 1234, "a" * 64]},
    {"a.py": [0.0, 0, "b" * 64]},
    {"b.py": [1.5e9, 999999, "c" * 64]},
]

_PATH_VARIANTS = [
    "simple.py",
    "dir/sub/file.py",
    "space_in_name.py",
    "unicode_ea.py",
    "a" * 50 + ".py",
]


def _gen_valid_payloads(n):
    results = list(_SEED_VALID)
    for i in range(n):
        new = {}
        count = _RNG.randint(0, 5)
        for j in range(count):
            path_key = _RNG.choice(_PATH_VARIANTS) + f"_{i}_{j}"
            mtime = _RNG.uniform(0.0, 2e9)
            size = _RNG.randint(0, 10 ** 7)
            hash_val = "".join(_RNG.choices(_HEX, k=64))
            new[path_key] = [mtime, size, hash_val]
        results.append(new)
    return results[:n]


MAX_COMBOS = 120
_valid_payloads = _gen_valid_payloads(30)

# Build cross-product cases
_cases_a = list(product(_valid_payloads, _path_counts))
_cases_b = list(product(
    [{"__RAW__": s} for s in _raw_content_values],
    _path_counts,
))
_all = _cases_a + _cases_b
_RNG.shuffle(_all)
_CASES = list(islice(_all, MAX_COMBOS))

_UNEXPECTED = (AttributeError, IndexError, KeyError, RecursionError, AssertionError)


# ---------------------------------------------------------------------------
# Fuzz: inject raw content into cache file, then call Cache.read
# ---------------------------------------------------------------------------
class TestCacheFuzzReadStability:
    @pytest.mark.parametrize("case_idx", range(len(_CASES)))
    def test_fuzz_read_case(self, case_idx, tmp_path):
        payload_or_raw, n_paths = _CASES[case_idx]
        bc = reload_cache(str(tmp_path))
        from black import Mode
        mode = Mode()
        cache_file = bc.get_cache_file(mode)
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(payload_or_raw, dict) and "__RAW__" in payload_or_raw:
            raw_str = payload_or_raw["__RAW__"]
            cache_file.write_text(raw_str, encoding="utf-8", errors="replace")
        else:
            cache_file.write_text(json.dumps(payload_or_raw), encoding="utf-8")

        try:
            cache = bc.Cache.read(mode)
        except _UNEXPECTED as e:
            pytest.fail(f"Unexpected internal error from Cache.read: {type(e).__name__}: {e}")
        except Exception:
            return  # documented/expected errors (OSError etc) are acceptable

        # Invariant: file_data must be a dict with correct value types
        assert isinstance(cache.file_data, dict)
        for k, v in cache.file_data.items():
            assert isinstance(k, str)
            assert isinstance(v.st_mtime, float), f"st_mtime should be float, got {type(v.st_mtime)}"
            assert isinstance(v.st_size, int), f"st_size should be int, got {type(v.st_size)}"
            assert isinstance(v.hash, str), f"hash should be str, got {type(v.hash)}"


# ---------------------------------------------------------------------------
# Fuzz: write then read round-trip for varying path counts
# ---------------------------------------------------------------------------
class TestCacheFuzzWriteReadRoundTrip:
    @pytest.mark.parametrize("n_paths", _path_counts)
    def test_write_then_read_round_trips(self, n_paths, tmp_path):
        bc = reload_cache(str(tmp_path))
        from black import Mode
        mode = Mode()
        srcs = []
        actual_n = min(n_paths, 50)  # cap heavy case for speed
        for i in range(actual_n):
            p = tmp_path / f"src_{i}.py"
            p.write_text(f"x = {i}\n", encoding="utf-8")
            srcs.append(p)

        cache = bc.Cache.read(mode)
        cache.write(srcs)

        try:
            cache2 = bc.Cache.read(mode)
        except _UNEXPECTED as e:
            pytest.fail(f"Unexpected internal error from Cache.read after write: {e}")

        for src in srcs:
            key = str(src.resolve())
            assert key in cache2.file_data, f"{key} missing after round-trip"
            fd = cache2.file_data[key]
            orig = cache.file_data[key]
            assert fd.st_mtime == orig.st_mtime
            assert fd.st_size == orig.st_size
            assert fd.hash == orig.hash
            assert not cache2.is_changed(src), f"is_changed must be False after write for {src}"


# ---------------------------------------------------------------------------
# Fuzz: atomic write — file must be valid JSON after write
# ---------------------------------------------------------------------------
class TestCacheFuzzAtomicWrite:
    @pytest.mark.parametrize("case_idx", range(min(len(_CASES), 20)))
    def test_atomic_write_leaves_valid_json(self, case_idx, tmp_path):
        bc = reload_cache(str(tmp_path))
        from black import Mode
        mode = Mode()
        src = tmp_path / "atom_src.py"
        src.write_text("y = 42\n", encoding="utf-8")

        cache = bc.Cache.read(mode)
        cache.write([src])

        cache_file = bc.get_cache_file(mode)
        if not cache_file.exists():
            return  # silently failed (OSError) — acceptable

        try:
            with cache_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            assert isinstance(data, dict), "Cache file must be a JSON object after write"
        except _UNEXPECTED as e:
            pytest.fail(f"Unexpected error reading cache after write: {e}")
        except (json.JSONDecodeError, OSError) as e:
            pytest.fail(
                f"Cache file is not valid JSON after write (atomicity violation?): {e}"
            )
