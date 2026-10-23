"""Service factory and flash-message helpers for the Streamlit pages."""

from __future__ import annotations

import streamlit as st

from .. import config
from ..persistence.repository import Repository
from ..services.planning_service import PlanningService


@st.cache_resource(show_spinner=False)
def _repository(path: str) -> Repository:
    return Repository(path)


def get_service() -> PlanningService:
    return PlanningService(_repository(str(config.db_path())))


def flash(kind: str, message: str) -> None:
    """Queue a message to show after the next rerun (e.g. after a successful save)."""
    st.session_state.setdefault("_flash", []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop("_flash", []):
        getattr(st, kind)(message)


def go_to(page_key: str) -> None:
    page = PAGES.get(page_key)
    if page is not None:
        st.switch_page(page)


PAGES: dict[str, object] = {}
