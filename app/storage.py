"""Object-storage adapter boundary.

LocalStorageAdapter keeps files on disk and mints HMAC-signed download URLs
with an expiry timestamp — behaviourally equivalent to S3 presigned URLs for
the purpose of this ticket. Swapping in a real S3 client means implementing
the same three methods; callers never touch the filesystem directly.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path

from . import config


class StorageAdapter:
    def put(self, key: str, data: bytes) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def get(self, key: str) -> bytes | None:  # pragma: no cover - interface
        raise NotImplementedError

    def presign(self, key: str, ttl_seconds: int | None = None) -> str:  # pragma: no cover
        raise NotImplementedError

    def verify(self, key: str, expires: str, sig: str) -> tuple[bool, str]:
        """Returns (ok, reason). reason in {'ok','bad_signature','expired'}."""
        raise NotImplementedError  # pragma: no cover


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, base_dir: Path | None = None, secret: str | None = None):
        self.base = Path(base_dir or config.STORAGE_DIR)
        self.base.mkdir(parents=True, exist_ok=True)
        self.secret = (secret or config.LINK_SECRET).encode("utf-8")

    # -- object read/write ------------------------------------------------
    def _path(self, key: str) -> Path:
        safe = key.replace("\\", "/").lstrip("/")
        if ".." in safe.split("/"):
            raise ValueError("invalid storage key")
        return self.base / safe

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return path.read_bytes()

    # -- presigned links ---------------------------------------------------
    def _sign(self, key: str, expires: int) -> str:
        msg = f"{key}|{expires}".encode("utf-8")
        return hmac.new(self.secret, msg, hashlib.sha256).hexdigest()

    def presign(self, key: str, ttl_seconds: int | None = None) -> str:
        ttl = int(ttl_seconds if ttl_seconds is not None else config.LINK_TTL_SECONDS)
        expires = int(time.time()) + ttl
        sig = self._sign(key, expires)
        return f"/files/{key}?expires={expires}&sig={sig}"

    def verify(self, key: str, expires: str, sig: str) -> tuple[bool, str]:
        try:
            exp = int(expires)
        except (TypeError, ValueError):
            return False, "bad_signature"
        if not hmac.compare_digest(self._sign(key, exp), sig or ""):
            return False, "bad_signature"
        if exp < int(time.time()):
            return False, "expired"
        return True, "ok"


_adapter: StorageAdapter | None = None


def get_storage() -> StorageAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LocalStorageAdapter()
    return _adapter


def set_storage(adapter: StorageAdapter) -> None:
    global _adapter
    _adapter = adapter
