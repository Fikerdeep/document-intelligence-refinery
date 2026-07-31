"""Pure grid math shared by coverage and extraction.

The pipeline compares page content on a coarse boolean grid. This module
owns the two primitives: projecting rectangles onto a grid, and finding
connected regions of a grid mask back in page coordinates. Boxes are always
mapped through the grid's actual shape, never through a nominal cell size —
rounding drift between the two once faked a coverage collapse.
"""

from __future__ import annotations

import numpy as np


def boxes_mask(shape: tuple[int, int], boxes: list[tuple[float, float, float, float]],
               page_width: float, page_height: float) -> np.ndarray:
    """Project (x0, y0, x1, y1) page-point boxes onto a boolean grid of ``shape``."""
    mask = np.zeros(shape, dtype=bool)
    if page_width <= 0 or page_height <= 0:
        return mask
    rows, cols = shape
    for x0, y0, x1, y1 in boxes:
        r0 = max(0, int(y0 / page_height * rows))
        r1 = min(rows, int(np.ceil(y1 / page_height * rows)))
        c0 = max(0, int(x0 / page_width * cols))
        c1 = min(cols, int(np.ceil(x1 / page_width * cols)))
        if r1 > r0 and c1 > c0:
            mask[r0:r1, c0:c1] = True
    return mask


def connected_regions(mask: np.ndarray, page_width: float, page_height: float,
                      min_area_pt2: float) -> list[tuple[float, float, float, float]]:
    """Bounding boxes (page points) of 4-connected components above ``min_area_pt2``."""
    rows, cols = mask.shape
    cell_w, cell_h = page_width / cols, page_height / rows
    labels = np.zeros(mask.shape, dtype=np.int32)
    regions = []
    current = 0
    for r in range(rows):
        for c in range(cols):
            if not mask[r, c] or labels[r, c]:
                continue
            current += 1
            stack = [(r, c)]
            labels[r, c] = current
            r_min, r_max, c_min, c_max, cells = r, r, c, c, 0
            while stack:
                rr, cc = stack.pop()
                cells += 1
                r_min, r_max = min(r_min, rr), max(r_max, rr)
                c_min, c_max = min(c_min, cc), max(c_max, cc)
                for nr, nc in ((rr-1, cc), (rr+1, cc), (rr, cc-1), (rr, cc+1)):
                    if 0 <= nr < rows and 0 <= nc < cols and mask[nr, nc] and not labels[nr, nc]:
                        labels[nr, nc] = current
                        stack.append((nr, nc))
            if cells * cell_w * cell_h >= min_area_pt2:
                regions.append((c_min * cell_w, r_min * cell_h,
                                (c_max + 1) * cell_w, (r_max + 1) * cell_h))
    return regions
