"""Materialise the corpus split defined in corpus_manifest.yaml as directories.

The manifest is the authority on the split but names only holdout, oos and
dropped; tune is the remainder of the source folder. Files are copied, never
moved or symlinked, so the source folder stays intact and a corrupted working
copy can never damage the original.

Usage:
    python scripts/build_corpus.py [--source ~/Downloads/data] [--oos-source docs]
                                   [--manifest corpus_manifest.yaml] [--dest corpus]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml


def load_split(manifest: Path) -> tuple[set[str], set[str], set[str]]:
    """Read the manifest's three named lists as sets of file names."""
    data = yaml.safe_load(manifest.read_text())
    return (set(data.get("holdout") or []),
            set(data.get("oos") or []),
            set(data.get("dropped") or []))


def copy_into(names: list[Path], destination: Path) -> int:
    """Copy each file into destination, creating it, and return the count."""
    destination.mkdir(parents=True, exist_ok=True)
    for path in names:
        shutil.copy2(path, destination / path.name)
    return len(names)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path.home() / "Downloads" / "data")
    ap.add_argument("--oos-source", type=Path, default=Path("docs"))
    ap.add_argument("--manifest", type=Path, default=Path("corpus_manifest.yaml"))
    ap.add_argument("--dest", type=Path, default=Path("corpus"))
    args = ap.parse_args()

    holdout, oos, dropped = load_split(args.manifest)
    available = {p.name: p for p in sorted(args.source.glob("*.pdf"))}

    missing = (holdout | dropped) - set(available)
    if missing:
        for name in sorted(missing):
            print(f"MISSING from source: {name}", file=sys.stderr)

    tune_files = [p for name, p in available.items()
                  if name not in holdout and name not in dropped]
    holdout_files = [available[name] for name in sorted(holdout & set(available))]

    oos_available = {p.name: p for p in sorted(args.oos_source.glob("*.pdf"))}
    oos_files = [oos_available[name] for name in sorted(oos & set(oos_available))]
    for name in sorted(oos - set(oos_available)):
        print(f"MISSING from oos-source: {name}", file=sys.stderr)

    n_tune = copy_into(tune_files, args.dest / "tune")
    n_holdout = copy_into(holdout_files, args.dest / "holdout")
    n_oos = copy_into(oos_files, args.dest / "oos")

    print(f"source:   {args.source} ({len(available)} pdfs)")
    print(f"tune:     {n_tune}")
    print(f"holdout:  {n_holdout}")
    print(f"oos:      {n_oos}")
    print(f"skipped:  {len(dropped & set(available))} dropped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
