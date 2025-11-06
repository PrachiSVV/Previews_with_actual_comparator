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

    # ---- Actual ----
    actual_block = actual_doc.get(report_type, {}).get("actual", {}).get(actual_period)
    if not actual_block:
        return None

    act_sales = actual_block.get("net_sales")
    act_ebitda = actual_block.get("ebitda")
    act_pat = actual_block.get("net_profit")
    act_ebitda_margin = actual_block.get("ebitda_margin")
    act_pat_margin = actual_block.get("pat_margin")

    # ---- Expected ----
    if broker == "Consensus":
        cons = preview_doc.get("consensus", {})
        exp_sales = cons.get("expected_sales", {}).get("mean")
        exp_ebitda = cons.get("expected_ebitda", {}).get("mean")
        exp_pat = cons.get("expected_pat", {}).get("mean")
        exp_ebitda_margin = cons.get("ebitda_margin_percent", {}).get("mean")
        exp_pat_margin = cons.get("pat_margin_percent", {}).get("mean")
    else:
        b = next((x for x in preview_doc.get("broker_estimates", [])
                  if x["broker_name"] == broker), None)
        if not b:
            return None
        exp_sales = b.get("expected_sales")
        exp_ebitda = b.get("expected_ebitda")
        exp_pat = b.get("expected_pat")
        exp_ebitda_margin = b.get("ebitda_margin_percent")
        exp_pat_margin = b.get("pat_margin_percent")

    # ---- Differences ----
    cs = pct(act_sales, exp_sales)
    ce = pct(act_ebitda, exp_ebitda)
    cp = pct(act_pat, exp_pat)
    cem = None if act_ebitda_margin is None or exp_ebitda_margin is None else (act_ebitda_margin - exp_ebitda_margin) * 100
    cpm = None if act_pat_margin is None or exp_pat_margin is None else (act_pat_margin - exp_pat_margin) * 100

    # ---- Beat flags ----
    bs = 1 if cs is not None and cs > 0 else 0
    be = 1 if ce is not None and ce > 0 else 0
    bp = 1 if cp is not None and cp > 0 else 0
    bem = 1 if cem is not None and cem > 0 else 0
    bpm = 1 if cpm is not None and cpm > 0 else 0

    total_beats = bs + be + bp + bem + bpm

    return {
        "Company": company_name,
        "ISIN": isin,

        # Expected values
        "Exp Sales": exp_sales,
        "Exp EBITDA": exp_ebitda,
        "Exp PAT": exp_pat,
        "Exp EBITDA Margin %": exp_ebitda_margin,
        "Exp PAT Margin %": exp_pat_margin,

        # Actual values
        "Act Sales": act_sales,
        "Act EBITDA": act_ebitda,
        "Act PAT": act_pat,
        "Act EBITDA Margin %": act_ebitda_margin,
        "Act PAT Margin %": act_pat_margin,

        # Differences
        "Sales % Diff": cs,
        "EBITDA % Diff": ce,
        "PAT % Diff": cp,
        "EBITDA Margin bps Diff": cem,
        "PAT Margin bps Diff": cpm,

        # Beats
        "Sales Beat": bs,
        "EBITDA Beat": be,
        "PAT Beat": bp,
        "EBITDA Margin Beat": bem,
        "PAT Margin Beat": bpm,

        "Total Beats": total_beats
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
def format_one_decimal(df):
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype(float).round(1)
    return df

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

        df_all = format_one_decimal(df_all)
        st.dataframe(df_all, use_container_width=True)


        # st.dataframe(df_all, use_container_width=True)
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

# Expanded detailed comparison
single_df = pd.DataFrame({
    "Metric": [
        "Sales", "EBITDA", "PAT", "EBITDA Margin", "PAT Margin"
    ],
    "Expected": [
        row["Exp Sales"], row["Exp EBITDA"], row["Exp PAT"],
        row["Exp EBITDA Margin %"], row["Exp PAT Margin %"]
    ],
    "Actual": [
        row["Act Sales"], row["Act EBITDA"], row["Act PAT"],
        row["Act EBITDA Margin %"], row["Act PAT Margin %"]
    ],
    "Difference": [
        row["Sales % Diff"], row["EBITDA % Diff"], row["PAT % Diff"],
        row["EBITDA Margin bps Diff"], row["PAT Margin bps Diff"]
    ],
    "Beat": [
        row["Sales Beat"], row["EBITDA Beat"], row["PAT Beat"],
        row["EBITDA Margin Beat"], row["PAT Margin Beat"]
    ]
})

single_df = format_one_decimal(single_df)

st.dataframe(single_df, use_container_width=True)
st.metric("✅ Total Beats", row["Total Beats"])
