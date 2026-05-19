#!/usr/bin/env python3
"""Evaluate simple hand-written bin packing heuristics with the official EoH evaluator."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


BASELINES: dict[str, str] = {
    "first_fit": """import numpy as np

def score(item, bins):
    # Feasible bins arrive in original order, so favor the earliest one.
    scores = -np.arange(bins.shape[0], dtype=np.float64)
    return scores
""",
    "best_fit": """import numpy as np

def score(item, bins):
    after = bins - item
    # Higher score is better, so prefer the tightest feasible fit.
    return -after.astype(np.float64)
""",
    "worst_fit": """import numpy as np

def score(item, bins):
    after = bins - item
    # Prefer the roomiest feasible bin.
    return after.astype(np.float64)
""",
    "exact_fit_bonus": """import numpy as np

def score(item, bins):
    after = bins - item
    exact = (after == 0).astype(np.float64) * 1000.0
    # Strongly reward exact fits, otherwise prefer tighter fits.
    return exact - after.astype(np.float64)
""",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="results/official_baselines",
        help="Directory for CSV/JSON summaries.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from eoh.problems.optimization.bp_online.run import BPONLINE

    problem = BPONLINE()
    rows: list[dict[str, object]] = []
    for name, code in BASELINES.items():
        objective = problem.evaluate(code)
        rows.append(
            {
                "method": name,
                "objective": None if objective is None else round(float(objective), 5),
                "code": code,
            }
        )

    rows.sort(key=lambda row: float("inf") if row["objective"] is None else row["objective"])

    with (out_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "problem": "bp_online",
                "objective_definition": "average excess over the official lower bound; lower is better",
                "results": rows,
            },
            handle,
            indent=2,
        )

    with (out_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["method", "objective"])
        writer.writeheader()
        for row in rows:
            writer.writerow({"method": row["method"], "objective": row["objective"]})

    note = "\n".join(
        [
            f"Date: {datetime.utcnow().isoformat()}Z",
            "Command:",
            f"  ./.venv/bin/python scripts/evaluate_official_bp_baselines.py --output-dir {out_dir}",
            "Evaluator: official EoH bp_online evaluator",
            "Methods: " + ", ".join(BASELINES.keys()),
        ]
    )
    (out_dir / "experiment_note.md").write_text(note + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
