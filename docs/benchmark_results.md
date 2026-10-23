# Benchmark results (synthetic instances)

Produced by `python scripts/run_benchmarks.py --limit 10 --workers 1`. **Synthetic, artificially generated instances (fixed seed 42) run on the build sandbox - not factory data and not your computer.** The sandbox had a single logical CPU, so multi-worker behaviour was **not** measured. Re-run the script on your own laptop to obtain figures that apply to you.

Hardware/software: Linux-6.18.44-fc-v139-x86_64-with-glibc2.39, 1 logical CPUs, Python 3.12.3, OR-Tools 9.15.6755, solver workers=1, seed=1. SYNTHETIC instances.

| Objective | Orders | Ops | Machines | Precedences | Limit (s) | Status | Solve (s) | Validated | Objective | Best bound | Validation (s) | Total (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| makespan | 5 | 15 | 6 | 10 | 10.0 | OPTIMAL | 0.03 | True | 590 | 590.0 | 0.0002 | 0.03 |
| makespan | 10 | 30 | 6 | 20 | 10.0 | OPTIMAL | 3.18 | True | 1590 | 1590.0 | 0.0002 | 3.18 |
| makespan | 20 | 60 | 6 | 40 | 10.0 | FEASIBLE | 10.01 | True | 3262 | 684.0 | 0.0003 | 10.01 |
| makespan | 40 | 120 | 6 | 80 | 10.0 | FEASIBLE | 10.01 | True | 6297 | 1566.0 | 0.0006 | 10.01 |
| total_tardiness | 5 | 15 | 6 | 10 | 10.0 | OPTIMAL | 0.01 | True | 0 | 0.0 | 0.0001 | 0.01 |
| total_tardiness | 10 | 30 | 6 | 20 | 10.0 | FEASIBLE | 10.0 | True | 1406 | 0.0 | 0.0002 | 10.0 |
| total_tardiness | 20 | 60 | 6 | 40 | 10.0 | FEASIBLE | 10.01 | True | 34879 | 0.0 | 0.0003 | 10.01 |
| total_tardiness | 40 | 120 | 6 | 80 | 10.0 | FEASIBLE | 10.01 | True | 148365 | 799.0 | 0.0009 | 10.02 |


## What these numbers do and do not show

* Every returned schedule passed independent validation (column *Validated*).
* Small instances (5 orders / 15 operations) were solved to proven optimality in well under a second; 10 orders needed ~2.7 s for makespan.
* From about 20 orders / 60 operations (and from 10 orders for total tardiness) the solver stopped at the 10 s limit with status FEASIBLE: a validated schedule exists but the gap between objective and best bound is large, so **quality is unproven**. A longer time limit and more solver workers should help; this was not measured here.
* No maximum problem size, guaranteed runtime or real-world performance claim is made.
