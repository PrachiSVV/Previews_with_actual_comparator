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
    """Streamlit Cloud reads secrets from st.secrets."""
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
        "company": 1,                           # ← ISIN
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
        "symbolmap.company": 1,                 # ← ISIN
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


@st.cache_data(show_spinner=False)
def load_company_list():
    """Return dropdown list: Show names but internally mapped by ISIN."""
    actuals = load_all_actuals()
    return {v["name"]: isin for isin, v in actuals.items()}


ALL_ACTUALS = load_all_actuals()
ALL_PREVIEWS = load_all_previews()
COMPANY_OPTIONS = load_company_list()   # Name → ISIN mapping


# ============================================================
#                       SAFE COMPARISON LOGIC
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

    company_name = actual_entry["name"]
    preview_doc = preview_entry["data"]
    actual_doc = actual_entry["data"]

    # ---- Actual ----
    actual_block = actual_doc.get(report_type, {}).get("actual", {}).get(actual_period)
    if not actual_block:
        return None

    act_sales = actual_block.get("net_sales")
    act_ebitda = actual_block.get("ebitda")
    act_pat = actual_block.get("net_profit")
    act_margin = actual_block.get("ebitda_margin")

    # ---- Expected ----
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

    # ---- Comparison ----
    cs = pct(act_sales, exp_sales)
    ce = pct(act_ebitda, exp_ebitda)
    cp = pct(act_pat, exp_pat)
    cm = None if act_margin is None or exp_margin is None else (act_margin - exp_margin) * 100

    # ---- Beats ----
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

selected_name = st.sidebar.selectbox("Company", list(COMPANY_OPTIONS.keys()))
selected_isin = COMPANY_OPTIONS[selected_name]

# Periods available
exp_periods = sorted({p for (isin, p) in ALL_PREVIEWS.keys() if isin == selected_isin})

actual_doc = ALL_ACTUALS[selected_isin]["data"]
act_periods = sorted(
    list(actual_doc.get("Standalone", {}).get("actual", {}).keys()) +
    list(actual_doc.get("Consolidated", {}).get("actual", {}).keys())
)

show_all = st.sidebar.checkbox("Show ALL companies for this period", value=False)

expected_period = st.sidebar.selectbox("Expected Period", exp_periods)
actual_period = st.sidebar.selectbox("Actual Period", act_periods)
report_type = st.sidebar.radio("Type", ["Standalone", "Consolidated"])

preview_entry = ALL_PREVIEWS.get((selected_isin, expected_period))
if not preview_entry:
    st.error("No estimate data found for this period.")
    st.stop()

preview_doc = preview_entry["data"]
broker_list = ["Consensus"] + [b["broker_name"] for b in preview_doc.get("broker_estimates", [])]
broker = st.sidebar.selectbox("Broker", broker_list)


# ============================================================
#               ALL COMPANIES TABLE (FAST MODE)
# ============================================================

if show_all:
    rows = []
    for isin in ALL_ACTUALS.keys():
        row = process_company(isin, expected_period, actual_period, report_type, broker)
        if row:
            rows.append(row)

    if rows:
        df_all = pd.DataFrame(rows).sort_values("Total Beats", ascending=False)
        st.subheader(f"📊 All Companies — {actual_period} vs {expected_period} ({broker})")
        st.dataframe(df_all, use_container_width=True)
    else:
        st.warning("No companies have both actual and expected data.")

    st.stop()


# ============================================================
#                   SINGLE COMPANY VIEW
# ============================================================

row = process_company(selected_isin, expected_period, actual_period, report_type, broker)
if not row:
    st.error("Company missing required data.")
    st.stop()

st.title(f"📈 {selected_name} — {report_type} Results")
st.caption(f"{actual_period} Actuals vs {expected_period} Estimates ({broker})")

compare_df = pd.DataFrame({
    "Metric": ["Sales %", "EBITDA %", "PAT %", "Margin (bps)"],
    "Value": [row["Sales %"], row["EBITDA %"], row["PAT %"], row["Margin (bps)"]],
})

st.subheader("Comparison (% difference vs estimates)")
st.dataframe(compare_df, use_container_width=True)

st.metric("✅ Total Beats", row["Total Beats"])
