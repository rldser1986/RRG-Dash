"""RRG Dashboard — Streamlit entry point."""

import math
import os
from datetime import datetime

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from streamlit_autorefresh import st_autorefresh

from src.engine import run as engine_run
from src.db import save_results, get_latest, get_by_date, get_tail, get_available_dates

AUTOREFRESH_INTERVAL_MS = 60 * 60 * 1000  # 60 minutes

# ---------------------------------------------------------------------------
# Ticker definitions
# ---------------------------------------------------------------------------
INDICES = ["SPY", "QQQ", "IWM", "DIA"]

SECTORS = {
    "XLB": "Materials", "XLC": "Communication", "XLE": "Energy",
    "XLF": "Financials", "XLI": "Industrials", "XLK": "Technology",
    "XLP": "Consumer Staples", "XLRE": "Real Estate", "XLU": "Utilities",
    "XLV": "Health Care", "XLY": "Consumer Discretionary",
}

BENCHMARK_OPTIONS = ["SPY", "QQQ", "IWM", "RSP", "VTV", "VUG", "DIA", "EFA", "EEM"]
BENCHMARK_LABELS = {
    "SPY": "SPY — S&P 500",
    "QQQ": "QQQ — Nasdaq 100",
    "IWM": "IWM — Russell 2000",
    "RSP": "RSP — Equal-Weight S&P",
    "VTV": "VTV — Value",
    "VUG": "VUG — Growth",
    "DIA": "DIA — Dow 30",
    "EFA": "EFA — Intl Developed",
    "EEM": "EEM — Emerging Markets",
    # Sector ETFs (Individual view only)
    "XLK": "XLK — Technology",
    "XLV": "XLV — Health Care",
    "XLF": "XLF — Financials",
    "XLE": "XLE — Energy",
    "XLI": "XLI — Industrials",
    "XLY": "XLY — Consumer Disc.",
    "XLP": "XLP — Consumer Staples",
    "XLU": "XLU — Utilities",
    "XLC": "XLC — Communication",
    "XLRE": "XLRE — Real Estate",
    "XLB": "XLB — Materials",
    "_SEP_": "── Sector ETFs ──",
}
INDIVIDUAL_BENCHMARK_OPTIONS = (
    BENCHMARK_OPTIONS
    + ["_SEP_"]
    + ["XLK", "XLV", "XLF", "XLE", "XLI", "XLY", "XLP", "XLU", "XLC", "XLRE", "XLB"]
)

QUADRANT_COLORS = {
    "Leading": "#00C853",
    "Weakening": "#FF9100",
    "Lagging": "#FF1744",
    "Improving": "#2979FF",
}

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="RRG Dashboard", layout="wide")

# ---------------------------------------------------------------------------
# Cached data pipeline
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Fetching & computing RRG data...", ttl=3600)
def fetch_and_store(tickers: tuple, benchmark: str) -> str:
    """Fetch prices, compute RRG, save to SQLite, return timestamp."""
    df = engine_run(list(tickers), benchmark)
    if not df.empty:
        save_results(df)
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


SP500_CSV = os.path.join(os.path.dirname(__file__), "data", "sp500_tickers.csv")


@st.cache_data
def load_ticker_csv() -> pd.DataFrame:
    """Load sp500_tickers.csv into a DataFrame. Returns empty DF if missing."""
    if not os.path.exists(SP500_CSV):
        return pd.DataFrame()
    return pd.read_csv(SP500_CSV)


@st.cache_data
def load_ticker_options() -> list[str]:
    """Return formatted options: 'TICKER — Company'."""
    df = load_ticker_csv()
    if df.empty:
        return []
    return [f"{row.Symbol} — {row.Company}" for _, row in df.iterrows()]

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("RRG Dashboard")

view = st.sidebar.radio("View", ["Indices", "Sectors", "Individual"])

if view == "Indices":
    benchmark = "SPY"
    tickers = [t for t in INDICES if t != benchmark]
    st.sidebar.caption(f"Benchmark: {benchmark}")
elif view == "Sectors":
    benchmark = st.sidebar.selectbox("Benchmark", BENCHMARK_OPTIONS, format_func=lambda t: BENCHMARK_LABELS[t], key="bench_sectors")
    tickers = list(SECTORS.keys())
    tickers = [t for t in tickers if t != benchmark]
else:  # Individual
    ticker_options = load_ticker_options()
    ticker_csv = load_ticker_csv()

    default_selections = [
        "AAPL — Apple Inc.",
        "MSFT — Microsoft",
        "GOOGL — Alphabet Inc. (Class A)",
        "NVDA — Nvidia",
    ]
    # Support URL query params: ?tickers=AAPL,MSFT,NVDA
    url_tickers = st.query_params.get("tickers", "")
    if url_tickers and ticker_options:
        url_syms = [s.strip().upper() for s in url_tickers.split(",") if s.strip()]
        sym_to_opt = {opt.split(" — ")[0]: opt for opt in ticker_options}
        default_selections = [sym_to_opt[s] for s in url_syms if s in sym_to_opt]

    # Initialise session_state for multiselect (allows button injection)
    if "individual_tickers" not in st.session_state:
        st.session_state["individual_tickers"] = default_selections

    # Merge any pending addition from "Add to watchlist" button
    pending = st.session_state.pop("_pending_ticker", None)
    if pending and pending not in st.session_state["individual_tickers"]:
        st.session_state["individual_tickers"] = st.session_state["individual_tickers"] + [pending]

    if ticker_options:
        selected = st.sidebar.multiselect(
            "Select stocks",
            options=ticker_options,
            key="individual_tickers",
            help="Type to search by ticker or company name",
        )
        tickers = [s.split(" — ")[0] for s in selected]
    else:
        # Fallback if CSV not generated yet
        custom_input = st.sidebar.text_input(
            "Tickers (comma-separated)", value="AAPL, NVDA, MSFT, GOOGL"
        )
        tickers = [t.strip().upper() for t in custom_input.split(",") if t.strip()]

    # --- Browse by Sector expander ---
    if not ticker_csv.empty:
        # Exclude benchmarks from sector browsing
        stock_df = ticker_csv[ticker_csv["GICS Sector"] != "Benchmark"].copy()
        sectors_list = sorted(stock_df["GICS Sector"].dropna().unique().tolist())

        with st.sidebar.expander("Browse by Sector"):
            sel_sector = st.selectbox("Sector", sectors_list, key="browse_sector")
            industries_in_sector = sorted(
                stock_df.loc[stock_df["GICS Sector"] == sel_sector, "GICS Sub-Industry"]
                .dropna().unique().tolist()
            )
            sel_industry = st.selectbox("Industry", industries_in_sector, key="browse_industry")
            stocks_in_industry = stock_df[stock_df["GICS Sub-Industry"] == sel_industry]
            stock_opts = [
                f"{r.Symbol} — {r.Company}"
                for _, r in stocks_in_industry.iterrows()
            ]
            sel_stock = st.selectbox("Stock", stock_opts, key="browse_stock")

            if st.button("Add to watchlist"):
                if sel_stock:
                    st.session_state["_pending_ticker"] = sel_stock
                    st.rerun()

    benchmark = st.sidebar.selectbox("Benchmark", INDIVIDUAL_BENCHMARK_OPTIONS, format_func=lambda t: BENCHMARK_LABELS[t], key="bench_individual")
    if benchmark == "_SEP_":
        benchmark = "SPY"
    tickers = [t for t in tickers if t != benchmark]

# ---------------------------------------------------------------------------
# Display options
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
compact_mode = st.sidebar.checkbox("Compact Mode", value=False)
tail_weeks = st.sidebar.slider("Tail Length (weeks)", min_value=3, max_value=10, value=3)

# ---------------------------------------------------------------------------
# Refresh Data button + Auto-Refresh
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")

# Show toast confirmation from previous rerun (flag set before st.rerun)
if st.session_state.get("_show_refresh_toast"):
    st.toast("Data refreshed!", icon="\u2705")
    st.session_state["_show_refresh_toast"] = False

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.session_state["last_refresh"] = datetime.now()
    st.session_state["_show_refresh_toast"] = True
    st.rerun()

auto_refresh = st.sidebar.toggle("Auto-Refresh (60 min)", value=False)

if auto_refresh:
    tick = st_autorefresh(interval=AUTOREFRESH_INTERVAL_MS, key="rrg_autorefresh")
    # tick > 0 means an auto-refresh just fired (not the initial page load)
    if tick > 0:
        st.cache_data.clear()
        st.session_state["last_refresh"] = datetime.now()

if not tickers:
    st.warning("Enter at least one ticker to display.")
    st.stop()

# ---------------------------------------------------------------------------
# Run pipeline (cached) — returns timestamp
# ---------------------------------------------------------------------------
last_updated = fetch_and_store(tuple(sorted(tickers)), benchmark)

# ---------------------------------------------------------------------------
# Last Updated timestamp + countdown
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
# Persist the last refresh time in session state so it survives reruns
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = datetime.now()

refresh_ts: datetime = st.session_state["last_refresh"]
st.sidebar.caption(f"Last refreshed: {refresh_ts.strftime('%Y-%m-%d %H:%M:%S')} UTC")

if auto_refresh:
    elapsed = datetime.now() - refresh_ts
    remaining_min = max(0, 60 - int(elapsed.total_seconds() // 60))
    st.sidebar.caption(f"Next refresh in: ~{remaining_min} min")

# ---------------------------------------------------------------------------
# Lookback slider
# ---------------------------------------------------------------------------
available_dates = get_available_dates(benchmark)

# Filter to dates that have data for our current tickers
if not available_dates:
    st.error("No data in database. Check your network connection and try again.")
    st.stop()

use_lookback = st.sidebar.checkbox("Lookback mode", value=False)

if use_lookback and len(available_dates) > 1:
    selected_date = st.sidebar.select_slider(
        "Date",
        options=available_dates,
        value=available_dates[-1],
    )
    snapshot = get_by_date(selected_date, benchmark)
    # Filter to current tickers only
    snapshot = snapshot[snapshot["ticker"].isin(tickers)]
else:
    selected_date = available_dates[-1]
    snapshot = get_latest(benchmark)
    snapshot = snapshot[snapshot["ticker"].isin(tickers)]

if snapshot.empty:
    st.warning("No RRG data for the selected tickers / date.")
    st.stop()

# ---------------------------------------------------------------------------
# Global CSS overrides
# ---------------------------------------------------------------------------
if compact_mode:
    st.markdown(
        "<style>"
        "  .block-container { padding-top: 1rem; }"
        "  .stDataFrame td, .stDataFrame th { font-size: 1.05rem !important; }"
        "</style>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Precompute tails (used by both chart and velocity table)
# ---------------------------------------------------------------------------
tails: dict[str, pd.DataFrame] = {}
# In lookback mode, tails must end at the selected date (not the latest)
_tail_cutoff = selected_date if use_lookback else None
for _, row in snapshot.iterrows():
    tails[row["ticker"]] = get_tail(row["ticker"], benchmark, tail_weeks,
                                     up_to_date=_tail_cutoff)

# ---------------------------------------------------------------------------
# Hero Plot
# ---------------------------------------------------------------------------
if compact_mode:
    st.markdown("### Relative Rotation Graph")
else:
    st.header("Relative Rotation Graph")

if use_lookback:
    st.caption(f"Date: {selected_date}  |  Benchmark: {benchmark}")
else:
    st.caption(f"Latest: {selected_date}  |  Benchmark: {benchmark}")

fig = go.Figure()

# Determine axis range from data (with padding)
all_ratios = snapshot["rs_ratio"].tolist()
all_momenta = snapshot["rs_momentum"].tolist()
for tail in tails.values():
    all_ratios.extend(tail["rs_ratio"].tolist())
    all_momenta.extend(tail["rs_momentum"].tolist())

pad = 0.5
x_min = min(all_ratios) - pad
x_max = max(all_ratios) + pad
y_min = min(all_momenta) - pad
y_max = max(all_momenta) + pad

# Quadrant background rectangles
fig.add_shape(type="rect", x0=100, x1=x_max + 10, y0=100, y1=y_max + 10,
              fillcolor="rgba(0,200,83,0.08)", line_width=0, layer="below")   # Leading
fig.add_shape(type="rect", x0=100, x1=x_max + 10, y0=y_min - 10, y1=100,
              fillcolor="rgba(255,145,0,0.08)", line_width=0, layer="below")  # Weakening
fig.add_shape(type="rect", x0=x_min - 10, x1=100, y0=y_min - 10, y1=100,
              fillcolor="rgba(255,23,68,0.08)", line_width=0, layer="below")  # Lagging
fig.add_shape(type="rect", x0=x_min - 10, x1=100, y0=100, y1=y_max + 10,
              fillcolor="rgba(41,121,255,0.08)", line_width=0, layer="below") # Improving

# Crosshairs at (100, 100)
fig.add_hline(y=100, line_dash="dot", line_color="gray", line_width=1)
fig.add_vline(x=100, line_dash="dot", line_color="gray", line_width=1)

# Quadrant labels
label_style = dict(font=dict(size=11, color="rgba(150,150,150,0.5)"), showarrow=False)
fig.add_annotation(x=x_max, y=y_max, text="Leading", xanchor="right", yanchor="top", **label_style)
fig.add_annotation(x=x_max, y=y_min, text="Weakening", xanchor="right", yanchor="bottom", **label_style)
fig.add_annotation(x=x_min, y=y_min, text="Lagging", xanchor="left", yanchor="bottom", **label_style)
fig.add_annotation(x=x_min, y=y_max, text="Improving", xanchor="left", yanchor="top", **label_style)

# Tails + current points
for _, row in snapshot.iterrows():
    ticker = row["ticker"]
    quadrant = row["quadrant"]
    color = QUADRANT_COLORS.get(quadrant, "gray")
    tail = tails[ticker]

    if len(tail) > 1:
        n_segments = len(tail) - 1
        for seg_i in range(n_segments):
            # Ramp opacity from 0.15 (oldest segment) to 1.0 (newest)
            if n_segments == 1:
                seg_opacity = 1.0
            else:
                seg_opacity = 0.15 + 0.85 * (seg_i / (n_segments - 1))
            fig.add_trace(go.Scatter(
                x=tail["rs_ratio"].iloc[seg_i:seg_i + 2],
                y=tail["rs_momentum"].iloc[seg_i:seg_i + 2],
                mode="lines",
                line=dict(color=color, width=1.5),
                opacity=seg_opacity,
                showlegend=False,
                hoverinfo="skip",
            ))

    marker_size = 8 if compact_mode else 10
    font_size = 10 if compact_mode else 11

    fig.add_trace(go.Scatter(
        x=[row["rs_ratio"]], y=[row["rs_momentum"]],
        mode="markers+text",
        marker=dict(size=marker_size, color=color, line=dict(width=1, color="white")),
        text=[ticker],
        textposition="top center",
        textfont=dict(size=font_size, color=color),
        name=f"{ticker} ({quadrant})",
        hovertemplate=(
            f"<b>{ticker}</b><br>"
            f"RS-Ratio: %{{x:.2f}}<br>"
            f"RS-Momentum: %{{y:.2f}}<br>"
            f"Quadrant: {quadrant}<extra></extra>"
        ),
    ))

chart_height = 400 if compact_mode else 600

fig.update_layout(
    xaxis_title="RS-Ratio",
    yaxis_title="RS-Momentum",
    xaxis=dict(range=[x_min, x_max], zeroline=False),
    yaxis=dict(range=[y_min, y_max], zeroline=False),
    height=chart_height,
    margin=dict(l=40, r=40, t=20, b=80),
    legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
    plot_bgcolor="rgba(0,0,0,0)",
)

st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ---------------------------------------------------------------------------
# Velocity Sort Table
# ---------------------------------------------------------------------------
if compact_mode:
    st.markdown("### Velocity Rankings")
else:
    st.subheader("Velocity Rankings")

velocity_rows = []
for _, row in snapshot.iterrows():
    ticker = row["ticker"]
    tail = tails[ticker]

    if len(tail) >= 2:
        oldest = tail.iloc[0]
        newest = tail.iloc[-1]
        dx = newest["rs_ratio"] - oldest["rs_ratio"]
        dy = newest["rs_momentum"] - oldest["rs_momentum"]
        velocity = math.sqrt(dx**2 + dy**2)
        # "Toward Leading" = net movement toward upper-right (positive dx + dy)
        toward = dx + dy > 0
    else:
        velocity = 0.0
        toward = False

    velocity_rows.append({
        "Ticker": ticker,
        "RS-Ratio": round(row["rs_ratio"], 2),
        "RS-Momentum": round(row["rs_momentum"], 2),
        "Quadrant": row["quadrant"],
        "Velocity": velocity,
        "toward": toward,
    })

vtable = pd.DataFrame(velocity_rows)
vtable = vtable.sort_values("Velocity", ascending=False).reset_index(drop=True)

# Build the display DataFrame (no Styler — avoids serialization issues on
# Streamlit Cloud).  Row highlighting is done with a leading emoji column.
vtable_display = pd.DataFrame()
vtable_display[""] = vtable["toward"].map({True: "\U0001f7e2", False: "\u26aa"})  # green circle / white circle
vtable_display["Ticker"] = vtable["Ticker"]
vtable_display["RS-Ratio"] = vtable["RS-Ratio"]
vtable_display["RS-Momentum"] = vtable["RS-Momentum"]
vtable_display["Quadrant"] = vtable["Quadrant"]

if compact_mode:
    # Arrow emoji inside Velocity column; no separate Direction column
    vtable_display["Velocity"] = vtable.apply(
        lambda r: f"{r['Velocity']:.3f} \u2197" if r["toward"] else f"{r['Velocity']:.3f} \u2198",
        axis=1,
    )
else:
    vtable_display["Velocity"] = vtable["Velocity"].round(3)
    vtable_display["Direction"] = vtable["toward"].map(
        {True: "Toward Leading", False: "Away from Leading"}
    )

column_config = {
    "": st.column_config.TextColumn("", width="small"),
    "RS-Ratio": st.column_config.NumberColumn("RS-Ratio", format="%.2f"),
    "RS-Momentum": st.column_config.NumberColumn("RS-Momentum", format="%.2f"),
}

if not compact_mode:
    column_config["Velocity"] = st.column_config.NumberColumn("Velocity", format="%.3f")

st.dataframe(
    vtable_display,
    use_container_width=True,
    hide_index=True,
    column_config=column_config,
)
