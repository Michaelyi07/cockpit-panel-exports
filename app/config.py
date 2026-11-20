"""Environment-driven configuration (platform convention: secrets/config only from env)."""
from __future__ import annotations

import os
from pathlib import Path


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


DATABASE_URL = _env(
    "DATABASE_URL",
    "postgresql+psycopg://postgres@127.0.0.1:5433/dash_exports_1855",
)
STORAGE_DIR = Path(_env("STORAGE_DIR", "./storage"))
LINK_SECRET = _env("LINK_SECRET", "dev-link-secret-change-me")
LINK_TTL_SECONDS = int(_env("LINK_TTL_SECONDS", "86400"))  # 24h per brief
WORKER_POLL_SECONDS = float(_env("WORKER_POLL_SECONDS", "2"))
WORKER_ENABLED = _env("WORKER_ENABLED", "true").lower() == "true"
TIMEZONE = _env("TIMEZONE", "Asia/Shanghai")
CALIBER_VERSION = _env("CALIBER_VERSION", "v1.0")

# Identity stub (S2-IAM boundary). Real deployments swap in token-derived claims.
ROLE_OPS_MANAGER = "ops_manager"
