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
        "symbolmap": 1,
        "Standalone.actual": 1,
        "Consolidated.actual": 1
    }))

    actual_map = {}
    for d in docs:
        symbol = d.get("symbolmap", {})
        name = symbol.get("Company_Name")   # safe access
        if not name:
            continue    # skip empty/broken docs
        actual_map[name] = d

    return actual_map


@st.cache_data(show_spinner=False)
def load_all_previews():
    docs = list(COL_PREVIEW.find({}, {
        "symbolmap": 1,
        "report_period": 1,
        "consensus": 1,
        "broker_estimates": 1
    }))

    preview_map = {}
    for d in docs:
        symbol = d.get("symbolmap", {})
        name = symbol.get("Company_Name")
        period = d.get("report_period")

        if not name or not period:
            continue    # skip incomplete docs

        preview_map[(name, period)] = d

    return preview_map


@st.cache_data(show_spinner=False)
def load_company_names():
    docs = COL_ACTUAL.find({}, {"symbolmap.Company_Name": 1})
    return sorted({d["symbolmap"]["Company_Name"] for d in docs})


# Preload datasets
ALL_ACTUALS = load_all_actuals()
ALL_PREVIEWS = load_all_previews()
COMPANIES = load_company_names()


# ============================================================
#                       SAFE COMPARISON LOGIC
# ============================================================

def pct(a, e):
    if a is None or e in (None, 0):
        return None
    return ((a / e) - 1) * 100


def process_company(company, expected_period, actual_period, report_type, broker):
    """Compute comparison row for one company using preloaded data."""
    preview_doc = ALL_PREVIEWS.get((company, expected_period))
    actual_doc = ALL_ACTUALS.get(company)

    if not preview_doc or not actual_doc:
        return None

    # ---- Actual Data ----
    actual_block = actual_doc.get(report_type, {}).get("actual", {}).get(actual_period)
    if not actual_block:
        return None

    act_sales = actual_block.get("net_sales")
    act_ebitda = actual_block.get("ebitda")
    act_pat = actual_block.get("net_profit")
    act_margin = actual_block.get("ebitda_margin")

    # ---- Expected Data ----
    if broker == "Consensus":
        cons = preview_doc.get("consensus", {})
        exp_sales = cons.get("expected_sales", {}).get("mean")
        exp_ebitda = cons.get("expected_ebitda", {}).get("mean")
        exp_pat = cons.get("expected_pat", {}).get("mean")
        exp_margin = cons.get("ebitda_margin_percent", {}).get("mean")
    else:
        match = next((b for b in preview_doc.get("broker_estimates", [])
                      if b["broker_name"] == broker), None)
        if not match:
            return None
        exp_sales = match.get("expected_sales")
        exp_ebitda = match.get("expected_ebitda")
        exp_pat = match.get("expected_pat")
        exp_margin = match.get("ebitda_margin_percent")

    # ---- Comparisons ----
    cs = pct(act_sales, exp_sales)
    ce = pct(act_ebitda, exp_ebitda)
    cp = pct(act_pat, exp_pat)

    if act_margin is None or exp_margin is None:
        cm = None
    else:
        cm = (act_margin - exp_margin) * 100

    # ---- Beat Flags ----
    bs = 1 if cs is not None and cs > 0 else 0
    be = 1 if ce is not None and ce > 0 else 0
    bp = 1 if cp is not None and cp > 0 else 0
    bm = 1 if cm is not None and cm > 0 else 0
    total = bs + be + bp + bm

    return {
        "Company": company,
        "Sales %": cs,
        "EBITDA %": ce,
        "PAT %": cp,
        "Margin (bps)": cm,
        "Sales Beat": bs,
        "EBITDA Beat": be,
        "PAT Beat": bp,
        "Margin Beat": bm,
        "Total Beats": total
    }


# ============================================================
#                      SIDEBAR FILTERS
# ============================================================

st.sidebar.header("🔎 Filters")

company = st.sidebar.selectbox("Company", COMPANIES)

# available periods
exp_periods = sorted({key[1] for key in ALL_PREVIEWS.keys() if key[0] == company})
act_periods = sorted(
    list(ALL_ACTUALS.get(company, {}).get("Standalone", {}).get("actual", {}).keys()) +
    list(ALL_ACTUALS.get(company, {}).get("Consolidated", {}).get("actual", {}).keys())
)

show_all = st.sidebar.checkbox("Show ALL companies for this period", value=False)

expected_period = st.sidebar.selectbox("Expected Period", exp_periods)
actual_period = st.sidebar.selectbox("Actual Period", act_periods)
report_type = st.sidebar.radio("Type", ["Standalone", "Consolidated"])

preview_doc = ALL_PREVIEWS.get((company, expected_period))
if not preview_doc:
    st.error("No estimate data found for this period.")
    st.stop()

broker_list = ["Consensus"] + [b["broker_name"] for b in preview_doc.get("broker_estimates", [])]
broker = st.sidebar.selectbox("Broker", broker_list)


# ============================================================
#               ALL COMPANIES TABLE (FAST MODE)
# ============================================================

if show_all:
    rows = []
    for comp in COMPANIES:
        row = process_company(comp, expected_period, actual_period, report_type, broker)
        if row:
            rows.append(row)

    if rows:
        df_all = pd.DataFrame(rows).sort_values("Total Beats", ascending=False)
        st.subheader(f"📊 All Companies — {actual_period} vs {expected_period} ({broker})")
        st.dataframe(df_all, use_container_width=True)
    else:
        st.warning("No companies have both expected and actual data.")

    st.stop()


# ============================================================
#                   SINGLE COMPANY VIEW
# ============================================================

row = process_company(company, expected_period, actual_period, report_type, broker)
if not row:
    st.error("Company missing required data.")
    st.stop()

st.title(f"📈 {company} — {report_type} Results")
st.caption(f"{actual_period} Actuals vs {expected_period} Estimates ({broker})")

df = pd.DataFrame({
    "Metric": ["Sales", "EBITDA", "PAT", "EBITDA Margin"],
    "Expected": [
        row["Sales %"] is not None,
        row["EBITDA %"] is not None,
        row["PAT %"] is not None,
        row["Margin (bps)"] is not None,
    ],
})

compare_df = pd.DataFrame({
    "Metric": ["Sales %", "EBITDA %", "PAT %", "Margin (bps)"],
    "Value": [row["Sales %"], row["EBITDA %"], row["PAT %"], row["Margin (bps)"]],
})

st.subheader("Compare vs Expected (%)")
st.dataframe(compare_df, use_container_width=True)

st.metric("✅ Total Beats", row["Total Beats"])
