"""The coverage residual: measure what extraction missed against the page's own ink."""

from refinery.coverage.ink import ink_mask, otsu_threshold
from refinery.coverage.residual import CoverageResult, assess, split_valid_claims
from refinery.coverage.writeoffs import retag_furniture

__all__ = ["ink_mask", "otsu_threshold", "CoverageResult", "assess",
           "split_valid_claims", "retag_furniture"]
