"""Shared Streamlit UI helpers: theme CSS, status badges, headers, formatting.

Only native Streamlit components plus a small, scoped CSS block are used (app_theme 15).
Status is always conveyed by a text label; colour is a secondary cue.
"""

from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

from ..domain.timeutil import to_datetime
from ..persistence.repository import StoredRun

CSS = """
<style>
html, body, [class*="css"] { font-family: "Segoe UI", Arial, sans-serif; }
.tpo-badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:13px;
             font-weight:600; border:1px solid; margin-right:6px; }
.tpo-green { color:#15803D; border-color:#15803D; background:#F0FDF4; }
.tpo-blue  { color:#1D4ED8; border-color:#1D4ED8; background:#EFF6FF; }
.tpo-amber { color:#B45309; border-color:#B45309; background:#FFFBEB; }
.tpo-red   { color:#B91C1C; border-color:#B91C1C; background:#FEF2F2; }
.tpo-grey  { color:#475569; border-color:#CBD5E1; background:#F1F5F9; }
div[data-testid="stMetric"] { background:#FFFFFF; border:1px solid #CBD5E1; border-radius:6px;
                              padding:8px 12px; }
</style>
"""

# Solver / run outcome -> (label, colour class, explanation). The label is authoritative.
OUTCOME_STYLES = {
    ("ACCEPTED", "OPTIMAL"): ("Optimal", "green", "The optimum for the configured objective was proven."),
    ("ACCEPTED", "FEASIBLE"): ("Feasible", "blue", "A valid schedule was found; optimality was NOT proven."),
    ("INFEASIBLE", None): ("Infeasible", "red", "No schedule satisfies the encoded constraints (proven)."),
    ("NO_SOLUTION", None): (
        "Time limit reached - no solution",
        "amber",
        "No feasible solution found in time; infeasibility was NOT proven.",
    ),
    ("VALIDATION_FAILED", None): ("Validation failed", "red", "The candidate failed independent validation."),
    ("MODEL_INVALID", None): ("Solver error: invalid model", "red", "The optimization model was rejected."),
    ("ERROR", None): ("Solver error", "red", "The scheduling attempt failed."),
}


def inject_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def badge(label: str, kind: str = "grey") -> str:
    return f'<span class="tpo-badge tpo-{kind}">{html.escape(label)}</span>'


def show_badges(*items: tuple[str, str]) -> None:
    st.markdown(" ".join(badge(label, kind) for label, kind in items), unsafe_allow_html=True)


def outcome_label(run: StoredRun) -> tuple[str, str, str]:
    key = (run.outcome, run.solver_status if run.outcome == "ACCEPTED" else None)
    return OUTCOME_STYLES.get(key, (run.outcome.title(), "grey", ""))


def page_header(title: str, description: str) -> None:
    inject_theme()
    st.title(title)
    st.caption(description)


def empty_state(message: str) -> None:
    st.info(message)


def show_issues(report, *, title: str = "Validation results") -> None:
    """Render errors (blocking) and warnings with text labels."""
    if report.errors:
        st.error(f"**Blocking errors ({len(report.errors)})** - fix these before scheduling.")
        for issue in report.errors:
            st.markdown(f"- **Error:** {issue.message}")
    if report.warnings:
        with st.expander(f"Warnings ({len(report.warnings)})", expanded=not report.errors):
            for issue in report.warnings:
                st.markdown(f"- **Warning:** {issue.message}")
    if not report.errors and not report.warnings:
        st.success("Input validation: no errors or warnings.")


def fmt_time(minutes, origin: datetime | None) -> str:
    if minutes is None:
        return "unavailable"
    if origin is None:
        return str(int(minutes))
    return f"{int(minutes)} ({to_datetime(int(minutes), origin):%a %d %b %H:%M})"
