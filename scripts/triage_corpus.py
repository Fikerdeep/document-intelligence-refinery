"""Run triage over every PDF in a folder and print the classification summary.

Usage:
    python scripts/triage_corpus.py --corpus <dir> [--rules rubric/extraction_rules.yaml]
                                    [--out .refinery/profiles] [--exclude name.pdf ...]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refinery.config import load_rules
from refinery.triage import profile_document, save_profile


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--rules", default="rubric/extraction_rules.yaml")
    ap.add_argument("--out", default=".refinery/profiles")
    ap.add_argument("--exclude", nargs="*", default=[])
    args = ap.parse_args()

    rules = load_rules(args.rules)
    origins, rungs, langs = Counter(), Counter(), Counter()
    for pdf in sorted(args.corpus.glob("*.pdf")):
        if pdf.name in set(args.exclude):
            continue
        try:
            profile = profile_document(pdf, rules)
        except Exception as err:
            print(f"ERROR  {pdf.name}: {err}", file=sys.stderr)
            continue
        save_profile(profile, args.out)
        for page in profile.pages:
            origins[page.origin_type.value] += 1
            rungs[page.recommended_rung.value] += 1
            langs[page.language] += 1
        print(f"{profile.dominant_origin.value:15s} {pdf.name}")

    print(f"\npages by origin: {dict(origins)}")
    print(f"pages by rung:   {dict(rungs)}")
    print(f"pages by lang:   {dict(langs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
