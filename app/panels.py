"""Metric registry (caliber) + panel definitions.

Each metric carries its caliber: definition text and version. The Caliber sheet
is rendered from this registry so numbers on the data sheet are always
self-documenting. Data end time is computed per export from the fact rows.
"""
from __future__ import annotations

PANEL_METRICS: dict[str, list[dict]] = {
    "occupancy": [
        {"code": "rentable_workstations", "definition": "Rentable workstations on record for the site/floor filter (shared spaces excluded)"},
        {"code": "leased_workstations", "definition": "Workstations under active lease at period end"},
        {"code": "occ_rate", "definition": "leased_workstations / rentable_workstations, 0 when denominator is 0"},
    ],
    "revenue": [
        {"code": "signed_value_cents", "definition": "Sum of signed contract amounts (integer cents, first-year basis)"},
        {"code": "contracts_signed", "definition": "Count of contracts whose signing date falls in the period"},
    ],
    "leads": [
        {"code": "leads_new", "definition": "Leads created within the period"},
        {"code": "leads_qualified", "definition": "Leads that reached the qualified stage within the period"},
    ],
}

# Aggregation mode per metric: "sum_cents", "sum_num", "avg_num"
METRIC_MODE: dict[str, str] = {
    "rentable_workstations": "sum_num",
    "leased_workstations": "sum_num",
    "occ_rate": "avg_num",
    "signed_value_cents": "sum_cents",
    "contracts_signed": "sum_num",
    "leads_new": "sum_num",
    "leads_qualified": "sum_num",
}

KNOWN_PANELS = tuple(PANEL_METRICS.keys())
