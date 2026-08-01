from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st

from insightflow.config import ensure_directories, is_read_only
from insightflow.i18n import t
from insightflow.ui import apply_design_system, render_app_brand
from insightflow.pages import (
    actions,
    assistant,
    customers,
    data_hub,
    decision_lab,
    diagnostics,
    experiments,
    inventory,
    overview,
    planning,
    products,
    profit,
    quality,
    report,
    sales,
)

ensure_directories(allow_write=not is_read_only())

st.set_page_config(
    page_title="InsightFlow · Decision Intelligence",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_design_system()
render_app_brand()

pages = {
    t("nav.executive"): [
        st.Page(overview.render, title=t("page.overview.title"), icon=":material/space_dashboard:", url_path="overview", default=True),
        st.Page(actions.render, title=t("page.actions.title"), icon=":material/task_alt:", url_path="actions"),
    ],
    t("nav.diagnose"): [
        st.Page(sales.render, title=t("page.sales.title"), icon=":material/trending_up:", url_path="sales"),
        st.Page(profit.render, title=t("page.profit.title"), icon=":material/paid:", url_path="profit"),
        st.Page(customers.render, title=t("page.customers.title"), icon=":material/group:", url_path="customers"),
        st.Page(products.render, title=t("page.products.title"), icon=":material/inventory_2:", url_path="products"),
        st.Page(inventory.render, title=t("page.inventory.title"), icon=":material/local_shipping:", url_path="inventory"),
        st.Page(diagnostics.render, title=t("page.diagnostics.title"), icon=":material/monitoring:", url_path="diagnostics"),
    ],
    t("nav.plan"): [
        st.Page(planning.render, title=t("page.planning.title"), icon=":material/event_upcoming:", url_path="planning"),
        st.Page(decision_lab.render, title=t("page.decision_lab.title"), icon=":material/science:", url_path="decision-lab"),
        st.Page(experiments.render, title=t("page.experiments.title"), icon=":material/biotech:", url_path="experiments"),
    ],
    t("nav.ask"): [
        st.Page(assistant.render, title=t("page.assistant.title"), icon=":material/auto_awesome:", url_path="assistant"),
    ],
    t("nav.data"): [
        st.Page(data_hub.render, title=t("page.data_hub.title"), icon=":material/upload_file:", url_path="data-hub"),
    ],
    t("nav.trust"): [
        st.Page(quality.render, title=t("page.quality.title"), icon=":material/verified_user:", url_path="quality"),
        st.Page(report.render, title=t("page.report.title"), icon=":material/description:", url_path="report"),
    ],
}


navigation = st.navigation(pages)
navigation.run()
