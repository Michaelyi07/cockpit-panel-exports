# -*- coding: utf-8 -*-
"""Test fixtures: a real PostgreSQL 16 database (env: TEST_DATABASE_URL), seeded
fictional facts, a TestClient with an isolated storage dir and worker disabled
(tests drive the worker deterministically via worker.process_pending()).

NOTE: environment must be configured at conftest import time (top-level), because
test modules import `app.*` at collection — before any fixture runs."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres@127.0.0.1:5433/dash_exports_1855_test",
)
ADMIN_DSN = os.environ.get(
    "ADMIN_DATABASE_URL",
    "postgresql+psycopg://postgres@127.0.0.1:5433/postgres",
)

# ── top-level env config: must precede any `app.*` import ──────────────────
os.environ["DATABASE_URL"] = TEST_DSN
os.environ["WORKER_ENABLED"] = "false"
_TMP_STORAGE = Path(tempfile.mkdtemp(prefix="dash-storage-"))
os.environ["STORAGE_DIR"] = str(_TMP_STORAGE)
os.environ["LINK_SECRET"] = "test-link-secret"
os.environ["LINK_TTL_SECONDS"] = "86400"

from sqlalchemy import create_engine, text  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

_admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
with _admin.connect() as _conn:
    _conn.execute(text('DROP DATABASE IF EXISTS "dash_exports_1855_test" WITH (FORCE)'))
    _conn.execute(text('CREATE DATABASE "dash_exports_1855_test"'))

_cfg = Config(str(_ROOT / "alembic.ini"))
os.chdir(_ROOT)
command.upgrade(_cfg, "head")

from app.db import Base, engine  # noqa: E402
from app.models import DashboardFact  # noqa: E402

ORG = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
SITE_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
SITE_B = uuid.UUID("00000000-0000-0000-0000-000000000002")
FACTS = [
    ("occupancy", "rentable_workstations", SITE_A, {"floor": "3F"}, "2026-11-30", 300.0, None),
    ("occupancy", "leased_workstations", SITE_A, {"floor": "3F"}, "2026-11-30", 180.0, None),
    ("occupancy", "occ_rate", SITE_A, {"floor": "3F"}, "2026-11-30", 0.6, None),
    ("occupancy", "rentable_workstations", SITE_A, {"floor": "3F"}, "2026-12-31", 300.0, None),
    ("occupancy", "leased_workstations", SITE_A, {"floor": "3F"}, "2026-12-31", 192.0, None),
    ("occupancy", "occ_rate", SITE_A, {"floor": "3F"}, "2026-12-31", 0.64, None),
    ("occupancy", "rentable_workstations", SITE_B, {"floor": "5F"}, "2026-11-30", 120.0, None),
    ("occupancy", "leased_workstations", SITE_B, {"floor": "5F"}, "2026-11-30", 60.0, None),
    ("occupancy", "occ_rate", SITE_B, {"floor": "5F"}, "2026-11-30", 0.5, None),
    ("revenue", "signed_value_cents", SITE_A, {"channel": "direct"}, "2026-11-15", None, 1_500_000),
    ("revenue", "signed_value_cents", SITE_A, {"channel": "referral"}, "2026-11-20", None, 2_750_000),
    ("revenue", "contracts_signed", SITE_A, {"channel": "direct"}, "2026-11-15", 1.0, None),
    ("revenue", "contracts_signed", SITE_A, {"channel": "referral"}, "2026-11-20", 2.0, None),
    ("revenue", "signed_value_cents", SITE_B, {"channel": "direct"}, "2026-11-18", None, 900_000),
    ("revenue", "contracts_signed", SITE_B, {"channel": "direct"}, "2026-11-18", 1.0, None),
    ("leads", "leads_new", SITE_A, {"source": "website"}, "2026-11-10", 12.0, None),
    ("leads", "leads_new", SITE_A, {"source": "event"}, "2026-11-12", 7.0, None),
    ("leads", "leads_qualified", SITE_A, {"source": "website"}, "2026-11-25", 5.0, None),
    ("leads", "leads_new", SITE_B, {"source": "event"}, "2026-11-14", 4.0, None),
    ("leads", "leads_qualified", SITE_B, {"source": "event"}, "2026-11-26", 2.0, None),
]

with engine.begin() as _conn:
    _session = __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(bind=engine)()
    _session.add_all([
        DashboardFact(org_id=ORG, site_id=site, panel=panel, metric_code=metric,
                      dimension=dim, period=period, value_num=num, value_cents=cents)
        for panel, metric, site, dim, period, num, cents in FACTS
    ])
    _session.commit()
    _session.close()


@pytest.fixture(scope="session")
def seed_data():
    return {"org_id": ORG, "site_a": SITE_A, "site_b": SITE_B}


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


ANALYST = {"X-User-Id": "analyst-1", "X-Role": "analyst"}
MANAGER = {"X-User-Id": "manager-1", "X-Role": "ops_manager"}
