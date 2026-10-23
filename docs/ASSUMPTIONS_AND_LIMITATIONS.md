# Assumptions, specification reconciliation and limitations

## Source documents
Implemented from the supplied `project_explanation`, `app_workflow`, `app_theme`, `technical_specification`,
`textile_scheduling_rules`, `testing_requirements` and `master_prompt` files (supplied as Markdown; the documents
refer to them as `.docx`).

## Where the documents differed and what was implemented
| Topic | Difference | Decision |
|---|---|---|
| Objective | `project_explanation` mentions a staged tardiness-first hierarchy; `technical_specification` 8.1 and `textile_scheduling_rules` 13.1 require **one objective per run**. | One objective per run (makespan / total tardiness / weighted tardiness). Staged multi-objective optimization is **not** implemented. |
| Due dates | `app_workflow` suggests calendar due dates; the model uses integer minutes. | Times are whole minutes from a configured planning origin; the UI shows the calendar equivalent. |
| Priority vs weight | Priority is informational; weights for weighted tardiness must be explicit. | `priority` 1 (lowest)-5 (highest) is informational only. `weight` (integer >= 0) is required for every scheduled order only when the weighted objective is selected. Nothing is inferred. |
| Changeovers | Conditional feature in the specifications. | Implemented (see below) and disclosed as *not modelled* whenever disabled. |
| Machine capability | Operations must match machine capabilities but eligibility must be explicit. | `operation_name` is the process category; a machine may be listed as eligible only if its supported processes include that name. |

## Modelling assumptions (all explicit and tested)
* Time unit: integer minutes from the planning origin; 1 scheduling minute = 1 clock minute. Shifts/breaks/holidays must be entered as availability windows. Naive local times only (no time zones). Sub-minute values are rejected, not rounded.
* Intervals are half-open `[start, end)`; back-to-back operations are allowed; an operation may end exactly at a window end or at the horizon end.
* Non-preemptive operations; each must fit completely inside one effective window (availability minus downtime). Machines are single-capacity.
* Availability windows may not overlap each other; downtime intervals may not overlap each other (rejected). Windows beyond the horizon are clipped with a warning. A machine used by scheduled operations with no availability is a blocking error (unknown availability is never unlimited).
* Only `ready` orders, their `active` operations and `active` machines are scheduled. Draft orders are excluded with a warning.
* Precedence: finish-to-start, no lag, within one order only. Order completion = latest end of the order's terminal operations.
* Due dates are soft optimization targets unless "enforce due dates" is switched on.
* Machine-specific durations: an optional per-machine override replaces the operation's default duration on that machine only.
* **Changeovers** (optional): explicit category-to-category minutes. Setup is a minimum gap between *consecutive* operations on a machine; it occupies the machine but need not lie inside an availability window; the first operation on a machine needs no setup. Every ordered pair of categories that can meet on a machine must be defined (0 allowed) and transitions must satisfy the triangle inequality (otherwise blocking error) so that enforcing the gap between every pair equals enforcing it between consecutive operations.
* Utilization excludes changeover time and is computed per machine over `[0, horizon_end)`.
* Fingerprint: includes scheduling-relevant data (ready orders: release, due, weight; active machines' effective windows; operations' options, predecessors, categories when changeovers are on; matrix when on; horizon; origin; objective; hard-due and changeover flags). It excludes names, notes, descriptions, quantities, product codes, solver time limit/workers/seed.
* Solver defaults: 30 s time limit, 1 worker, seed 1 (favours reproducibility; reproducibility of identical schedules is **not** guaranteed).

## Limitations
1. Durations are entered/estimated values (flagged as estimates); no quantity x rate derivation.
2. No lags, preemption, multi-capacity/batch machines, operators/tools/utilities, cross-order dependencies or split/merge routes.
3. No shift/holiday calendar engine, no live data integration, no machine control.
4. Changeover model is global (not machine-specific) and simplified as above.
5. One objective per run; no staged lexicographic optimization; no soft constraints.
6. The solver call blocks the Streamlit script; there is **no cancellation**. Duplicate-run protection is a per-process lock plus a disabled button.
7. Solution quality for larger instances depends on time limit and CPU cores (see `docs/benchmark_results.md`); no maximum problem size is claimed.
8. Single-user local SQLite; no authentication; not for networked/multi-user use without a security review.
9. A validated schedule is valid only with respect to the implemented constraints. Real-factory suitability is **unverified** and needs review with production staff and real data.
10. The visual theme was implemented with Streamlit's native theme + small CSS but has **not been visually reviewed** in a browser by the author; only automated rendering tests were run.
