import os
import streamlit as st
from pymongo import MongoClient
import pandas as pd
from functools import lru_cache
from typing import Optional
from dotenv import load_dotenv


# ============================================================
#                     AUTHENTICATION LOGIC
# ============================================================

def init_env():
    load_dotenv(override=False)

def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if "secrets" in dir(st) and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)

def check_credentials(username: str, password: str) -> bool:
    return (
        username == get_secret("AUTH_USER", "") and
        password == get_secret("AUTH_PASS", "")
    )

def show_login():
    st.title("🔐 Sign in")
    with st.form("login_form", clear_on_submit=False):
        u = st.text_input("Username", value="", autocomplete="username")
        p = st.text_input("Password", value="", type="password", autocomplete="current-password")
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
#                         MAIN APP STARTS HERE
# ============================================================
st.set_page_config(page_title="Earnings Dashboard", layout="wide")

# Load environment variables
init_env()

# Mongo connection
MONGO_URI = get_secret("MONGO_URI")
client = MongoClient(MONGO_URI)

DB = client["CAG_CHATBOT"]
COL_ACTUAL = DB["LatestCmotData"]
COL_PREVIEW = DB["company_result_previews"]


# ============================================================
#                       CACHED QUERIES
# ============================================================

@st.cache_data(show_spinner=False)
def get_companies():
    docs = COL_ACTUAL.find({}, {"symbolmap.Company_Name": 1})
    return sorted({doc.get("symbolmap", {}).get("Company_Name") for doc in docs if doc.get("symbolmap")})

@st.cache_data(show_spinner=False)
def get_expected_periods(company):
    return sorted(COL_PREVIEW.find({"symbolmap.Company_Name": company}).distinct("report_period"))

@st.cache_data(show_spinner=False)
def get_actual_periods(company):
    doc = COL_ACTUAL.find_one({"symbolmap.Company_Name": company})
    if not doc:
        return []
    standalone = doc.get("Standalone", {}).get("actual", {})
    consolidated = doc.get("Consolidated", {}).get("actual", {})
    return sorted(set(list(standalone.keys()) + list(consolidated.keys())))

@st.cache_data(show_spinner=False)
def fetch_actual(company, period, report_type):
    doc = COL_ACTUAL.find_one({"symbolmap.Company_Name": company})
    if not doc:
        return None
    data = doc.get(report_type, {}).get("actual", {}).get(period, {})
    return {
        "sales": data.get("net_sales"),
        "ebitda": data.get("ebitda"),
        "pat": data.get("net_profit"),
        "ebitda_margin": data.get("ebitda_margin")
    } if data else None

@st.cache_data(show_spinner=False)
def fetch_preview(company, period):
    return COL_PREVIEW.find_one({
        "symbolmap.Company_Name": company,
        "report_period": period
    })


# ============================================================
#                      SIDEBAR FILTERS
# ============================================================

st.sidebar.header("🔎 Filters")

companies = get_companies()
company = st.sidebar.selectbox("Company", companies)

expected_periods = get_expected_periods(company)
actual_periods = get_actual_periods(company)

expected_period = st.sidebar.selectbox("Expected Period (Estimates)", expected_periods)
actual_period = st.sidebar.selectbox("Actual Report Period", actual_periods)

report_type = st.sidebar.radio("Financials Type", ["Standalone", "Consolidated"])

preview_doc = fetch_preview(company, expected_period)
if not preview_doc:
    st.error("No expected data found for this company/period.")
    st.stop()

broker_list = ["Consensus"] + [b["broker_name"] for b in preview_doc.get("broker_estimates", [])]
broker = st.sidebar.selectbox("Broker", broker_list)


# ============================================================
#                EXPECTED VALUES (BROKER / CONSENSUS)
# ============================================================

if broker == "Consensus":
    cons = preview_doc["consensus"]
    expected_sales = cons["expected_sales"]["mean"]
    expected_ebitda = cons["expected_ebitda"]["mean"]
    expected_pat = cons["expected_pat"]["mean"]
    expected_margin = cons["ebitda_margin_percent"]["mean"]
else:
    b = next(x for x in preview_doc["broker_estimates"] if x["broker_name"] == broker)
    expected_sales = b.get("expected_sales")
    expected_ebitda = b.get("expected_ebitda")
    expected_pat = b.get("expected_pat")
    expected_margin = b.get("ebitda_margin_percent")


# ============================================================
#                       ACTUAL VALUES
# ============================================================

actual = fetch_actual(company, actual_period, report_type)
if not actual:
    st.error("Actual data missing for selected period.")
    st.stop()

actual_sales = actual["sales"]
actual_ebitda = actual["ebitda"]
actual_pat = actual["pat"]
actual_margin = actual["ebitda_margin"]


# ============================================================
#                    COMPUTATION LOGIC
# ============================================================

def pct_difference(actual, expected):
    if actual is None or expected in (None, 0):
        return None
    return ((actual / expected) - 1) * 100

compare_sales = pct_difference(actual_sales, expected_sales)
compare_ebitda = pct_difference(actual_ebitda, expected_ebitda)
compare_pat = pct_difference(actual_pat, expected_pat)
compare_margin = (actual_margin - expected_margin) * 100  # bps

beat_sales = 1 if compare_sales and compare_sales > 0 else 0
beat_ebitda = 1 if compare_ebitda and compare_ebitda > 0 else 0
beat_pat = 1 if compare_pat and compare_pat > 0 else 0
beat_margin = 1 if compare_margin and compare_margin > 0 else 0

total_beats = beat_sales + beat_ebitda + beat_pat + beat_margin


# ============================================================
#                        DISPLAY TABLE
# ============================================================

st.title(f"📈 {company} — {report_type} Results")
st.caption(f"Comparing **{actual_period} Actuals** vs **{expected_period} Estimates** ({broker})")

df = pd.DataFrame({
    "Metric": ["Sales", "EBITDA", "PAT", "EBITDA Margin"],
    "Expected": [expected_sales, expected_ebitda, expected_pat, expected_margin],
    "Actual": [actual_sales, actual_ebitda, actual_pat, actual_margin],
    "Difference (%)": [compare_sales, compare_ebitda, compare_pat, compare_margin],
    "Beat": [beat_sales, beat_ebitda, beat_pat, beat_margin]
})

styled = df.style.format({
    "Expected": "{:,.2f}",
    "Actual": "{:,.2f}",
    "Difference (%)": "{:+.2f}"
}).apply(
    lambda row: ["background-color:#d4edda" if row["Beat"] == 1 else "background-color:#f8d7da"] * len(row),
    axis=1
)

st.dataframe(styled, use_container_width=True)

st.metric("✅ Total Beats", total_beats)
