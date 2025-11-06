import os
import streamlit as st
from pymongo import MongoClient
import pandas as pd
from typing import Optional


# ============================================================
#              PAGE CONFIG (must be at the top)
# ============================================================
st.set_page_config(page_title="Earnings Dashboard", layout="wide")


# ============================================================
#                     AUTHENTICATION LOGIC
# ============================================================

def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    if key in st.secrets:
        return st.secrets[key]
    return os.getenv(key, default)

def check_credentials(username: str, password: str) -> bool:
    return (
        username == get_secret("AUTH_USER", "") and
        password == get_secret("AUTH_PASS", "")
    )

def show_login():
    st.title("🔐 Sign In")
    with st.form("login_form", clear_on_submit=False):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Sign In")
    if ok:
        if check_credentials(u, p):
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Invalid credentials.")


# ============================================================
#                  SHOW LOGIN FIRST
# ============================================================
if "auth_ok" not in st.session_state:
    show_login()
    st.stop()


# ============================================================
#                       MONGO CONNECTION
# ============================================================

MONGO_URI = get_secret("MONGO_URI")
client = MongoClient(MONGO_URI)

DB = client["CAG_CHATBOT"]
COL_ACTUAL = DB["LatestCmotData"]
COL_PREVIEW = DB["company_result_previews"]


# ============================================================
#           PRELOAD EVERYTHING (FASTEST PERFORMANCE)
# ============================================================

@st.cache_data(show_spinner=False)
def load_all_actuals():
    docs = list(COL_ACTUAL.find({}, {
        "company": 1,
        "symbolmap.Company_Name": 1,
        "Standalone.actual": 1,
        "Consolidated.actual": 1
    }))

    actual_map = {}
    for d in docs:
        isin = d.get("company")
        if not isin:
            continue

        name = d.get("symbolmap", {}).get("Company_Name", isin)
        actual_map[isin] = {
            "name": name,
            "data": d
        }

    return actual_map


@st.cache_data(show_spinner=False)
def load_all_previews():
    docs = list(COL_PREVIEW.find({}, {
        "symbolmap.company": 1,
        "symbolmap.Company_Name": 1,
        "report_period": 1,
        "consensus": 1,
        "broker_estimates": 1
    }))

    preview_map = {}
    for d in docs:
        isin = d.get("symbolmap", {}).get("company")
        period = d.get("report_period")
        if not isin or not period:
            continue

        name = d.get("symbolmap", {}).get("Company_Name", isin)
        preview_map[(isin, period)] = {
            "name": name,
            "data": d
        }
    return preview_map


ALL_ACTUALS = load_all_actuals()
ALL_PREVIEWS = load_all_previews()


# ============================================================
#          GLOBAL DISTINCT PERIODS (PERIOD IS FIRST FILTER)
# ============================================================

@st.cache_data(show_spinner=False)
def get_global_expected_periods():
    return sorted({period for (_, period) in ALL_PREVIEWS.keys()})

@st.cache_data(show_spinner=False)
def get_global_actual_periods():
    periods = set()
    for entry in ALL_ACTUALS.values():
        d = entry["data"]
        periods.update(list(d.get("Standalone", {}).get("actual", {}).keys()))
        periods.update(list(d.get("Consolidated", {}).get("actual", {}).keys()))
    return sorted(periods)


EXPECTED_PERIODS = get_global_expected_periods()
ACTUAL_PERIODS = get_global_actual_periods()


# ============================================================
#     BROKER LIST FOR SELECTED EXPECTED PERIOD (OPTION 2)
# ============================================================

def get_brokers_for_period(period):
    brokers = set()
    for (isin, p), entry in ALL_PREVIEWS.items():
        if p == period:
            doc = entry["data"]
            for b in doc.get("broker_estimates", []):
                brokers.add(b["broker_name"])
    return ["Consensus"] + sorted(brokers)


# ============================================================
#                    COMPARISON LOGIC
# ============================================================

def pct(a, e):
    if a is None or e in (None, 0):
        return None
    return ((a / e) - 1) * 100


def process_company(isin, expected_period, actual_period, report_type, broker):
    preview_entry = ALL_PREVIEWS.get((isin, expected_period))
    actual_entry = ALL_ACTUALS.get(isin)

    if not preview_entry or not actual_entry:
        return None

    preview_doc = preview_entry["data"]
    actual_doc = actual_entry["data"]
    company_name = actual_entry["name"]

    # Actual values
    actual_block = actual_doc.get(report_type, {}).get("actual", {}).get(actual_period)
    if not actual_block:
        return None

    act_sales = actual_block.get("net_sales")
    act_ebitda = actual_block.get("ebitda")
    act_pat = actual_block.get("net_profit")
    act_margin = actual_block.get("ebitda_margin")

    # Expected values
    if broker == "Consensus":
        cons = preview_doc.get("consensus", {})
        exp_sales = cons.get("expected_sales", {}).get("mean")
        exp_ebitda = cons.get("expected_ebitda", {}).get("mean")
        exp_pat = cons.get("expected_pat", {}).get("mean")
        exp_margin = cons.get("ebitda_margin_percent", {}).get("mean")
    else:
        b = next((x for x in preview_doc.get("broker_estimates", [])
                  if x["broker_name"] == broker), None)
        if not b:
            return None
        exp_sales = b.get("expected_sales")
        exp_ebitda = b.get("expected_ebitda")
        exp_pat = b.get("expected_pat")
        exp_margin = b.get("ebitda_margin_percent")

    # Differences
    cs = pct(act_sales, exp_sales)
    ce = pct(act_ebitda, exp_ebitda)
    cp = pct(act_pat, exp_pat)
    cm = None if act_margin is None or exp_margin is None else (act_margin - exp_margin) * 100

    # Beats
    bs = 1 if cs is not None and cs > 0 else 0
    be = 1 if ce is not None and ce > 0 else 0
    bp = 1 if cp is not None and cp > 0 else 0
    bm = 1 if cm is not None and cm > 0 else 0

    total = bs + be + bp + bm

    return {
        "Company": company_name,
        "ISIN": isin,
        "Sales %": cs,
        "EBITDA %": ce,
        "PAT %": cp,
        "Margin (bps)": cm,
        "Sales Beat": bs,
        "EBITDA Beat": be,
        "PAT Beat": bp,
        "Margin Beat": bm,
        "Total Beats": total,
    }


# ============================================================
#                      SIDEBAR FILTERS
# ============================================================

st.sidebar.header("🔎 Filters")

# Period FIRST (GLOBAL)
expected_period = st.sidebar.selectbox("Expected Period", EXPECTED_PERIODS)
actual_period = st.sidebar.selectbox("Actual Period", ACTUAL_PERIODS)

# Global broker list for the selected expected_period
broker_list = get_brokers_for_period(expected_period)
broker = st.sidebar.selectbox("Broker", broker_list)

report_type = st.sidebar.radio("Financial Type", ["Standalone", "Consolidated"])

# Default: ALL companies table is ON
show_all = st.sidebar.checkbox("Show ALL companies", value=True)

# Company dropdown (single-company mode)
company_name_to_isin = {v["name"]: isin for isin, v in ALL_ACTUALS.items()}
selected_name = st.sidebar.selectbox("Company (optional)", ["-- Show All --"] + list(company_name_to_isin.keys()))

# If selecting a company → single-company mode
if selected_name != "-- Show All --":
    show_all = False


# ============================================================
#                  ALL COMPANIES TABLE (DEFAULT)
# ============================================================

if show_all:
    rows = []
    for isin in ALL_ACTUALS.keys():
        row = process_company(isin, expected_period, actual_period, report_type, broker)
        if row:
            rows.append(row)

    if rows:
        df_all = pd.DataFrame(rows).sort_values("Total Beats", ascending=False)
        st.title("📊 All Companies — Comparison Table")
        st.caption(f"Actual: {actual_period} | Expected: {expected_period} | Broker: {broker}")
        st.dataframe(df_all, use_container_width=True)
    else:
        st.warning("No companies have both actual and expected data.")

    st.stop()


# ============================================================
#                 SINGLE-COMPANY MODE
# ============================================================

selected_isin = company_name_to_isin.get(selected_name)
row = process_company(selected_isin, expected_period, actual_period, report_type, broker)

if not row:
    st.error("Company does not have matching data for this period.")
    st.stop()

st.title(f"📈 {selected_name} — {report_type} Results")
st.caption(f"Actual: {actual_period} | Expected: {expected_period} | Broker: {broker}")

compare_df = pd.DataFrame({
    "Metric": ["Sales %", "EBITDA %", "PAT %", "Margin (bps)"],
    "Value": [row["Sales %"], row["EBITDA %"], row["PAT %"], row["Margin (bps)"]],
})

st.dataframe(compare_df, use_container_width=True)
st.metric("✅ Total Beats", row["Total Beats"])
