# -*- coding: utf-8 -*-
"""Unified convention: secrets/config only from env. LINK_SECRET must be
provided; the SERVICE refuses to start without it (guard in create_app), so no
download link can ever be signed with a fabricated placeholder. Importing
config/migrations stays possible with only DATABASE_URL set."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def test_required_env_rejects_missing(monkeypatch):
    from app import config

    monkeypatch.delenv("DASH_TEST_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="missing required environment variable"):
        config._required_env("DASH_TEST_SECRET")

    monkeypatch.setenv("DASH_TEST_SECRET", "from-env")
    assert config._required_env("DASH_TEST_SECRET") == "from-env"


def test_service_start_without_link_secret_refuses():
    """A fresh interpreter calling create_app() with LINK_SECRET unset must
    fail — proof the service cannot boot with the placeholder removed."""
    env = dict(os.environ)
    env.pop("LINK_SECRET", None)
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import create_app; create_app()"],
        cwd=str(_ROOT), env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "LINK_SECRET" in result.stderr


def test_service_start_with_link_secret_succeeds():
    """With LINK_SECRET present the app factory builds cleanly."""
    env = dict(os.environ)
    env["LINK_SECRET"] = "a-real-secret-from-env"
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import create_app; create_app(); print('APP_OK')"],
        cwd=str(_ROOT), env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "APP_OK" in result.stdout


def test_import_config_without_secret_still_works():
    """Migrations/tools can import config with no secret (startup guard is not
    at import time), so `alembic upgrade head` needs no signing key."""
    env = dict(os.environ)
    env.pop("LINK_SECRET", None)
    result = subprocess.run(
        [sys.executable, "-c", "import app.config; print('CONFIG_OK')"],
        cwd=str(_ROOT), env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CONFIG_OK" in result.stdout
