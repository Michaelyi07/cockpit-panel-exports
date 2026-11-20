"""Seed fictional dashboard facts (run after alembic upgrade head).

Reads the same fictional dataset the test suite uses, so the walkthrough and
the tests exercise identical numbers."""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + "/1855-dash-exports")

from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import engine  # noqa: E402
from app.models import DashboardFact  # noqa: E402

FACTS = [
    ("occupancy", "rentable_workstations", "00000000-0000-0000-0000-000000000001", {"floor": "3F"}, "2026-11-30", 300.0, None),
    ("occupancy", "leased_workstations", "00000000-0000-0000-0000-000000000001", {"floor": "3F"}, "2026-11-30", 180.0, None),
    ("occupancy", "occ_rate", "00000000-0000-0000-0000-000000000001", {"floor": "3F"}, "2026-11-30", 0.6, None),
    ("occupancy", "rentable_workstations", "00000000-0000-0000-0000-000000000001", {"floor": "3F"}, "2026-12-31", 300.0, None),
    ("occupancy", "leased_workstations", "00000000-0000-0000-0000-000000000001", {"floor": "3F"}, "2026-12-31", 192.0, None),
    ("occupancy", "occ_rate", "00000000-0000-0000-0000-000000000001", {"floor": "3F"}, "2026-12-31", 0.64, None),
    ("occupancy", "rentable_workstations", "00000000-0000-0000-0000-000000000002", {"floor": "5F"}, "2026-11-30", 120.0, None),
    ("occupancy", "leased_workstations", "00000000-0000-0000-0000-000000000002", {"floor": "5F"}, "2026-11-30", 60.0, None),
    ("occupancy", "occ_rate", "00000000-0000-0000-0000-000000000002", {"floor": "5F"}, "2026-11-30", 0.5, None),
    ("revenue", "signed_value_cents", "00000000-0000-0000-0000-000000000001", {"channel": "direct"}, "2026-11-15", None, 1500000),
    ("revenue", "signed_value_cents", "00000000-0000-0000-0000-000000000001", {"channel": "referral"}, "2026-11-20", None, 2750000),
    ("revenue", "contracts_signed", "00000000-0000-0000-0000-000000000001", {"channel": "direct"}, "2026-11-15", 1.0, None),
    ("revenue", "contracts_signed", "00000000-0000-0000-0000-000000000001", {"channel": "referral"}, "2026-11-20", 2.0, None),
    ("revenue", "signed_value_cents", "00000000-0000-0000-0000-000000000002", {"channel": "direct"}, "2026-11-18", None, 900000),
    ("revenue", "contracts_signed", "00000000-0000-0000-0000-000000000002", {"channel": "direct"}, "2026-11-18", 1.0, None),
    ("leads", "leads_new", "00000000-0000-0000-0000-000000000001", {"source": "website"}, "2026-11-10", 12.0, None),
    ("leads", "leads_new", "00000000-0000-0000-0000-000000000001", {"source": "event"}, "2026-11-12", 7.0, None),
    ("leads", "leads_qualified", "00000000-0000-0000-0000-000000000001", {"source": "website"}, "2026-11-25", 5.0, None),
    ("leads", "leads_new", "00000000-0000-0000-0000-000000000002", {"source": "event"}, "2026-11-14", 4.0, None),
    ("leads", "leads_qualified", "00000000-0000-0000-0000-000000000002", {"source": "event"}, "2026-11-26", 2.0, None),
]

Session = sessionmaker(bind=engine)
with Session() as s:
    if s.query(DashboardFact).count() == 0:
        s.add_all([
            DashboardFact(org_id=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
                          site_id=uuid.UUID(site), panel=panel, metric_code=metric,
                          dimension=dim, period=period, value_num=num, value_cents=cents)
            for panel, metric, site, dim, period, num, cents in FACTS
        ])
        s.commit()
        print(f"seeded {len(FACTS)} fact rows")
    else:
        print("facts already present, skipped")
