#!/usr/bin/env python3
"""Minimal online bin packing reproduction with simple evolutionary search."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from datetime import date
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


CAPACITY = 100


@dataclass
class Heuristic:
    name: str
    alpha: float
    beta: float
    gamma: float
    delta: float

    def score(self, item: int, remaining: int) -> float:
        after = remaining - item
        fit_ratio = item / remaining if remaining else 0.0
        exact_fit = 1.0 if after == 0 else 0.0
        slack_ratio = after / CAPACITY
        return (
            self.alpha * (-after)
            + self.beta * fit_ratio
            + self.gamma * exact_fit
            + self.delta * (-slack_ratio * slack_ratio)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--train-instances", type=int, default=8)
    parser.add_argument("--test-instances", type=int, default=8)
    parser.add_argument("--items-per-instance", type=int, default=80)
    parser.add_argument("--generations", type=int, default=4)
    parser.add_argument("--population-size", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output-dir", default="results/minimal_repro")
    return parser.parse_args()


def generate_instance(rng: random.Random, n_items: int) -> list[int]:
    choices = []
    for _ in range(n_items):
        p = rng.random()
        if p < 0.50:
            value = int(round(min(95, max(5, rng.gauss(48, 12)))))
        elif p < 0.80:
            value = rng.randint(15, 70)
        else:
            value = rng.randint(1, 99)
        choices.append(value)
    return choices


def generate_dataset(seed: int, n_instances: int, n_items: int) -> list[list[int]]:
    rng = random.Random(seed)
    return [generate_instance(rng, n_items) for _ in range(n_instances)]


def lower_bound(items: list[int]) -> int:
    return math.ceil(sum(items) / CAPACITY)


def pack_with_scores(items: list[int], scorer: Callable[[int, int], float]) -> int:
    bins: list[int] = []
    for item in items:
        best_idx = None
        best_score = None
        for idx, remaining in enumerate(bins):
            if remaining >= item:
                score = scorer(item, remaining)
                if best_score is None or score > best_score:
                    best_score = score
                    best_idx = idx
        if best_idx is None:
            bins.append(CAPACITY - item)
        else:
            bins[best_idx] -= item
    return len(bins)


def first_fit(items: list[int]) -> int:
    bins: list[int] = []
    for item in items:
        placed = False
        for idx, remaining in enumerate(bins):
            if remaining >= item:
                bins[idx] -= item
                placed = True
                break
        if not placed:
            bins.append(CAPACITY - item)
    return len(bins)


def best_fit(items: list[int]) -> int:
    bins: list[int] = []
    for item in items:
        best_idx = None
        best_after = None
        for idx, remaining in enumerate(bins):
            if remaining >= item:
                after = remaining - item
                if best_after is None or after < best_after:
                    best_after = after
                    best_idx = idx
        if best_idx is None:
            bins.append(CAPACITY - item)
        else:
            bins[best_idx] -= item
    return len(bins)


def first_fit_decreasing(items: list[int]) -> int:
    return first_fit(sorted(items, reverse=True))


def evaluate_dataset(dataset: list[list[int]], packer: Callable[[list[int]], int]) -> dict[str, float]:
    bins_used = [packer(instance) for instance in dataset]
    lbs = [lower_bound(instance) for instance in dataset]
    mean_bins = sum(bins_used) / len(bins_used)
    mean_lb = sum(lbs) / len(lbs)
    mean_excess = sum((b - lb) / lb for b, lb in zip(bins_used, lbs)) / len(bins_used)
    return {
        "avg_bins": mean_bins,
        "avg_lb": mean_lb,
        "avg_excess": mean_excess,
    }


def heuristic_packer(heuristic: Heuristic) -> Callable[[list[int]], int]:
    return lambda items: pack_with_scores(items, heuristic.score)


def mutate(parent: Heuristic, rng: random.Random, child_id: int) -> Heuristic:
    scale = 0.7
    return Heuristic(
        name=f"mut_{child_id}",
        alpha=parent.alpha + rng.uniform(-scale, scale),
        beta=parent.beta + rng.uniform(-scale, scale),
        gamma=parent.gamma + rng.uniform(-1.5, 1.5),
        delta=parent.delta + rng.uniform(-scale, scale),
    )


def seed_population() -> list[Heuristic]:
    return [
        Heuristic("seed_best_fitish", 1.0, 0.8, 0.6, 0.2),
        Heuristic("seed_balance", 0.7, 0.4, 1.1, 0.4),
        Heuristic("seed_exact_fit_bonus", 0.5, 0.3, 1.8, 0.1),
        Heuristic("seed_compact", 1.2, 0.2, 0.2, 0.8),
    ]


def summarize_heuristic(heuristic: Heuristic) -> str:
    return (
        f"score = {heuristic.alpha:.3f}*(-after)"
        f" + {heuristic.beta:.3f}*fit_ratio"
        f" + {heuristic.gamma:.3f}*exact_fit"
        f" + {heuristic.delta:.3f}*(-slack_ratio^2)"
    )


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    train_data = generate_dataset(args.seed, args.train_instances, args.items_per_instance)
    test_data = generate_dataset(args.seed + 1, args.test_instances, args.items_per_instance)

    baseline_rows = []
    baselines = {
        "First Fit": first_fit,
        "Best Fit": best_fit,
        "First Fit Decreasing": first_fit_decreasing,
    }
    for name, fn in baselines.items():
        metrics = evaluate_dataset(test_data, fn)
        baseline_rows.append({"method": name, **metrics})

    population = seed_population()
    while len(population) < args.population_size:
        population.append(mutate(random.choice(population), rng, len(population)))

    history = []
    next_id = len(population)
    best = None
    best_score = None

    for generation in range(args.generations):
        scored = []
        for heuristic in population:
            metrics = evaluate_dataset(train_data, heuristic_packer(heuristic))
            scored.append((metrics["avg_excess"], heuristic, metrics))
        scored.sort(key=lambda row: row[0])

        generation_best = scored[0]
        history.append(
            {
                "generation": generation,
                "train_avg_excess": generation_best[0],
                "heuristic": asdict(generation_best[1]),
                "formula": summarize_heuristic(generation_best[1]),
            }
        )
        if best_score is None or generation_best[0] < best_score:
            best_score = generation_best[0]
            best = generation_best[1]

        parents = [row[1] for row in scored[: args.top_k]]
        children = list(parents)
        while len(children) < args.population_size:
            parent = rng.choice(parents)
            children.append(mutate(parent, rng, next_id))
            next_id += 1
        population = children

    assert best is not None

    final_methods = baseline_rows[:]
    evolved_metrics = evaluate_dataset(test_data, heuristic_packer(best))
    final_methods.append(
        {
            "method": f"Evolved heuristic ({best.name})",
            **evolved_metrics,
        }
    )

    with (out_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "seed": args.seed,
                "capacity": CAPACITY,
                "train_instances": args.train_instances,
                "test_instances": args.test_instances,
                "items_per_instance": args.items_per_instance,
                "generations": args.generations,
                "population_size": args.population_size,
                "best_heuristic": asdict(best),
                "best_formula": summarize_heuristic(best),
                "history": history,
                "results": final_methods,
            },
            handle,
            indent=2,
        )

    with (out_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["method", "avg_bins", "avg_lb", "avg_excess"])
        writer.writeheader()
        writer.writerows(final_methods)

    with (out_dir / "experiment_note.md").open("w", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    f"Date: {date.today().isoformat()}",
                    f"Command: python scripts/minimal_bp_repro.py --seed {args.seed} --generations {args.generations} --population-size {args.population_size}",
                    "Model used: none (manual seeds + numeric mutation)",
                    f"Parameters: train_instances={args.train_instances}, test_instances={args.test_instances}, items_per_instance={args.items_per_instance}",
                    f"Best heuristic: {best.name}",
                    f"Formula: {summarize_heuristic(best)}",
                    f"Result: avg_excess={evolved_metrics['avg_excess']:.4f} on test set",
                    "",
                ]
            ),
        )

    print(json.dumps({"output_dir": str(out_dir), "best_formula": summarize_heuristic(best), "results": final_methods}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
