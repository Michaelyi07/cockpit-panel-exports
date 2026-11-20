# Dash Exports — Cockpit Panel Export (S3-DASH-004)

Member Space Platform · Cockpit Panel Export: Caliber Page, Approval Gate & Watermark Numbers.

Async XLSX/CSV export service for cockpit panels with a caliber (metric
definition) worksheet, an operation-manager approval gate for detail-bearing
exports, unique watermark numbers (print headers + workbook file properties),
24-hour presigned download links, and full audit coverage of every export
event — running on PostgreSQL 16.

## Acceptance criteria → implementation → tests

| # | Acceptance criterion | Implementation | Tests |
|---|---|---|---|
| 1 | Exported XLSX contains a data sheet and a caliber worksheet with caliber instructions (metric code, definition, version, data end time, filter conditions) | `app/generator.py` builds "Panel Data" + "Caliber" sheets; caliber rows render from the metric registry (`app/panels.py`) with per-export data-end-time and filter echo | `tests/test_acceptance_1_xlsx_sheets.py` (5 cases incl. CSV fallback + CSV detail-after-approval) |
| 2 | Aggregate exports generate directly; detail-bearing exports (`include_detail=true`) only generate after ops-manager approval | `include_detail=true` → `pending_approval`; the worker only processes `queued`; approve → `queued` → generation (embeds a `Detail List` sheet with fictional enterprise/employee rows via `app/generator.py`); reject → `rejected` (no file). Aggregates-only files contain no detail sheet | `tests/test_acceptance_2_approval_gate.py` (8 cases incl. role matrix, creator self-approval 403, approved-file-has-detail-rows, aggregate-file-has-no-detail-sheet) |
| 3 | Each file's watermark number is unique and written to the print header and file attributes | `app/watermark.py` `WM-{YYYYMMDD}-{uuid8}` with global DB-level collision guard (partial unique index); written to every sheet's print header (`oddHeader`), the A1 banner (kept), and workbook `properties.title`/`keywords`; generator retries on collision with global scope | `tests/test_acceptance_3_watermark.py` (6 cases incl. print-header assertion, DB uniqueness, real retry-loop coverage) |
| 4 | Download link expires after 24 hours; each export has an audit record | HMAC-signed presigned links, TTL 86400s (env-overridable); expired → `410 EXPIRED` + regeneration hint; every event (requested/approved/rejected/succeeded/failed/link_issued) writes one `audit_log` row | `tests/test_acceptance_4_link_audit.py` (7 cases incl. tampered signature) |

Edge cases beyond the criteria live in `tests/test_edge_cases.py` (auth 401/403,
unknown panel/date/site_id 422, admin-not-approver, failed-not-reapprovable,
honest empty report, batch worker semantics, failure recording) and
`tests/test_config_secret.py` (LINK_SECRET startup guard). Total: 40 tests.

## Run

### Option A — docker compose (PostgreSQL 16 + app)

```bash
# secrets/env are mandatory — compose refuses to start without them
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"
export LINK_SECRET="$(openssl rand -hex 32)"
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
| `LINK_SECRET` | **(required — no default)** | HMAC secret for presigned links; the service refuses to start if unset (never falls back to a placeholder) |
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
  the filesystem. File keys are built as `dash-exports/{org_id}/{export_id}.{ext}`
  (see `app/worker.py`), i.e. they embed the export id — a UUID that is not
  guessable from any sequence.
- **Identity stub (S2-IAM)**: `X-User-Id`/`X-Role` headers stand in for the
  real identity service; roles `analyst` / `ops_manager` / `admin` (only
  `ops_manager` may approve/reject — `admin` is intentionally not an approver).
  To integrate,
  replace the `get_actor` dependency in `app/routes.py` with claims decoded
  from the platform token — the rest of the code only sees the
  `(user_id, role)` tuple, so no other module changes.
- **Audit stub (S2-AUDIT)**: `app/audit.py` defines `AuditSink.record(...)` and
  every export event (requested/approved/rejected/succeeded/failed/link_issued)
  calls `get_audit().record(...)` through that interface. To integrate the real
  audit service, implement `AuditSink.record` to forward the same event name and
  payload to S2-AUDIT (or replace the module-level `_sink` via a setter); the
  event names stay identical. The local sink currently writes one `audit_log`
  row per event as the mock.
- **Infra stub (S2-INFRA)**: object storage is the infra dependency —
  `app/storage.py` exposes the `StorageAdapter` protocol (`put/get/presign/verify`)
  with `LocalStorageAdapter` as the mock. To integrate S2-INFRA (e.g. real S3),
  implement the four methods and register it via `set_storage(adapter)`; callers
  never touch the filesystem. The presigned-URL semantics (HMAC + expiry) must be
  preserved.
- **Unified columns**: every business table carries `id (UUID), org_id, site_id,
  created_at, created_by, updated_at, deleted_at`; amounts in integer cents.
- **No AI, no hand-written numbers**: every value in the report comes from the
  fact query; the caliber sheet is rendered from the registry.

## Verification records

Raw command outputs from a live run (PostgreSQL 16.9) are in
`verification/` — pytest run, walkthrough script output, and the audit table
dump quoted in the delivery body. The authoritative, up-to-date pytest run is
`verification/pytest_raw_output_r3_5433.txt` (40 passed on PG 16.9, port 5433);
`pytest_raw_output.txt` is the pre-rework 29-test baseline and is kept only for
historical comparison.
