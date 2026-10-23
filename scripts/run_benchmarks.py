"""Synthetic scheduling benchmarks (all instances are artificial, generated from a fixed seed).

Usage (from the project root, virtual environment active):
    python scripts/run_benchmarks.py            # prints a Markdown table
    python scripts/run_benchmarks.py --limit 10 # per-instance solver time limit in seconds

The numbers describe THIS computer and THESE synthetic instances only. They are not factory
measurements and do not establish a maximum problem size.
"""

from __future__ import annotations

import argparse
import os
import platform
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ortools  # noqa: E402

from textile_optimizer.domain.snapshot import (  # noqa: E402
    MachineSpec,
    OperationSpec,
    OrderSpec,
    ProblemSnapshot,
)
from textile_optimizer.reporting.metrics import schedule_metrics  # noqa: E402
from textile_optimizer.scheduling.solver import SolverConfig, solve  # noqa: E402
from textile_optimizer.validation.schedule_validator import validate_schedule  # noqa: E402

SIZES = (5, 10, 20, 40)


def generate(n_orders: int, objective: str, seed: int = 42) -> ProblemSnapshot:
    """n orders x 3 chained operations; 3 stages with 2 machines each; 12 h/day calendars."""
    rng = random.Random(seed)
    day, shift, days = 1440, 720, 12
    windows = tuple((d * day, d * day + shift) for d in range(days))
    machines = tuple(MachineSpec(f"S{s}-M{k}", windows) for s in range(3) for k in range(2))
    orders, ops = [], []
    for i in range(n_orders):
        orders.append(
            OrderSpec(
                f"O{i:03d}", rng.choice([0, 0, 240]), rng.randint(600, 600 + 40 * n_orders), rng.randint(1, 5)
            )
        )
        prev = None
        for s in range(3):
            options = tuple(sorted((f"S{s}-M{k}", rng.randint(60, 240)) for k in range(2)))
            oid = f"O{i:03d}-{s}"
            ops.append(OperationSpec(oid, f"O{i:03d}", (prev,) if prev else (), options, None))
            prev = oid
    return ProblemSnapshot(
        day * days, objective, False, False, "2026-01-05T08:00:00", tuple(orders), machines, tuple(ops)
    )


def run(limit: float, workers: int) -> list[dict]:
    rows = []
    for objective in ("makespan", "total_tardiness"):
        for n in SIZES:
            snap = generate(n, objective)
            t0 = time.perf_counter()
            res = solve(snap, SolverConfig(limit, workers, 1))
            t_solve = time.perf_counter() - t0
            valid, t_val, obj = False, 0.0, None
            if res.candidate is not None:
                t1 = time.perf_counter()
                valid = validate_schedule(snap, res.candidate).passed
                t_val = time.perf_counter() - t1
                obj = schedule_metrics(snap, res.candidate.assignments)["objective_value"]
            rows.append(
                {
                    "objective": objective,
                    "orders": n,
                    "operations": len(snap.operations),
                    "machines": len(snap.machines),
                    "precedences": sum(len(o.predecessors) for o in snap.operations),
                    "limit": limit,
                    "status": res.status.value,
                    "solve_s": round(t_solve, 2),
                    "validated": valid,
                    "objective_value": obj,
                    "best_bound": None if res.best_bound is None else round(res.best_bound, 1),
                    "validation_s": round(t_val, 4),
                    "total_s": round(t_solve + t_val, 2),
                }
            )
    return rows


def to_markdown(rows: list[dict], workers: int) -> str:
    head = (
        "| Objective | Orders | Ops | Machines | Precedences | Limit (s) | Status | Solve (s) | Validated | "
        "Objective | Best bound | Validation (s) | Total (s) |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    body = "".join(
        f"| {r['objective']} | {r['orders']} | {r['operations']} | {r['machines']} | {r['precedences']} | {r['limit']} | "
        f"{r['status']} | {r['solve_s']} | {r['validated']} | {r['objective_value']} | {r['best_bound']} | "
        f"{r['validation_s']} | {r['total_s']} |\n"
        for r in rows
    )
    ctx = (
        f"Hardware/software: {platform.platform()}, {os.cpu_count()} logical CPUs, Python {platform.python_version()}, "
        f"OR-Tools {ortools.__version__}, solver workers={workers}, seed=1. SYNTHETIC instances.\n\n"
    )
    return ctx + head + body


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    print(to_markdown(run(args.limit, args.workers), args.workers))
