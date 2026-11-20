"""Pydantic request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .panels import KNOWN_PANELS


class ExportCreate(BaseModel):
    panel: Literal[tuple(KNOWN_PANELS)]  # type: ignore[valid-type]
    filters: dict = Field(default_factory=dict)
    include_detail: bool = False
    export_format: Literal["xlsx", "csv"] = "xlsx"

    @model_validator(mode="after")
    def _validate_filters(self):
        f = self.filters or {}
        for key in ("date_from", "date_to"):
            if key in f and not _valid_date(f[key]):
                raise ValueError(f"filters.{key} must be YYYY-MM-DD")
        return self


def _valid_date(value) -> bool:
    try:
        datetime.strptime(str(value), "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


class RejectCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class ExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    panel: str
    filters: dict
    include_detail: bool
    export_format: str
    status: str
    watermark: str | None = None
    file_key: str | None = None
    approved_by: str | None = None
    error: str | None = None
    created_at: datetime


class ExportDetailOut(ExportOut):
    download_url: str | None = None
    link_expires_at: datetime | None = None
