"""Caching of formatted files with feature-based invalidation."""

import hashlib
import hmac
import os
import pickle
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from platformdirs import user_cache_dir

from _black_version import version as __version__
from black.mode import Mode
from black.output import err

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

# Length in bytes of the HMAC-SHA256 digest prepended to every cache file.
_HMAC_DIGEST_SIZE = 32


def _cache_file_hmac_key(cache_file: Path) -> bytes:
    """Derive a stable HMAC key from the cache file path and the black version.

    The key is intentionally tied to the file path so that a cache file cannot
    be moved or renamed to satisfy the integrity check of a different path.
    This is not a secret key — the goal is *integrity* (detecting accidental
    corruption or malicious tampering), not confidentiality.
    """
    material = f"{cache_file}:{__version__}".encode()
    return hashlib.sha256(material).digest()


def _sign_cache_data(data: bytes, cache_file: Path) -> bytes:
    """Return HMAC-SHA256 digest || data for the given pickled cache bytes."""
    key = _cache_file_hmac_key(cache_file)
    digest = hmac.new(key, data, hashlib.sha256).digest()
    return digest + data


def _verify_and_strip_cache_data(signed: bytes, cache_file: Path) -> bytes:
    """Verify the HMAC prefix and return the raw pickle bytes.

    Raises ``ValueError`` if the data is too short or the digest does not match,
    which signals that the cache should be treated as invalid.
    """
    if len(signed) < _HMAC_DIGEST_SIZE:
        raise ValueError("Cache file too short to contain HMAC digest")
    stored_digest = signed[:_HMAC_DIGEST_SIZE]
    data = signed[_HMAC_DIGEST_SIZE:]
    key = _cache_file_hmac_key(cache_file)
    expected_digest = hmac.new(key, data, hashlib.sha256).digest()
    if not hmac.compare_digest(stored_digest, expected_digest):
        raise ValueError("Cache file HMAC digest mismatch — file may be tampered")
    return data


class FileData(NamedTuple):
    st_mtime: float
    st_size: int
    hash: str


def get_cache_dir() -> Path:
    """Get the cache directory used by black.

    Users can customize this directory on all systems using `BLACK_CACHE_DIR`
    environment variable. By default, the cache directory is the user cache directory
    under the black application.

    This result is immediately set to a constant `black.cache.CACHE_DIR` as to avoid
    repeated calls.
    """
    # NOTE: Function mostly exists as a clean way to test getting the cache directory.
    default_cache_dir = user_cache_dir("black")
    cache_dir = Path(os.environ.get("BLACK_CACHE_DIR", default_cache_dir))
    cache_dir = cache_dir / __version__
    return cache_dir


CACHE_DIR = get_cache_dir()


def get_cache_file(mode: Mode) -> Path:
    return CACHE_DIR / f"cache.{mode.get_cache_key()}.pickle"


@dataclass
class Cache:
    mode: Mode
    cache_file: Path
    file_data: dict[str, FileData] = field(default_factory=dict)

    @classmethod
    def read(cls, mode: Mode) -> Self:
        """Read the cache if it exists and is well-formed.

        If it is not well-formed, the call to write later should
        resolve the issue.
        """
        cache_file = get_cache_file(mode)
        try:
            exists = cache_file.exists()
        except OSError as e:
            # Likely file too long; see #4172 and #4174
            err(f"Unable to read cache file {cache_file} due to {e}")
            return cls(mode, cache_file)
        if not exists:
            return cls(mode, cache_file)

        with cache_file.open("rb") as fobj:
            try:
                signed = fobj.read()
                raw = _verify_and_strip_cache_data(signed, cache_file)
                data: dict[str, tuple[float, int, str]] = pickle.loads(raw)
                file_data = {k: FileData(*v) for k, v in data.items()}
            except (pickle.UnpicklingError, ValueError, IndexError):
                return cls(mode, cache_file)

        return cls(mode, cache_file, file_data)

    @staticmethod
    def hash_digest(path: Path) -> str:
        """Return hash digest for path."""

        data = path.read_bytes()
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def get_file_data(path: Path) -> FileData:
        """Return file data for path."""

        stat = path.stat()
        hash = Cache.hash_digest(path)
        return FileData(stat.st_mtime, stat.st_size, hash)

    def is_changed(self, source: Path) -> bool:
        """Check if source has changed compared to cached version."""
        res_src = source.resolve()
        old = self.file_data.get(str(res_src))
        if old is None:
            return True

        st = res_src.stat()
        if st.st_size != old.st_size:
            return True
        if st.st_mtime != old.st_mtime:
            new_hash = Cache.hash_digest(res_src)
            if new_hash != old.hash:
                return True
        return False

    def filtered_cached(self, sources: Iterable[Path]) -> tuple[set[Path], set[Path]]:
        """Split an iterable of paths in `sources` into two sets.

        The first contains paths of files that modified on disk or are not in the
        cache. The other contains paths to non-modified files.
        """
        changed: set[Path] = set()
        done: set[Path] = set()
        for src in sources:
            if self.is_changed(src):
                changed.add(src)
            else:
                done.add(src)
        return changed, done

    def write(self, sources: Iterable[Path]) -> None:
        """Update the cache file data and write a new cache file."""
        self.file_data.update(
            **{str(src.resolve()): Cache.get_file_data(src) for src in sources}
        )
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=str(self.cache_file.parent), delete=False
            ) as f:
                # We store raw tuples in the cache because it's faster.
                data: dict[str, tuple[float, int, str]] = {
                    k: (*v,) for k, v in self.file_data.items()
                }
                raw = pickle.dumps(data, protocol=4)
                # Prepend an HMAC-SHA256 digest to detect cache tampering.
                # An attacker who can write to the cache directory could
                # otherwise craft a malicious pickle that executes arbitrary
                # code the next time `black` runs.
                f.write(_sign_cache_data(raw, self.cache_file))
            os.replace(f.name, self.cache_file)
        except OSError:
            pass
