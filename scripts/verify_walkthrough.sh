#!/usr/bin/env bash
# Reproducible verification walkthrough for 【S3-DASH-004】(must run against a
# real PostgreSQL 16 database — see README "Run" section for environment setup).
# Every command prints raw output; the delivery body quotes these verbatim.
set -euo pipefail

PSQL="${PSQL:-psql}"

BASE="${BASE:-http://127.0.0.1:8801}"
ANALYST=(-H "X-User-Id: analyst-1" -H "X-Role: analyst" -H "Content-Type: application/json")
MANAGER=(-H "X-User-Id: manager-1" -H "X-Role: ops_manager" -H "Content-Type: application/json")

echo "== 0. service + database version =="
"$PSQL" --version
"$PSQL" -h 127.0.0.1 -p 5433 -U postgres -d dash_exports_1855 -t -c "SELECT version();"

echo "== 1. aggregate export: XLSX with Panel Data + Caliber sheets (C1) =="
CREATE1=$(curl -s -X POST "$BASE/api/dash/exports" "${ANALYST[@]}" \
  -d '{"panel":"occupancy","filters":{"site_id":"00000000-0000-0000-0000-000000000001","date_from":"2026-11-01","date_to":"2026-12-31"}}')
echo "$CREATE1"
EID1=$(echo "$CREATE1" | python -c "import json,sys; print(json.load(sys.stdin)['id'])")
sleep 4   # background worker generates
DETAIL1=$(curl -s "$BASE/api/dash/exports/$EID1" "${ANALYST[@]}")
echo "$DETAIL1"
URL1=$(echo "$DETAIL1" | python -c "import json,sys; print(json.load(sys.stdin)['download_url'])")

echo "== 2. watermark uniqueness + file attributes (C3) =="
CREATE2=$(curl -s -X POST "$BASE/api/dash/exports" "${ANALYST[@]}" \
  -d '{"panel":"revenue","filters":{"site_id":"00000000-0000-0000-0000-000000000001"}}')
EID2=$(echo "$CREATE2" | python -c "import json,sys; print(json.load(sys.stdin)['id'])")
sleep 4
DETAIL2=$(curl -s "$BASE/api/dash/exports/$EID2" "${ANALYST[@]}")
URL2=$(echo "$DETAIL2" | python -c "import json,sys; print(json.load(sys.stdin)['download_url'])")
curl -s "$BASE$URL1" -o /tmp/export1.xlsx && curl -s "$BASE$URL2" -o /tmp/export2.xlsx
python - <<'PY'
from openpyxl import load_workbook
w1 = load_workbook("/tmp/export1.xlsx"); w2 = load_workbook("/tmp/export2.xlsx")
wm1, wm2 = w1.properties.title, w2.properties.title
print("watermark1 =", wm1); print("watermark2 =", wm2)
print("unique:", wm1 != wm2)
print("sheets:", w1.sheetnames)
print("header A1:", w1["Panel Data"].cell(row=1, column=1).value)
print("caliber row:", [w1["Caliber"].cell(row=3, column=c).value for c in range(1, 6)])
PY

echo "== 3. detail export: unapproved generates NO file (C2) =="
CREATE3=$(curl -s -X POST "$BASE/api/dash/exports" "${ANALYST[@]}" \
  -d '{"panel":"revenue","include_detail":true,"filters":{"site_id":"00000000-0000-0000-0000-000000000001"}}')
echo "$CREATE3"
EID3=$(echo "$CREATE3" | python -c "import json,sys; print(json.load(sys.stdin)['id'])")
sleep 4
curl -s "$BASE/api/dash/exports/$EID3" "${ANALYST[@]}"
echo "(status stays pending_approval; file_key null)"

echo "== 4. analyst approval attempt -> 403; manager approves -> queued (C2) =="
curl -s -o /dev/null -w "analyst approve http_code=%{http_code}\n" \
  -X POST "$BASE/api/dash/exports/$EID3/approve" "${ANALYST[@]}"
curl -s -X POST "$BASE/api/dash/exports/$EID3/approve" "${MANAGER[@]}"
sleep 4
curl -s "$BASE/api/dash/exports/$EID3" "${ANALYST[@]}"

echo "== 5. link TTL 24h + audit per issuance (C4) =="
curl -s "$BASE/api/dash/exports/$EID1" "${ANALYST[@]}" | python -c "
import json, sys, time
d = json.load(sys.stdin)
q = d['download_url'].split('expires=')[1].split('&')[0]
print('ttl_seconds =', int(q) - int(time.time()))
"
"$PSQL" -h 127.0.0.1 -p 5433 -U postgres -d dash_exports_1855 -c \
  "SELECT action, count(*) FROM audit_log WHERE resource_id='$EID1' GROUP BY action ORDER BY action;"

echo "== 6. audit rows for export 1 (requested/succeeded/link_issued) =="
"$PSQL" -h 127.0.0.1 -p 5433 -U postgres -d dash_exports_1855 -c \
  "SELECT action, count(*) FROM audit_log WHERE resource_id='$EID1' GROUP BY action ORDER BY action;"

echo "== done: all raw outputs above are quoted verbatim in the delivery body =="
