from __future__ import annotations
import threading
import time
import sqlite3
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from streamlit_flow import streamlit_flow
from streamlit_flow.elements import StreamlitFlowNode, StreamlitFlowEdge
from streamlit_flow.state import StreamlitFlowState
from streamlit_flow.layouts import TreeLayout

# --- Constants ---
EMISSION_FACTOR_KG_PER_KWH = 0.82  # Indonesia grid avg
GRID_TARIFF_IDR_PER_KWH = 1500     # PLN Bisnis estimate
INTERVAL = 60                      # Default polling interval in seconds

# --- Colour Palette ---
COLOR_PV = "#00cc00"        # Green for PV
COLOR_GRID = "#1e90ff"      # Blue for Grid
COLOR_BATTERY = "#ffa500"   # Orange for Battery
COLOR_LOAD = "#ff4500"      # Red for Load
COLOR_BACKGROUND = "#0d0d0d"
COLOR_SURFACE = "#1b1b1b"
COLOR_WHITE = "#ffffff"

# --- Initialization & Background Polling ---
def _initialize() -> None:
    """Initialize database and start scheduler job."""
    try:
        from db import init_db
        init_db()
    except ImportError:
        st.warning("Database module 'db' not found. Initialization skipped.")
    try:
        from scheduler import job
        job()
    except ImportError:
        st.warning("Scheduler module 'scheduler' not found. Job execution skipped.")
        global INTERVAL
        INTERVAL = 60

def _background_scheduler() -> None:
    """Run scheduler job periodically in a background thread."""
    while True:
        try:
            from scheduler import job
            job()
        except ImportError:
            st.warning("Scheduler module 'scheduler' not found.")
        time.sleep(INTERVAL)

# --- Styling ---
def _load_css() -> None:
    """Load custom CSS for dashboard styling with glassmorphism."""
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&family=Poppins:wght@300;500&display=swap');
    :root {{
      --pv:{COLOR_PV}; --grid:{COLOR_GRID}; --battery:{COLOR_BATTERY}; --load:{COLOR_LOAD};
      --bg:{COLOR_BACKGROUND}; --surf:{COLOR_SURFACE}; --white:{COLOR_WHITE};
      --blur:14px;
    }}
    body,.block-container{{background:var(--bg)!important;color:var(--white)!important;font-family:'Poppins',sans-serif!important;}}
    h1,h2,h3,h4,.css-10trblm{{font-family:'Montserrat',sans-serif!important;color:var(--pv)!important;}}
    .kpi-card{{background:var(--white);color:#000;border-radius:20px;box-shadow:0 8px 28px rgba(0,0,0,.25);padding:1.2rem 1.4rem;display:flex;flex-direction:column;align-items:center;transition:transform .25s;}}
    .kpi-card:hover{{transform:translateY(-6px);}}
    .kpi-card h3{{margin:0;font-size:.9rem;font-weight:600;color:#333}}
    .kpi-card p{{margin:0;font-size:1.65rem;font-weight:700}}
    .glass-card{{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.18);backdrop-filter:blur(var(--blur));border-radius:18px;padding:1.5rem 1.7rem;box-shadow:0 6px 24px rgba(0,0,0,.35);}}
    .stTabs [role=tablist]>button{{background:var(--surf);border:none;color:var(--white);padding:.6rem 1.2rem;margin-right:4px;font-family:'Montserrat',sans-serif;font-weight:500;border-radius:10px 10px 0 0;}}
    .stTabs [role=tablist]>button[aria-selected='true']{{background:var(--pv);}}
    .stButton>button{{background:linear-gradient(90deg,var(--pv),var(--grid));color:var(--white);border:none;border-radius:10px;font-weight:600;padding:.5rem 1.2rem;}}
    .stButton>button:hover{{filter:brightness(1.1)}}
    ::-webkit-scrollbar{{width:8px;}}::-webkit-scrollbar-thumb{{background:var(--pv);border-radius:4px;}}
    </style>""", unsafe_allow_html=True)

# --- Data Fetching ---
@st.cache_data(ttl=60)
def _get_latest_data(device_sn: str) -> tuple[datetime | None, dict]:
    """Fetch the latest data for a specific device from the database."""
    try:
        with sqlite3.connect("satu_energy.db") as conn:
            df = pd.read_sql_query(
                "SELECT key, value, unit, timestamp FROM device_data WHERE device_sn=? ORDER BY timestamp DESC",
                conn, params=(device_sn,))
        if df.empty:
            return None, {}
        latest_ts = df["timestamp"].max()
        raw_data = {row["key"]: {"value": row["value"], "unit": row["unit"]}
                    for _, row in df[df["timestamp"] == latest_ts].iterrows()}
        return latest_ts, raw_data
    except sqlite3.Error as e:
        st.error(f"Database error: {e}")
        return None, {}

@st.cache_data(ttl=60)
def _get_historical(device_sn: str, key: str, since: datetime) -> pd.DataFrame:
    """Fetch historical data for a specific key and device since a given time."""
    try:
        with sqlite3.connect("satu_energy.db") as conn:
            df = pd.read_sql_query(
                "SELECT timestamp, value FROM device_data WHERE device_sn=? AND key=? AND timestamp>=? ORDER BY timestamp",
                conn, params=(device_sn, key, since))
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    except sqlite3.Error as e:
        st.error(f"Database error: {e}")
        return pd.DataFrame()

# --- UI Components ---
def _kpi(label: str, value: str, delta: str | None = None) -> None:
    """Display a KPI card with label, value, and optional delta."""
    delta_html = f"<span style='font-size:.8rem;color:{COLOR_BATTERY}'>({delta})</span>" if delta else ""
    st.markdown(f"<div class='kpi-card'><h3>{label}</h3><p>{value} {delta_html}</p></div>", unsafe_allow_html=True)

def _plot_area(df: pd.DataFrame, y_title: str, height: int = 200) -> go.Figure:
    """Create an area plot from a DataFrame."""
    fig = go.Figure(go.Scatter(
        x=df["timestamp"], y=df["value"], mode="lines",
        line=dict(color=COLOR_PV, width=2),
        fill="tozeroy", fillcolor="rgba(0,204,0,.22)",
        hovertemplate="%{x|%d %b %Y %H:%M}<br>%{y:.2f} " + y_title + "<extra></extra>"))
    fig.update_layout(height=height, template="plotly_dark",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, yaxis_title=y_title)
    return fig

# --- Energy Flow Logic ---
def calculate_flows(raw_data: dict) -> dict[str, float]:
    """Calculate energy flows based on raw data in kW."""
    pv_power = float(raw_data.get("TotalSolarPower", {"value": 0})["value"])
    load_power = float(raw_data.get("TotalConsumptionPower", {"value": 0})["value"])
    grid_power = float(raw_data.get("TotalGridPower", {"value": 0})["value"])  # Positive: import, Negative: export
    battery_power = float(raw_data.get("BatteryPower", {"value": 0})["value"])  # Positive: discharge, Negative: charge

    flows = {
        "PV to Load": 0.0,
        "PV to Battery": 0.0,
        "PV to Grid": 0.0,
        "Grid to Load": 0.0,
        "Grid to Battery": 0.0,
        "Battery to Load": 0.0,
        "Battery to Grid": 0.0,
        "Load to Grid": 0.0,
    }

    # Distribute PV power
    if pv_power > 0:
        flows["PV to Load"] = min(pv_power, load_power)
        pv_power -= flows["PV to Load"]
        load_power -= flows["PV to Load"]

        if battery_power < 0 and pv_power > 0:
            flows["PV to Battery"] = min(pv_power, -battery_power)
            pv_power -= flows["PV to Battery"]
            battery_power += flows["PV to Battery"]

        if pv_power > 0:
            flows["PV to Grid"] = pv_power

    # Handle remaining load
    if load_power > 0:
        if battery_power > 0:
            flows["Battery to Load"] = min(battery_power, load_power)
            load_power -= flows["Battery to Load"]
            battery_power -= flows["Battery to Load"]

        if load_power > 0:
            flows["Grid to Load"] = load_power

    # Battery charging from grid
    if battery_power < 0:
        flows["Grid to Battery"] = -battery_power

    # Excess battery to grid
    if battery_power > 0:
        flows["Battery to Grid"] = battery_power

    # Convert to kW
    for key in flows:
        flows[key] /= 1000

    return {k: v for k, v in flows.items() if v > 0}

def generate_flow_elements(raw_data: dict) -> tuple[list[StreamlitFlowNode], list[StreamlitFlowEdge]]:
    """Generate nodes and edges for the energy flow diagram."""
    active_flows = calculate_flows(raw_data)

    nodes = [
        StreamlitFlowNode("pv", (0, 0), {'content': f"🔆 **PV**\n{raw_data.get('TotalSolarPower', {'value': 0})['value']} W", 'style': {'backgroundColor': COLOR_PV, 'color': COLOR_WHITE}}, 'default', 'bottom'),
        StreamlitFlowNode("battery", (0, 0), {'content': f"🔋 **Battery**\n{raw_data.get('BatteryPower', {'value': 0})['value']} W\nSOC: {raw_data.get('SOC', {'value': 0})['value']}%", 'style': {'backgroundColor': COLOR_BATTERY, 'color': COLOR_WHITE}}, 'default', 'top', 'bottom'),
        StreamlitFlowNode("grid", (0, 0), {'content': f"⚡ **Grid**\n{raw_data.get('TotalGridPower', {'value': 0})['value']} W", 'style': {'backgroundColor': COLOR_GRID, 'color': COLOR_WHITE}}, 'default', 'top', 'bottom'),
        StreamlitFlowNode("load", (0, 0), {'content': f"🏠 **Load**\n{raw_data.get('TotalConsumptionPower', {'value': 0})['value']} W", 'style': {'backgroundColor': COLOR_LOAD, 'color': COLOR_WHITE}}, 'default', 'top'),
    ]

    edges = []
    flow_mapping = {
        "PV to Load": ("pv", "load", COLOR_PV),
        "PV to Battery": ("pv", "battery", COLOR_PV),
        "PV to Grid": ("pv", "grid", COLOR_PV),
        "Grid to Load": ("grid", "load", COLOR_GRID),
        "Grid to Battery": ("grid", "battery", COLOR_GRID),
        "Battery to Load": ("battery", "load", COLOR_BATTERY),
        "Battery to Grid": ("battery", "grid", COLOR_BATTERY),
        "Load to Grid": ("load", "grid", COLOR_LOAD),
    }
    for flow_name, (source, target, color) in flow_mapping.items():
        if flow_name in active_flows:
            edge_id = f"{source}_to_{target}"
            edge_label = f"{active_flows[flow_name]:.2f} kW"
            edges.append(StreamlitFlowEdge(edge_id, source, target, label=edge_label, animated=True, style={'stroke': color, 'strokeWidth': '3px'}))

    return nodes, edges

# --- Main Application ---
def main() -> None:
    """Run the Satu.Energy Elite Dashboard."""
    _initialize()
    threading.Thread(target=_background_scheduler, daemon=True).start()
    st.set_page_config("Satu.Energy Elite Dashboard", "⚡", "wide")
    _load_css()

    st.title("Satu.Energy Elite Dashboard")

    # Sidebar
    with sqlite3.connect("satu_energy.db") as conn:
        devices = [row[0] for row in conn.execute("SELECT DISTINCT device_sn FROM device_meta").fetchall()]
    search = st.sidebar.text_input("🔍 Search Devices", "")
    devices = [d for d in devices if search.lower() in d.lower()]
    if not devices:
        st.sidebar.warning("No device matched")
        st.stop()
    device_sn = st.sidebar.selectbox("Select Device", devices)

    latest_ts, raw_data = _get_latest_data(device_sn)
    if not raw_data:
        st.sidebar.info("Waiting for data…")
        st.stop()

    last_update = pd.to_datetime(latest_ts)
    now = datetime.utcnow()
    is_online = (now - last_update).total_seconds() < 60
    st.sidebar.markdown(f"**Last Update:** {last_update:%Y-%m-%d %H:%M:%S} UTC")
    st.sidebar.markdown(f"**Status:** :{'green' if is_online else 'red'}[{'Online' if is_online else 'Offline'}]")

    period = st.sidebar.select_slider("Trend Period", ["1h", "6h", "12h", "24h", "7d"], "24h")
    since = now - (timedelta(days=7) if period == "7d" else timedelta(hours=int(period[:-1])))

    tab_over, tab_pv, tab_grid, tab_trend, tab_ins = st.tabs(
        ["🏠 Overview", "☀️ PV Details", "🔌 Grid & Battery", "📈 Trends", "💡 Insights"])

    # Overview Tab
    with tab_over:
        st.markdown(f"<div class='glass-card'><h3>Device Overview – {device_sn}</h3></div>", unsafe_allow_html=True)
        nodes, edges = generate_flow_elements(raw_data)

        if 'flow_state' not in st.session_state:
            st.session_state.flow_state = StreamlitFlowState(nodes, edges)
        else:
            st.session_state.flow_state.nodes = nodes
            st.session_state.flow_state.edges = edges

        if edges:
            st.session_state.flow_state = streamlit_flow('energy_flow', st.session_state.flow_state, layout=TreeLayout(direction='down'), fit_view=True, height=600)
        else:
            st.info("No active energy flows at the moment.")

        k1, k2, k3 = st.columns(3)
        def _delta(key: str) -> float | None:
            hist = _get_historical(device_sn, key, since)
            return None if hist.empty else float(raw_data[key]["value"]) - hist.iloc[0]["value"]

        for col, section, metrics in [
            (k1, "Production", [("DailyActiveProduction", "kWh"), ("TotalActiveProduction", "kWh"), ("TotalSolarPower", "W")]),
            (k2, "Consumption", [("DailyConsumption", "kWh"), ("TotalConsumption", "kWh")]),
            (k3, "Grid & Battery", [("TotalGridPower", "W"), ("SOC", "%")]),
        ]:
            with col:
                st.subheader(section)
                for key, unit in metrics:
                    val = raw_data.get(key, {"value": "-", "unit": unit})
                    delta = _delta(key) if key.startswith("Daily") else None
                    _kpi(key.replace("Daily", "Dly "), f"{val['value']} {val['unit']}", f"{delta:.1f} {unit}" if delta else None)

    # PV Details Tab
    with tab_pv:
        st.markdown("<div class='glass-card'><h3>PV Input Overview</h3></div>", unsafe_allow_html=True)
        for i in range(1, 5):
            with st.expander(f"☀️ PV{i} Details", expanded=(i == 1)):
                for metric, label in [("DCVoltagePV", "Voltage"), ("DCCurrentPV", "Current"), ("DCPowerPV", "Power")]:
                    val = raw_data.get(f"{metric}{i}", {})
                    st.write(f"**{label}:** {val.get('value')} {val.get('unit')}")
                df = _get_historical(device_sn, f"DCPowerPV{i}", since)
                if not df.empty:
                    st.plotly_chart(_plot_area(df, "W"), use_container_width=True, key=f"pv{i}")

    # Grid & Battery Tab
    with tab_grid:
        st.markdown("<div class='glass-card'><h3>Grid & Battery Metrics</h3></div>", unsafe_allow_html=True)
        rows = [{"Phase": ph,
                 "Voltage (V)": raw_data.get(f"GridVoltage{ph}", {}).get("value"),
                 "Current (A)": raw_data.get(f"GridCurrent{ph}", {}).get("value"),
                 "Power (W)": raw_data.get(f"GridPower{ph}", {}).get("value")}
                for ph in ["L1", "L2", "L3"]]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        soc_value = float(raw_data.get("SOC", {"value": 0})["value"])
        gauge = go.Figure(go.Indicator(mode="gauge+number", value=soc_value,
                                       gauge={"axis": {"range": [0, 100]}, "bar": {"color": COLOR_BATTERY}}))
        gauge.update_layout(height=320, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(gauge, use_container_width=True, key="soc_gauge")

    # Trends Tab
    with tab_trend:
        st.markdown("<div class='glass-card'><h3>Parameter Trends</h3></div>", unsafe_allow_html=True)
        param = st.selectbox("Select Parameter", list(raw_data.keys()))
        chart_type = st.radio("Chart Type", ["Line", "Bar"], horizontal=True)
        df = _get_historical(device_sn, param, since)
        if not df.empty:
            fig = (_plot_area(df, raw_data[param]["unit"], 330) if chart_type == "Line" else
                   px.bar(df, x="timestamp", y="value", color_discrete_sequence=[COLOR_PV])
                   .update_layout(height=330, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)"))
            st.plotly_chart(fig, use_container_width=True, key="trend")

    # Insights Tab
    with tab_ins:
        st.markdown("<div class='glass-card'><h3>Actionable Insights</h3></div>", unsafe_allow_html=True)
        daily_prod = float(raw_data.get("DailyActiveProduction", {"value": 0})["value"])
        daily_cons = float(raw_data.get("DailyConsumption", {"value": 0})["value"])
        daily_buy = float(raw_data.get("DailyEnergyBuy", {"value": 0})["value"])
        daily_sell = float(raw_data.get("DailyEnergySell", {"value": 0})["value"])
        net_energy = daily_prod - daily_cons
        soc = float(raw_data.get("SOC", {"value": 0})["value"])

        col_a, col_b, col_c, col_d, col_e = st.columns(5)
        col_a.metric("Net Energy", f"{net_energy:+.1f} kWh")
        col_b.metric("CO₂ Avoided", f"{daily_prod * EMISSION_FACTOR_KG_PER_KWH:,.0f} kg")
        col_c.metric("Grid Saved", f"Rp{(daily_prod - daily_sell) * GRID_TARIFF_IDR_PER_KWH:,.0f}")
        col_d.metric("Self-Cons.", f"{(daily_prod - daily_sell) / (daily_prod + 1e-6) * 100:.0f}%")
        col_e.metric("Battery SOC", f"{soc:.0f}%")

        self_cons_ratio = (daily_prod - daily_sell) / (daily_prod + 1e-6) * 100
        self_suff_ratio = (daily_prod - daily_sell) / (daily_cons + 1e-6) * 100
        st.progress(min(max(int(self_cons_ratio), 0), 100), text="Self-Consumption")
        st.progress(min(max(int(self_suff_ratio), 0), 100), text="Self-Sufficiency")

        since_7d = now - timedelta(days=7)
        prod_7d = _get_historical(device_sn, "DailyActiveProduction", since_7d)
        cons_7d = _get_historical(device_sn, "DailyConsumption", since_7d)
        if not prod_7d.empty and not cons_7d.empty:
            prod_daily = prod_7d.set_index("timestamp").resample("D").sum()
            cons_daily = cons_7d.set_index("timestamp").resample("D").sum()
            df_7d = pd.DataFrame({"Prod": prod_daily["value"], "Cons": cons_daily["value"]}).fillna(0)
            df_7d["Net"] = df_7d["Prod"] - df_7d["Cons"]
            df_7d["CO2"] = df_7d["Prod"] * EMISSION_FACTOR_KG_PER_KWH
            df_7d["Cum_CO2"] = df_7d["CO2"].cumsum()

            g1, g2, g3 = st.columns((1.6, 1.1, 1.3))
            fig_bal = go.Figure()
            fig_bal.add_trace(go.Scatter(x=df_7d.index, y=df_7d["Prod"], name="Prod", line=dict(width=0), stackgroup="one", fillcolor="rgba(0,204,0,.5)"))
            fig_bal.add_trace(go.Scatter(x=df_7d.index, y=df_7d["Cons"], name="Cons", line=dict(width=0), stackgroup="one", fillcolor="rgba(30,144,255,.55)"))
            fig_bal.update_layout(height=240, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=1.1, x=0.05))
            g1.plotly_chart(fig_bal, use_container_width=True, key="balance")

            fig_net = px.bar(df_7d, x=df_7d.index, y="Net", color="Net", color_continuous_scale=[(0, "#ff4d4d"), (0.5, "#ffdd4d"), (1, COLOR_PV)])
            fig_net.update_layout(height=240, template="plotly_dark", coloraxis_showscale=False, margin=dict(l=10, r=10, t=30, b=10))
            g2.plotly_chart(fig_net, use_container_width=True, key="net_bar")

            fig_cum = go.Figure(go.Scatter(x=df_7d.index, y=df_7d["Cum_CO2"], mode="lines+markers", line=dict(color=COLOR_BATTERY, width=2)))
            fig_cum.update_layout(height=240, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10), yaxis_title="kg CO₂")
            g3.plotly_chart(fig_cum, use_container_width=True, key="cum_co2")

            target_month = 1_500_000
            saved_month = df_7d["Net"].clip(lower=0).sum() * GRID_TARIFF_IDR_PER_KWH
            bullet = go.Figure(go.Indicator(mode="number+gauge", value=saved_month, number={"prefix": "Rp", "valueformat": ",.0f"},
                                            gauge={"shape": "bullet", "axis": {"range": [0, target_month * 1.1]}, "bar": {"color": COLOR_PV},
                                                   "threshold": {"line": {"color": COLOR_BATTERY, "width": 3}, "value": target_month}},
                                            title={"text": "Month-to-date Cost Saving"}))
            bullet.update_layout(height=180, template="plotly_dark", margin=dict(l=30, r=30, t=50, b=10))
            st.plotly_chart(bullet, use_container_width=True, key="cost_bullet")

        soc_24h = _get_historical(device_sn, "SOC", now - timedelta(hours=24))
        if not soc_24h.empty:
            st.plotly_chart(_plot_area(soc_24h, "%"), use_container_width=True, key="soc24h")

        pie = px.pie(values=[daily_buy, daily_sell], names=["Buy", "Sell"], color_discrete_sequence=[COLOR_GRID, COLOR_PV], hole=0.45)
        pie.update_traces(textposition="inside", texttemplate="%{label}: %{percent:.0%}")
        pie.update_layout(height=280, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(pie, use_container_width=False, key="pie")

        st.subheader("📋 Recommended Actions")
        tips = []
        if net_energy < 0:
            tips.append(f"🔆 Upsize PV ±{abs(net_energy) / 4:.0f} kWp.")
        if soc < 40:
            tips.append("🔋 Charge battery midday (SOC < 40 %).")
        if 'df_7d' in locals() and df_7d["Net"].min() < -5:
            tips.append("⚡ Shift HVAC loads on deficit days.")
        if self_suff_ratio < 70:
            tips.append("🔋 Add battery to lift self-sufficiency > 70 %.")
        tips.append("📜 Offer REC/carbon credits for formal Net-Zero Scope-2.")
        for tip in tips:
            st.markdown(f"- {tip}")

if __name__ == "__main__":
    main()