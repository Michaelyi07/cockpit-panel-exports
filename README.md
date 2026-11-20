# Dash Exports — Cockpit Panel Export (S3-DASH-004)

Member Space Platform · Cockpit Panel Export: Caliber Page, Approval Gate & Watermark Numbers.

Async XLSX/CSV export service for cockpit panels with a caliber (metric
definition) worksheet, an operation-manager approval gate for detail-bearing
exports, unique watermark numbers (sheet headers + workbook file properties),
24-hour presigned download links, and full audit coverage of every export
event — running on PostgreSQL 16.

## Acceptance criteria → implementation → tests

| # | Acceptance criterion | Implementation | Tests |
|---|---|---|---|
| 1 | Exported XLSX contains a data sheet and a caliber worksheet with caliber instructions (metric code, definition, version, data end time, filter conditions) | `app/generator.py` builds "Panel Data" + "Caliber" sheets; caliber rows render from the metric registry (`app/panels.py`) with per-export data-end-time and filter echo | `tests/test_acceptance_1_xlsx_sheets.py` (4 cases incl. CSV fallback) |
| 2 | No file generated when `include_detail=true` and not approved | `include_detail=true` → `pending_approval`; the worker only processes `queued`; approve → `queued` → generation; reject → `rejected` (no file) | `tests/test_acceptance_2_approval_gate.py` (6 cases incl. role matrix + creator self-approval 403) |
| 3 | Each file's watermark number is unique and written to file attributes | `app/watermark.py` `WM-{YYYYMMDD}-{uuid8}` with DB-level collision guard (partial unique index); written to every sheet header row and workbook `properties.title`/`keywords` | `tests/test_acceptance_3_watermark.py` (4 cases incl. DB-level uniqueness) |
| 4 | Download link expires after 24 hours; each export has an audit record | HMAC-signed presigned links, TTL 86400s (env-overridable); expired → `410 EXPIRED` + regeneration hint; every event (requested/approved/rejected/succeeded/failed/link_issued) writes one `audit_log` row | `tests/test_acceptance_4_link_audit.py` (7 cases incl. tampered signature) |

Edge cases beyond the criteria live in `tests/test_edge_cases.py` (auth 401/403,
unknown panel/date 422, honest empty report, batch worker semantics, failure
recording).

## Run

### Option A — docker compose (PostgreSQL 16 + app)

```bash
docker compose up --build
# app on http://localhost:8801
docker compose exec app alembic upgrade head
docker compose exec app python scripts/seed.py   # fictional demo facts
```

### Option B — local PostgreSQL 16

```bash
python -m venv .venv && .venv/Scripts/activate      # Linux: source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+psycopg://postgres@127.0.0.1:5433/dash_exports_1855"
export STORAGE_DIR="./storage"
export LINK_SECRET="change-me"
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --host 127.0.0.1 --port 8801   # WORKER_ENABLED=true by default
```

### Tests (against a real PostgreSQL 16 — required, not sqlite)

```bash
# test database is created and migrated automatically; default DSN below
export TEST_DATABASE_URL="postgresql+psycopg://postgres@127.0.0.1:5433/dash_exports_1855_test"
pytest tests/ -v
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres@127.0.0.1:5433/dash_exports_1855` | PostgreSQL 16 DSN |
| `STORAGE_DIR` | `./storage` | Local object-storage root |
| `LINK_SECRET` | `dev-link-secret-change-me` | HMAC secret for presigned links |
| `LINK_TTL_SECONDS` | `86400` | Download link TTL (24h per brief) |
| `WORKER_ENABLED` | `true` | Start the in-process generation worker |
| `WORKER_POLL_SECONDS` | `2` | Worker poll interval |
| `TIMEZONE` | `Asia/Shanghai` | Data-end-time rendering timezone |
| `CALIBER_VERSION` | `v1.0` | Caliber version stamped on the Caliber sheet |

## Architecture

```
POST /api/dash/exports                 → dash_export row (queued | pending_approval)
     include_detail=true → pending_approval (no file until approve)
POST /api/dash/exports/{id}/approve    → ops_manager role required → queued
POST /api/dash/exports/{id}/reject     → rejected (never generates a file)
GET  /api/dash/exports/{id}            → status; when succeeded mints a fresh 24h
                                         presigned link + audit "export.link_issued"
GET  /files/{key}?expires&sig          → HMAC-validated download; 410 EXPIRED + hint
worker (DB queue, FOR UPDATE SKIP LOCKED) → watermark → XLSX/CSV → storage → succeeded
```

- **Worker**: database-backed queue (`SELECT ... FOR UPDATE SKIP LOCKED`) — safe
  for multiple app instances, deterministic in tests (`process_pending()`).
- **Storage**: `StorageAdapter` protocol with `LocalStorageAdapter` (disk +
  HMAC-signed URLs, behaviourally equivalent to S3 presigned URLs). Swapping in
  a real S3 client = implement `put/get/presign/verify`; callers never touch
  the filesystem. File keys contain a random UUID — not derivable from the
  export id sequence.
- **Identity stub**: `X-User-Id`/`X-Role` headers (S2-IAM boundary per brief);
  roles `analyst` / `ops_manager` / `admin`.
- **Unified columns**: every business table carries `id (UUID), org_id, site_id,
  created_at, created_by, updated_at, deleted_at`; amounts in integer cents.
- **No AI, no hand-written numbers**: every value in the report comes from the
  fact query; the caliber sheet is rendered from the registry.

## Verification records

Raw command outputs from a live run (PostgreSQL 16.9) are in
`verification/` — pytest run, walkthrough script output, and the audit table
dump quoted in the delivery body.
