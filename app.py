"""Textile Production Optimization - Streamlit entry point.

Run with:  python -m streamlit run app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

from textile_optimizer import __version__  # noqa: E402
from textile_optimizer.errors import TextileOptimizerError  # noqa: E402
from textile_optimizer.logging_setup import get_logger  # noqa: E402
from textile_optimizer.ui import context  # noqa: E402
from textile_optimizer.ui.pages import dashboard, machines, operations, orders, reports, schedule  # noqa: E402

st.set_page_config(
    page_title="Textile Production Optimization", page_icon=":material/factory:", layout="wide"
)
log = get_logger("app")


def _guard(render):
    """Show concise errors instead of raw tracebacks; details go to the log."""

    def wrapper():
        try:
            render()
        except TextileOptimizerError as exc:
            st.error(f"{exc}")
        except Exception:  # noqa: BLE001
            log.exception("Unexpected error while rendering a page")
            st.error(
                "An unexpected error occurred. Details were written to data/logs/app.log. "
                "Your saved data is unchanged."
            )

    wrapper.__name__ = render.__module__.rsplit(".", 1)[-1]
    return wrapper


pages = {
    "dashboard": st.Page(
        _guard(dashboard.render),
        title="Dashboard",
        icon=":material/dashboard:",
        default=True,
        url_path="dashboard",
    ),
    "orders": st.Page(
        _guard(orders.render), title="Production Orders", icon=":material/receipt_long:", url_path="orders"
    ),
    "machines": st.Page(
        _guard(machines.render),
        title="Machines",
        icon=":material/precision_manufacturing:",
        url_path="machines",
    ),
    "operations": st.Page(
        _guard(operations.render), title="Operations", icon=":material/account_tree:", url_path="operations"
    ),
    "schedule": st.Page(
        _guard(schedule.render), title="Schedule", icon=":material/calendar_month:", url_path="schedule"
    ),
    "reports": st.Page(
        _guard(reports.render), title="Reports", icon=":material/bar_chart:", url_path="reports"
    ),
}
context.PAGES.update(pages)
navigation = st.navigation(list(pages.values()))
st.sidebar.markdown(f"**Textile Production Optimization**  \nv{__version__} - local planning tool")
st.sidebar.caption(
    "Decision support only. Schedules are validated against the implemented model, not the factory floor."
)
navigation.run()
