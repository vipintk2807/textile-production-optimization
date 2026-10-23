# Test and verification report

Only checks that were actually run are listed. Environment: Linux sandbox, **1 logical CPU**, Python 3.12.3,
OR-Tools 9.15.6755, Streamlit 1.66.0, pandas 3.0.2, pydantic 2.14.1, plotly 7.1.0, pytest 9.1.1, ruff 0.17.1.
**Not run on Windows.**

## Performed (in a clean extraction of the final ZIP, fresh virtual environment, `pip install -r requirements-dev.txt`)
| Check | Result |
|---|---|
| `python -m pytest` | **208 passed**, 1 deselected (performance test) |
| `python -m pytest -m performance` | 1 passed (29 s) |
| `python -m ruff check .` | All checks passed |
| `python -m ruff format --check .` | 63 files already formatted |
| `python -m streamlit run app.py --server.headless true` | `/_stcore/health` returned HTTP 200 `ok`; `/` returned 200; log directory created |
| `python scripts/run_benchmarks.py --limit 10` | Ran; see `docs/benchmark_results.md` (all returned schedules validated) |

## What the 208 tests cover
* **Unit:** field validation (invalid IDs, quantities, units, times, statuses, durations, self/duplicate predecessors), time conversion (no rounding, no time zones), half-open intervals, metrics against hand-derived values (completion, lateness, tardiness, weighted tardiness, makespan, utilization incl. zero-availability, changeover), fingerprint stability and sensitivity, all blocking input-validation rules.
* **Scheduling (real CP-SAT):** single/sequential/parallel operations, machine choice, machine-specific durations, precedence chains, release times, availability windows, boundary cases (end at window/horizon end), infeasible cases vs late-but-feasible, hard due dates, three objectives with hand-derived optima, changeovers, status mapping, real `MODEL_INVALID`, time-limit behaviour.
* **Validator:** VAL-01..VAL-17 corrupted/valid candidates plus hard due dates, objective claim mismatch, non-integer values.
* **Integration:** SQLite CRUD, restart persistence, referential integrity, delete policies, transaction rollback, backup, E2E-01..07 workflow (invalid input never reaches solver, infeasible, FEASIBLE labelling, stale detection, failed runs never overwrite the last validated schedule, persistence failure, CSV consistency, duplicate-run lock, sample data).
* **UI (Streamlit AppTest):** all pages render on empty and populated databases; app entry point launches; no solve on rerun, one run per click; Generate disabled on invalid inputs; stale banner and hidden metrics; order form validation and save.
* **Regression/cross-check:** 48 random tiny instances (makespan/tardiness, with and without changeovers) where the solver optimum equals an independent brute-force enumeration; table = Gantt = CSV for one run.

## Not tested / not verified
* **Windows** installation and CMD commands (instructions follow standard `venv`/`pip`/`streamlit` usage but were not executed on Windows).
* Python versions other than 3.12.3; dependency versions other than those pinned.
* Visual appearance in a real browser (no screenshots reviewed); accessibility/contrast beyond the chosen palette.
* Multi-worker solver behaviour and performance on your laptop (sandbox had 1 CPU).
* Real factory data, operational usefulness, and large instances beyond the benchmark table.
* Concurrent multi-user access.
