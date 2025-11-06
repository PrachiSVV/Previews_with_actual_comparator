# =====================================================================
# ==========================  APP.PY  =================================
# =====================================================================

import hashlib
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

# ==============================
# -------- CONFIG --------------
# ==============================
st.set_page_config(
    page_title="Results vs Expectations",
    page_icon="📊",
    layout="wide",
)

REQUIRED_COLS = [
    "co_code","nsesymbol","broker_name","sales","pat","ebitda","picked_type",
    "expected_sales","expected_ebitda","expected_pat",
    "ebitda_margin_percent","pat_margin_percent",
    "sales_beat","pat_beat","ebitda_beat",
    "sales_flag","pat_flag","ebitda_flag","overall_flag",
]

NUMERIC_COLS = [
    "sales","pat","ebitda",
    "expected_sales","expected_ebitda","expected_pat",
    "ebitda_margin_percent","pat_margin_percent",
    "sales_beat","pat_beat","ebitda_beat",
]

STATUS_ORDER = ["Beat", "Inline", "Miss"]

# ==============================
# -------- AUTH ----------------
# ==============================
def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def check_login(username: str, password: str) -> bool:
    users = st.secrets.get("auth", {}).get("users", {})
    if not username or username not in users:
        return False
    return _sha256(password) == users[username]

def login_gate():
    if "auth_user" in st.session_state:
        return True

    st.markdown(
        """
        <div style="padding:24px;border-radius:16px;background:linear-gradient(135deg,#0ea5e9, #3b82f6);color:white;">
          <h2 style="margin:0;">🔐 Login to Results Dashboard</h2>
          <p style="margin:6px 0 0 0;opacity:.9;">Secure access required</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("login"):
        c1, c2, c3 = st.columns([3,3,1.2])
        username = c1.text_input("Username")
        password = c2.text_input("Password", type="password")
        submit   = c3.form_submit_button("Log in")
    if submit:
        if check_login(username, password):
            st.session_state.auth_user = username
            st.success("Logged in successfully.")
            st.rerun()
        else:
            st.error("Invalid credentials. Please try again.")
            time.sleep(0.6)
    st.stop()

# Gate the app
login_gate()

# Optional logout in sidebar
if st.sidebar.button("🚪 Log out"):
    st.session_state.pop("auth_user", None)
    st.rerun()


# ==============================
# ---------- DATA --------------
# ==============================
@st.cache_data(show_spinner=False)
def read_csv(file) -> pd.DataFrame:
    return pd.read_csv(file)

def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for c in NUMERIC_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def validate_schema(df: pd.DataFrame):
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        st.error(f"Missing required columns: {missing}")
        st.stop()

def first_non_null(s: pd.Series):
    s = s.dropna()
    return s.iloc[0] if not s.empty else None


# ---------------- Load from GitHub raw URL ----------------
@st.cache_data(show_spinner=False)
def load_data_from_github_raw(raw_url: str) -> pd.DataFrame:
    return pd.read_csv(raw_url)

raw_url = st.secrets.get("data", {}).get("url")
if not raw_url:
    st.error("Missing data.url in secrets. Add your raw GitHub CSV URL under [data].")
    st.stop()

try:
    df = load_data_from_github_raw(raw_url)
except Exception as e:
    st.error(f"Failed to load CSV from GitHub raw URL.\n{e}")
    st.stop()

validate_schema(df)
df = coerce_numeric(df)

# ==============================
# --------- FILTERS ------------
# ==============================
with st.sidebar:
    st.subheader("Filters")
    symbols = sorted(df["nsesymbol"].dropna().unique())
    sel_symbol = st.selectbox("Company (nsesymbol)", options=symbols, index=0)

    all_brokers = sorted(df["broker_name"].dropna().unique())
    sel_brokers = st.multiselect("Brokers", options=all_brokers, default=all_brokers)

    all_picked = sorted(df["picked_type"].dropna().unique())
    sel_picked = st.multiselect("picked_type", options=all_picked, default=all_picked)

    flag_vals = ["Beat","Miss","Inline"]
    sel_sales_flag   = st.multiselect("sales_flag",  options=flag_vals, default=flag_vals)
    sel_pat_flag     = st.multiselect("pat_flag",    options=flag_vals, default=flag_vals)
    sel_ebitda_flag  = st.multiselect("ebitda_flag", options=flag_vals, default=flag_vals)
    sel_overall_flag = st.multiselect("overall_flag",options=flag_vals, default=flag_vals)

# Apply filters
f = df[
    (df["broker_name"].isin(sel_brokers)) &
    (df["picked_type"].isin(sel_picked)) &
    (df["sales_flag"].isin(sel_sales_flag)) &
    (df["pat_flag"].isin(sel_pat_flag)) &
    (df["ebitda_flag"].isin(sel_ebitda_flag)) &
    (df["overall_flag"].isin(sel_overall_flag))
].copy()

cmp = f[f["nsesymbol"] == sel_symbol].copy()
if cmp.empty:
    st.warning("No rows for selected company with these filters.")
    st.stop()

# ==============================
# -------- HERO ----------------
# ==============================
st.markdown(
    f"""
    <div style="padding:20px;border-radius:16px;
                background:linear-gradient(135deg,#0ea5e9,#3b82f6);color:#fff;">
        <h1 style="margin:0;">📊 Results vs Broker Expectations</h1>
        <p style="opacity:.9;">Actual vs Expected with Beat/Inline/Miss analysis</p>
        <div style="font-size:12px;">Logged in as <b>{st.session_state['auth_user']}</b></div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =====================================================================
# ✅ NEW: SUMMARY TABLE (your requested screenshot format)
# =====================================================================

def build_summary_table(cmp: pd.DataFrame):
    """Builds a 1-row summary table exactly like the screenshot."""

    # Actual values
    actual_sales  = first_non_null(cmp["sales"])
    actual_ebitda = first_non_null(cmp["ebitda"])
    actual_pat    = first_non_null(cmp["pat"])

    actual_margin = (actual_ebitda / actual_sales * 100) if pd.notna(actual_sales) else None

    # Expected (average)
    exp_sales  = cmp["expected_sales"].mean()
    exp_ebitda = cmp["expected_ebitda"].mean()
    exp_pat    = cmp["expected_pat"].mean()

    exp_margin = (exp_ebitda / exp_sales * 100) if pd.notna(exp_sales) else None

    # Diff functions
    def pct_diff(a, e):
        if pd.isna(a) or pd.isna(e) or e == 0:
            return None
        return (a / e - 1) * 100

    def bps(a, e):
        if pd.isna(a) or pd.isna(e):
            return None
        return (a - e) * 100  # convert % → basis points

    # Differences
    sales_diff  = pct_diff(actual_sales, exp_sales)
    pat_diff    = pct_diff(actual_pat, exp_pat)
    ebitda_diff = pct_diff(actual_ebitda, exp_ebitda)
    margin_diff = bps(actual_margin, exp_margin)

    # Beat flags
    sales_flag  = int((cmp["sales_flag"] == "Beat").any())
    pat_flag    = int((cmp["pat_flag"] == "Beat").any())
    ebitda_flag = int((cmp["ebitda_flag"] == "Beat").any())

    total_flag = sales_flag + pat_flag + ebitda_flag

    # Build output
    return pd.DataFrame([{
        "Company": sel_symbol,

        "Exp Sales": exp_sales,
        "Exp PAT": exp_pat,
        "Exp EBITDA": exp_ebitda,
        "Exp EBITDA Margin %": exp_margin,

        "Act Sales": actual_sales,
        "Act PAT": actual_pat,
        "Act EBITDA": actual_ebitda,
        "Act EBITDA Margin %": actual_margin,

        "Sales Diff %": sales_diff,
        "PAT Diff %": pat_diff,
        "EBITDA Diff %": ebitda_diff,
        "Margin Diff (bps)": margin_diff,

        "Beat Sales": sales_flag,
        "Beat PAT": pat_flag,
        "Beat EBITDA": ebitda_flag,
        "Beat Total": total_flag,
    }])


summary_table = build_summary_table(cmp)

st.markdown("### 📘 Summary Table (Expected vs Actual vs Comparison)")
st.dataframe(
    summary_table.style.format({
        "Exp Sales": "{:,.2f}",
        "Exp PAT": "{:,.2f}",
        "Exp EBITDA": "{:,.2f}",
        "Exp EBITDA Margin %": "{:,.2f}",
        "Act Sales": "{:,.2f}",
        "Act PAT": "{:,.2f}",
        "Act EBITDA": "{:,.2f}",
        "Act EBITDA Margin %": "{:,.2f}",
        "Sales Diff %": "{:+.2f}",
        "PAT Diff %": "{:+.2f}",
        "EBITDA Diff %": "{:+.2f}",
        "Margin Diff (bps)": "{:+.0f}",
    }),
    use_container_width=True,
)


# ==============================
# REMAINING ORIGINAL CHARTS (unchanged)
# ==============================

# Metrics display
actual_sales  = first_non_null(cmp["sales"])
actual_ebitda = first_non_null(cmp["ebitda"])
actual_pat    = first_non_null(cmp["pat"])

avg_exp_sales  = cmp["expected_sales"].mean()
avg_exp_ebitda = cmp["expected_ebitda"].mean()
avg_exp_pat    = cmp["expected_pat"].mean()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Actual Sales", f"{actual_sales:,.2f}")
m2.metric("Avg Expected Sales", f"{avg_exp_sales:,.2f}")
m3.metric("Avg Expected EBITDA", f"{avg_exp_ebitda:,.2f}")
m4.metric("Avg Expected PAT", f"{avg_exp_pat:,.2f}")

# ==============================
# Charts preserved (minimal change)
# ==============================

st.markdown("### 📈 Actual vs Brokers’ Expected")

exp_by_broker = (
    cmp.groupby("broker_name", as_index=False)[
        ["expected_sales","expected_ebitda","expected_pat"]
    ].mean()
)

# Build chart DF
rows = [
    {"metric": "sales",  "series": "Actual", "value": actual_sales},
    {"metric": "ebitda", "series": "Actual", "value": actual_ebitda},
    {"metric": "pat",    "series": "Actual", "value": actual_pat},
]

for _, r in exp_by_broker.iterrows():
    rows.append({"metric": "sales",  "series": f"Expected · {r['broker_name']}", "value": r["expected_sales"]})
    rows.append({"metric": "ebitda", "series": f"Expected · {r['broker_name']}", "value": r["expected_ebitda"]})
    rows.append({"metric": "pat",    "series": f"Expected · {r['broker_name']}", "value": r["expected_pat"]})

plot_df = pd.DataFrame(rows)

fig1 = px.bar(
    plot_df,
    x="metric",
    y="value",
    color="series",
    barmode="group",
)
st.plotly_chart(fig1, use_container_width=True)

# Beat values
st.markdown("### 📊 Beat values (%)")

beat_long = cmp.melt(
    id_vars=["broker_name"],
    value_vars=["sales_beat", "ebitda_beat", "pat_beat"],
    var_name="metric",
    value_name="percent_value"
)

fig2 = px.bar(
    beat_long,
    x="metric",
    y="percent_value",
    color="broker_name",
    barmode="group",
)
st.plotly_chart(fig2, use_container_width=True)

# ==============================
# Tables
# ==============================
tab1, tab2 = st.tabs(["📋 Selected Company Table", "📄 Full Filtered Data"])

with tab1:
    st.dataframe(cmp, use_container_width=True)

with tab2:
    st.dataframe(f, use_container_width=True)
    st.download_button(
        "⬇️ Download filtered CSV",
        data=f.to_csv(index=False).encode("utf-8"),
        file_name=f"filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

st.caption("Built for clarity: Actual vs expected, plus Beat/Inline/Miss distribution.")
