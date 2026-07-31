"""The extraction ledger: one entry per routing decision, the pipeline's flight recorder.

``area_escalated_pct`` is the system's first-class health metric: if it
creeps upward on a new document family, the deterministic layer is failing
and the thresholds need recalibration.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LedgerEntry(BaseModel):
    """What was decided for one page, what it cost, and why."""

    doc_id: str
    page: int = Field(ge=1)
    strategy_used: str
    coverage_residual: float = Field(ge=0.0, le=1.0)
    area_escalated_pct: float = Field(ge=0.0, le=100.0)
    table_sanity: bool | None = None
    cost_estimate_usd: float = Field(ge=0.0)
    processing_time_s: float = Field(ge=0.0)
