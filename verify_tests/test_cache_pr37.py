"""
Test suite for PR #37: pickle -> JSON cache serialization.
Covers Cache.read, Cache.write, get_cache_file.
"""

import json
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def reload_cache_module(cache_dir: str):
    for mod in list(sys.modules.keys()):
        if mod == "black.cache" or mod.startswith("black.cache."):
            del sys.modules[mod]
    import importlib
    import black.cache as bc
    importlib.reload(bc)
    bc.CACHE_DIR = Path(cache_dir)
    return bc


def make_source_file(td, name="src.py", content=None):
    if content is None:
        content = "x = 1\n"
    p = Path(td) / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# T01 - INTENT_AWARE: get_cache_file produces .json filename (not .pickle)
# ---------------------------------------------------------------------------
class TestGetCacheFileExtension:
    def test_cache_file_has_json_extension(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        cf = bc.get_cache_file(Mode())
        assert cf.suffix == ".json", (
            f"Expected .json suffix, got {cf.suffix!r}. "
            "PR #37 claims to replace .pickle with .json."
        )

    def test_cache_file_no_pickle_in_name(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        cf = bc.get_cache_file(Mode())
        assert "pickle" not in cf.name, (
            f"cache filename still contains 'pickle': {cf.name!r}"
        )


# ---------------------------------------------------------------------------
# T02 - CHARACTERIZATION: empty cache read returns empty file_data
# ---------------------------------------------------------------------------
class TestReadEmptyCache:
    def test_no_cache_file_returns_empty(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        cache = bc.Cache.read(Mode())
        assert cache.file_data == {}, "Expected empty file_data when no cache exists"


# ---------------------------------------------------------------------------
# T03 - INTENT_AWARE: Cache.write produces a JSON-readable file on disk
# ---------------------------------------------------------------------------
class TestWriteProducesJsonFile:
    def test_written_cache_is_valid_json(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        mode = Mode()
        src = make_source_file(str(tmp_path))
        cache = bc.Cache.read(mode)
        cache.write([src])
        cache_file = bc.get_cache_file(mode)
        assert cache_file.exists(), "Cache file was not created"
        with cache_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        assert isinstance(data, dict), "Serialized cache must be a JSON object"

    def test_written_file_has_json_suffix(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        mode = Mode()
        src = make_source_file(str(tmp_path))
        cache = bc.Cache.read(mode)
        cache.write([src])
        cache_file = bc.get_cache_file(mode)
        assert cache_file.suffix == ".json"


# ---------------------------------------------------------------------------
# T04 - INTENT_AWARE: cache round-trips losslessly through JSON
# ---------------------------------------------------------------------------
class TestCacheRoundTrip:
    def test_round_trip_single_entry(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        mode = Mode()
        src = make_source_file(str(tmp_path))
        cache = bc.Cache.read(mode)
        cache.write([src])
        cache2 = bc.Cache.read(mode)
        assert len(cache2.file_data) == 1
        key = str(src.resolve())
        assert key in cache2.file_data
        fd = cache2.file_data[key]
        assert isinstance(fd.st_mtime, float)
        assert isinstance(fd.st_size, int)
        assert isinstance(fd.hash, str)
        assert len(fd.hash) == 64, "SHA-256 hex digest must be 64 chars"

    def test_is_changed_false_after_write(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        mode = Mode()
        src = make_source_file(str(tmp_path))
        cache = bc.Cache.read(mode)
        cache.write([src])
        cache2 = bc.Cache.read(mode)
        assert not cache2.is_changed(src), (
            "After Cache.write, is_changed must return False for the written path"
        )

    def test_round_trip_1000_entries(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        mode = Mode()
        srcs = []
        for i in range(1000):
            p = make_source_file(str(tmp_path), f"src_{i}.py", f"x = {i}\n")
            srcs.append(p)
        cache = bc.Cache.read(mode)
        cache.write(srcs)
        cache2 = bc.Cache.read(mode)
        assert len(cache2.file_data) == 1000
        for src in srcs:
            assert not cache2.is_changed(src)


# ---------------------------------------------------------------------------
# T05 - INTENT_AWARE: corrupt / malformed cache returns empty (not exception)
# Invariant: corrupt_cache_returns_empty
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_content,desc", [
    (b"{}", "empty JSON object"),
    (b'{"path": [1700000000.0, 1234, "abc123", "extra"]}', "4-element list (too many)"),
    (b'{"path": null}', "null value"),
    (b'{"path": ["not_a_float", 1234, "abc123"]}', "first element not float"),
    (b'"not a dict at top level"', "top-level string, not dict"),
    (b"malformed{{json", "malformed/truncated JSON"),
    (b"", "empty file"),
    (b"[1, 2, 3]", "top-level array"),
    (b'{"path": [1700000000.0, "not_int", "abc123"]}', "second element not int"),
    (b'{"path": [1700000000.0, 1234, 999]}', "third element not str"),
])
class TestCorruptCacheReturnsEmpty:
    def test_corrupt_cache_returns_empty(self, tmp_path, raw_content, desc):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        mode = Mode()
        cache_file = bc.get_cache_file(mode)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(raw_content)
        cache = bc.Cache.read(mode)
        assert cache.file_data == {}, (
            f"Corrupt cache ({desc}) must yield empty file_data, got {cache.file_data!r}"
        )


# ---------------------------------------------------------------------------
# T06 - CHARACTERIZATION: mode isolation
# ---------------------------------------------------------------------------
class TestModeIsolation:
    def test_distinct_modes_have_distinct_cache_files(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        from black.mode import TargetVersion
        modes = [
            Mode(),
            Mode(line_length=1),
            Mode(line_length=1000),
            Mode(is_pyi=True),
            Mode(preview=True),
            Mode(target_versions={TargetVersion.PY310}),
        ]
        paths = [bc.get_cache_file(m) for m in modes]
        assert len(paths) == len(set(paths)), (
            "Different Mode configs must map to different cache files"
        )

    def test_write_to_one_mode_does_not_affect_another(self, tmp_path):
        bc = reload_cache_module(str(tmp_path))
        from black import Mode
        mode_a = Mode()
        mode_b = Mode(line_length=1)
        src = make_source_file(str(tmp_path))
        cache_a = bc.Cache.read(mode_a)
        cache_a.write([src])
        cache_b = bc.Cache.read(mode_b)
        assert cache_b.file_data == {}, (
            "Writing to mode_a cache must not affect mode_b cache"
        )
