"""Streamlit AppTest checks: pages render with empty and populated databases, the solver runs
only on an explicit click, and error states are shown instead of tracebacks."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from textile_optimizer.persistence.repository import Repository
from textile_optimizer.services.planning_service import PlanningService
from textile_optimizer.services.sample_data import load_sample_data

SRC = Path(__file__).resolve().parents[2] / "src"
APP_FILE = Path(__file__).resolve().parents[2] / "app.py"
PAGES = ["dashboard", "orders", "machines", "operations", "schedule", "reports"]


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TPO_DB_PATH", str(tmp_path / "ui.db"))
    return tmp_path / "ui.db"


def page_app(page: str) -> AppTest:
    script = f"""
import sys
sys.path.insert(0, {str(SRC)!r})
from textile_optimizer.ui.pages import {page}
{page}.render()
"""
    return AppTest.from_string(script, default_timeout=60)


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_on_empty_database(db_env, page):
    at = page_app(page).run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_with_sample_data(db_env, page):
    load_sample_data(PlanningService(Repository(db_env)))
    at = page_app(page).run()
    assert not at.exception, [e.value for e in at.exception]


def test_full_app_entry_point_launches(db_env):
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    assert not at.exception and at.title[0].value == "Dashboard"


def test_dashboard_shows_unavailable_not_zero_when_no_schedule(db_env):
    at = page_app("dashboard").run()
    values = {m.label: m.value for m in at.metric}
    assert values["Scheduled operations"] == "unavailable" and values["Late orders"] == "unavailable"
    assert values["Production orders"] == "0"


def test_rerun_does_not_start_solver_and_click_does(db_env):
    repo = Repository(db_env)
    load_sample_data(PlanningService(repo))
    at = page_app("schedule").run()
    at.run()  # an extra rerun
    at.run()
    assert repo.counts()["runs"] == 0  # no run without an explicit click
    gen = next(b for b in at.button if b.label == "Generate Schedule")
    assert not gen.disabled
    gen.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert repo.counts()["runs"] == 1
    assert repo.latest_accepted_run() is not None
    at.run()  # a rerun after the click must not create a second run
    assert repo.counts()["runs"] == 1


def test_generate_disabled_when_inputs_invalid(db_env):
    at = page_app("schedule").run()
    gen = next(b for b in at.button if b.label == "Generate Schedule")
    assert gen.disabled
    assert any("Blocking errors" in m.label for m in at.metric)


def test_stale_banner_after_data_change(db_env):
    repo = Repository(db_env)
    svc = PlanningService(repo)
    load_sample_data(svc)
    svc.run_schedule()
    order = repo.get_order("SYN-ORD-001")
    svc.save_order(order.model_copy(update={"due_time": order.due_time + 10}), is_new=False)
    at = page_app("dashboard").run()
    assert any("out of date" in w.value.lower() for w in at.warning)
    values = {m.label: m.value for m in at.metric}
    assert values["Late orders"] == "unavailable"  # stale metrics are not shown as current


def test_order_form_rejects_invalid_values_and_saves_valid(db_env):
    at = page_app("orders").run()
    at.text_input[1].set_value("") if len(at.text_input) > 1 else None
    form_inputs = {t.label: t for t in at.text_input}
    form_inputs["Order ID *"].set_value("UI-1")
    form_inputs["Product code *"].set_value("")
    next(b for b in at.button if b.label == "Save Order").click().run()
    assert any("Product code" in e.value for e in at.error)  # invalid: nothing saved
    assert Repository(db_env).list_orders() == []
    at = page_app("orders").run()
    form_inputs = {t.label: t for t in at.text_input}
    form_inputs["Order ID *"].set_value("UI-1")
    form_inputs["Product code *"].set_value("P-1")
    next(b for b in at.button if b.label == "Save Order").click().run()
    assert not at.exception
    assert [o.order_id for o in Repository(db_env).list_orders()] == ["UI-1"]
