# Textile Production Optimization

A local, open-source **production scheduling and decision-support tool** for textile manufacturers.
It turns orders, operations, machines, calendars, due dates and changeover rules into a
constraint-based schedule using **Google OR-Tools CP-SAT**, then **independently validates** the
result before accepting it. Built with Python, Streamlit, SQLite, Pydantic, Plotly and pytest.

> **Status: initial development release (0.1.0).** It runs locally without paid services or a GPU.
> It has only been tested with **synthetic data** and **has not been tested on Windows or on real
> factory data** (see [Verification status](#verification-status)). A schedule produced here is a
> validated solution of the *configured model*, not a guarantee of factory-floor feasibility or of
> improved production performance.

## What is implemented

* **Data management** (SQLite): production orders, machines (capabilities, availability windows,
  downtime), operations (durations, eligible machines with optional machine-specific durations,
  predecessors, changeover category), changeover matrix and settings. Full validation, referential
  integrity, confirmed deletes, backup via SQLite's online backup API.
* **Scheduling** (CP-SAT): machine assignment, finish-to-start precedence, single-capacity machines
  (no overlap), release times, availability windows + downtime (non-preemptive), planning horizon,
  optional sequence-dependent changeovers, optional hard due dates.
  Objectives (one per run): **minimize makespan**, **total tardiness** or **weighted total tardiness**.
* **Honest solver outcomes**: OPTIMAL, FEASIBLE (optimality *not* proven), INFEASIBLE, UNKNOWN
  (no solution / not proven infeasible), MODEL_INVALID, plus *validation failed* and *error*.
* **Independent schedule validator** that shares no code with the model builder (17 corruption
  cases tested). Only validated candidates are accepted; metrics exist only for accepted schedules.
* **Traceability**: every run stores its full input snapshot, SHA-256 input fingerprint, solver/model
  versions, objective, time limit, workers, seed, status, bound and validation result. Schedules
  become **stale** when scheduling-relevant data or the objective change; old runs stay available.
* **UI** (6 pages): Dashboard, Production Orders, Machines, Operations, Schedule (settings, input
  validation, explicit *Generate Schedule*, Gantt timeline, table), Reports (order performance,
  utilization, summary, baseline comparison, run history), CSV exports.
* **Baseline**: deterministic EDD list-scheduling baseline for comparison on identical data.
* **Synthetic sample dataset** (clearly labelled, loads only into an empty database).

## Requirements

* Windows 10/11 (Linux/macOS also work), **Python 3.12 (64-bit)** recommended
  (Python >= 3.11 is required by the pinned pandas; 3.12.3 was the tested version).
* Internet access once, to download packages from PyPI. No paid API, account, cloud or GPU.

## Windows installation and run (Command Prompt)

```bat
cd path\to\textile-production-optimization
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m streamlit run app.py
```

If `py -3.12` is not found, install Python from python.org (tick *Add python.exe to PATH*) or use
`py -m venv .venv`. The app opens at **http://localhost:8501** (bound to localhost only).
The SQLite database is created automatically at `data\textile_optimizer.db` on first start
(existing data is never reset). Stop the app with `Ctrl+C`.

### First steps in the app

1. **Dashboard -> Data management -> Load synthetic sample data** (empty database only), or enter your own data in this order:
   **Machines** (capabilities + availability windows) -> **Production Orders** (status `ready`) -> **Operations** -> **Schedule**.
2. **Schedule -> Scheduling settings**: planning origin (minute 0), horizon end, objective, time limit. Optionally enable changeovers and fill the changeover matrix.
3. **Validate Inputs**, then **Generate Schedule**. Inspect status badges, Gantt timeline and table.
4. **Reports** for tardiness, utilization, baseline comparison and CSV downloads.

All times are **whole minutes from the planning origin**; the UI shows the calendar equivalent.

### Running the checks

```bat
pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m pytest -m performance
python scripts\run_benchmarks.py --limit 10
```

## Reading the results

| Label | Meaning |
|---|---|
| **Optimal** | Solver proved the optimum of the configured objective for the encoded model. |
| **Feasible** | A valid schedule was found but optimality was **not** proven (typically the time limit stopped the search). Gap = objective vs best bound. |
| **Infeasible** | Proven: no schedule satisfies all encoded hard constraints *for this horizon*. Different from a feasible schedule with late orders (due dates are soft unless you enforce them). |
| **Time limit reached - no solution** | Nothing found in time; this is **not** proof of infeasibility. |
| **Validation failed** | The solver returned a candidate but the independent validator rejected it; it is not an accepted schedule. |
| **Solver error / invalid model** | A technical failure, not a production conclusion. |
| **Out of date (stale)** | Inputs/settings changed after the run; its metrics are historical. |

Metrics: tardiness `T = max(0, C - due)`; makespan = latest end; utilization `U = processing / available x 100 %`
within the horizon (changeover time excluded; shown as *unavailable* when available time is 0).

## Project layout

```
app.py                       Streamlit entry point (navigation)
src/textile_optimizer/
  domain/                    Pydantic records, immutable snapshot + fingerprint, intervals, time, graph
  validation/                input_validation.py (pre-solver), schedule_validator.py (independent)
  scheduling/                model_builder.py, solver.py, baseline.py
  persistence/               schema.py, db.py, repository.py (SQLite, parameterised SQL)
  services/                  planning_service.py (workflow), sample_data.py (SYNTHETIC)
  reporting/                 metrics.py, export.py (CSV)
  ui/                        components, gantt, run_view, pages/*
tests/                       unit, scheduling, validation, integration, ui, regression, performance
scripts/run_benchmarks.py    synthetic benchmark generator
docs/                        assumptions, test report, benchmarks, GitHub publishing
```

## Data, backup and maintenance

* Database: `data\textile_optimizer.db` (override with `TPO_DB_PATH` / `TPO_DATA_DIR`). Logs: `data\logs\app.log`.
* Backup: Dashboard -> Data management -> *Create database backup* (SQLite online backup to `data\backups\`).
  Do not copy the `.db` file while the app is writing. `data/` contents are git-ignored.
* Schema version is stored in `PRAGMA user_version`; add migrations in `persistence/db.py::migrate` when changing the schema.
* After upgrading any dependency, run the full test suite and `python scripts\run_benchmarks.py`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `py` / `python` not recognised | Install Python 3.12 and tick *Add to PATH*, reopen CMD. |
| `.venv\Scripts\activate` blocked | You are in PowerShell; use CMD, or run `.venv\Scripts\activate.bat`. |
| `pip install` fails for ortools | Use 64-bit Python 3.11-3.12; update pip; check internet/proxy. |
| Port 8501 busy | `python -m streamlit run app.py --server.port 8502` |
| "Blocking errors" on Schedule page | Read the listed messages (missing machine, availability, predecessors, weights, transitions...). |
| Result `Infeasible` | Extend the horizon, check calendars/durations, or disable hard due dates. |
| `Feasible` with large gap | Increase time limit and solver workers (Schedule -> Scheduling settings). |
| Locked database | Close other programs using the `.db` file. |

## Known limitations

See [docs/ASSUMPTIONS_AND_LIMITATIONS.md](docs/ASSUMPTIONS_AND_LIMITATIONS.md). In short: fixed estimated durations,
single-capacity machines, non-preemptive operations, no lags/auxiliary resources/shift-calendar engine, one
objective per run, simplified changeover model, single local user, no solver cancellation, no real-factory
validation, solve quality for 20+ orders depends on time limit/CPU cores.

## Verification status

See [docs/TEST_REPORT.md](docs/TEST_REPORT.md) for exactly what was run, where, and what was not.

## Publishing to GitHub

See [docs/GITHUB_PUBLISHING.md](docs/GITHUB_PUBLISHING.md) (target: `vipintk2807/textile-production-optimization`).

## License

MIT (see `LICENSE`). Choose another licence before publishing if you prefer one.
