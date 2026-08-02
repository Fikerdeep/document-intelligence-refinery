"""Typed access to rubric/extraction_rules.yaml.

Thresholds live in the YAML with their evidence; code receives them through
these models and never hardcodes a number. Unknown YAML sections pass
through untyped so config can grow ahead of code.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class MeasurementRules(BaseModel):
    """Rasterization and coverage-grid parameters."""

    raster_dpi: int
    cell_pt: float
    ink_cell_min_frac: float


class LayoutRules(BaseModel):
    """Heuristic constants for layout classification."""

    min_ruled_lines: int
    figure_min_image_ratio: float
    column_bin_pt: float
    column_min_share: float
    column_min_separation_pt: float


class TriageRules(BaseModel):
    """Origin-type gate, layout constants, and domain keyword lists."""

    scanned_max_density: float
    scanned_min_image_ratio: float
    native_min_density: float
    native_max_image_ratio: float
    layout: LayoutRules
    domain_keywords: dict[str, list[str]]


class RoutingRules(BaseModel):
    """Which extraction rung each origin type starts at, and how rung
    overlap resolves: a vision table overlapping a sane deterministic table
    by at least ``table_overlap_ratio`` of the smaller box stays out."""

    start_rung: dict[str, str]
    table_overlap_ratio: float = 0.5
    route_top_k: int = 3


class CoverageRules(BaseModel):
    """Escalation threshold and residual guards."""

    tau: float
    max_element_area_ratio: float
    min_region_area_pt2: float


class BudgetRules(BaseModel):
    """Hard caps on paid extraction."""

    max_vlm_usd_per_doc: float
    vlm_crop_dpi: int


class EmbeddingRules(BaseModel):
    """Embedding endpoint settings; the hash fallback engages when no key exists."""

    base_url: str
    model: str
    api_key_env: str
    dim: int


class VisionRules(BaseModel):
    """VLM endpoint settings; the key lives in the environment."""

    provider: str = "anthropic"
    base_url: str
    model: str
    api_key_env: str
    price_per_mtok_input: float
    price_per_mtok_output: float


class WriteoffRules(BaseModel):
    """Recurring-furniture detection and per-family manual overrides."""

    furniture_repeat_ratio: float
    manual: list = Field(default_factory=list)


class Rules(BaseModel):
    """The full rule set, one attribute per YAML section."""

    measurement: MeasurementRules
    triage: TriageRules
    routing: RoutingRules
    coverage: CoverageRules
    budget: BudgetRules
    vision: VisionRules
    embeddings: EmbeddingRules
    writeoffs: WriteoffRules
    chunking: dict = Field(default_factory=dict)


def load_rules(path: Path | str = "rubric/extraction_rules.yaml") -> Rules:
    """Parse and validate the rules file."""
    with open(path) as f:
        return Rules.model_validate(yaml.safe_load(f))
