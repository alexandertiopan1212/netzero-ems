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
REC_PRICE_IDR_PER_MWh = 1500000  # Harga REC Indonesia
CARBON_PRICE_IDR_PER_KG = 160    # $10/ton @kurs 16,000
GHG_INTENSITY = {                # Faktor emisi berbagai sumber
    'grid': 0.82,
    'diesel': 0.8,
    'gas': 0.45,
    'coal': 1.1
}
USD_IDR = 16000                 # Asumsi kurs USD-IDR

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

def calculate_emission_scopes(raw_data: dict, daily_buy: float) -> dict:
    """Hitung emisi berdasarkan GHG Protocol dengan breakdown detail"""
    return {
        'scope1': {
            'sources': ['Diesel Generator'],
            'emission': raw_data.get('DieselConsumption', 0) * GHG_INTENSITY['diesel'],
            'unit': 'kg'
        },
        'scope2': {
            'grid_import': daily_buy * GHG_INTENSITY['grid'],
            'unit': 'kg'
        },
        'scope3': {
            'components': {
                'BatteryProduction': raw_data.get('BatteryCapacity', 0) * 150,  # 150kg CO2/kWh
                'PVProduction': raw_data.get('PVCapacity', 0) * 500,            # 500kg CO2/kWp
                'Commuting': raw_data.get('EmployeeCount', 0) * 365 * 0.5       # Asumsi 0.5kg/hr
            },
            'unit': 'kg'
        }
    }

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
    raw = raw_data

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

    # ───────── Insights Tab ───────────────────────────────────────────
    with tab_ins:
        st.markdown(
            """
            <div class='glass-card' style="background:linear-gradient(135deg,rgba(0,204,0,.15),rgba(0,0,0,.3));">
                <h2 style="border-bottom:2px solid var(--pv);padding-bottom:.5rem;">♻️ Sustainability Intelligence Suite</h2>
            </div>
            """, unsafe_allow_html=True)

        # ----- Helper --------------------------------------------------
        def rgba(hex_color: str, a: float = .35) -> str:
            h = hex_color.lstrip("#")
            r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
            return f"rgba({r},{g},{b},{a})"

        # ----- Basic daily numbers ------------------------------------
        d_prod = float(raw.get("DailyActiveProduction", {"value": 0})["value"])
        d_cons = float(raw.get("DailyConsumption", {"value": 0})["value"])
        d_buy  = float(raw.get("DailyEnergyBuy", {"value": 0})["value"])

        avoided_emis = d_prod * EMISSION_FACTOR_KG_PER_KWH
        scope2_emis  = d_buy  * EMISSION_FACTOR_KG_PER_KWH
        scope1_total = 0.0                 # isi real jika ada bahan bakar onsite
        scope3_total = 0.0                 # isi real jika ada data rantai pasok

        # ----- REC & carbon value -------------------------------------
        REC_PRICE_IDR_PER_MWh = 1_500_000
        USD_IDR               = 16_000
        carbon_price_usd      = 10

        rec_generated = d_prod / 1000
        rec_value     = rec_generated * REC_PRICE_IDR_PER_MWh
        carbon_value_usd = avoided_emis/1000 * carbon_price_usd
        carbon_value     = carbon_value_usd * USD_IDR

        total_rec      = rec_generated * 365
        install_date   = "2024-01-01"
        flows          = calculate_flows(raw)
        pv_to_batt     = flows.get("PV→Battery", 0)
        rec_buyers     = "C&I, Data Center, Mining"
        net_zero_year  = 2030
        remaining_emis = max(scope2_emis + scope3_total - avoided_emis, 0)
        investment     = remaining_emis * 200_000

        # ----- 3 dashboard columns ------------------------------------
        dash1, dash2, dash3 = st.columns(3)

        # === DASH 1 : Carbon ==========================================
        with dash1:
            st.markdown(f"""
            <div class='glass-card' style="border-left:4px solid var(--pv);">
            <h3>🌍 Real-Time Carbon Accounting</h3>
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:1rem;">
                <div class='kpi-card' style="background:rgba(255,255,255,0.05);">
                <h4>Avoided Emissions</h4>
                <p style="color:var(--pv);font-size:1.8rem;">{avoided_emis:,.0f} kg</p>
                <small>≈ {avoided_emis/22:.0f} trees</small>
                </div>
                <div class='kpi-card' style="background:rgba(255,255,255,0.05);">
                <h4>Carbon Debt</h4>
                <p style="color:var(--load);font-size:1.8rem;">{scope2_emis:,.0f} kg</p>
                <small>{d_buy:.1f} kWh grid import</small>
                </div>
            </div>
            </div>""", unsafe_allow_html=True)

            fig_sankey = go.Figure(go.Sankey(
                node=dict(
                    label=["Energy","PV Generation","Grid Import",
                        "Scope 2","Avoided","Scope 3"],
                    color=[COLOR_GRID, COLOR_PV, COLOR_GRID,
                        COLOR_LOAD, COLOR_PV, COLOR_BATTERY]),
                link=dict(
                    source=[0,0,1,2,3,5],
                    target=[1,2,3,3,4,3],
                    value=[d_prod, d_buy, d_prod, d_buy, avoided_emis, scope3_total],
                    color=[rgba(COLOR_PV), rgba(COLOR_GRID), rgba(COLOR_PV),
                        rgba(COLOR_GRID), rgba(COLOR_PV), rgba(COLOR_BATTERY)]
                )
            ))
            fig_sankey.update_layout(title="Carbon Flow Analysis",
                                    height=400, template="plotly_dark")
            st.plotly_chart(fig_sankey, use_container_width=True)

        # === DASH 2 : REC =============================================
        with dash2:
            st.markdown(f"""
            <div class='glass-card' style="border-left:4px solid var(--battery);">
            <h3>📜 REC Management</h3>
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:1rem;">
                <div class='kpi-card' style="background:rgba(255,165,0,.05);">
                <h4>REC Generated</h4>
                <p style="color:var(--battery);font-size:1.8rem;">{rec_generated:.2f} MWh</p>
                <small>1 REC = 1 MWh</small>
                </div>
                <div class='kpi-card' style="background:rgba(255,165,0,.05);">
                <h4>REC Valuation</h4>
                <p style="color:var(--battery);font-size:1.8rem;">Rp{rec_value:,.0f}</p>
                <small>Market: Rp{REC_PRICE_IDR_PER_MWh:,.0f}/MWh</small>
                </div>
            </div>
            <div class='glass-card' style="margin-top:1rem;background:rgba(0,0,0,.3);">
                <h4>📅 Lifetime Achievement</h4>
                <p style="font-size:2rem;text-align:center;margin:0;">
                <span style="color:var(--pv);">{total_rec:.0f} MWh</span><br>
                <small>Since {install_date}</small>
                </p>
            </div>
            </div>""", unsafe_allow_html=True)

        # === DASH 3 : Carbon Money ====================================
        with dash3:
            st.markdown(f"""
            <div class='glass-card' style="border-left:4px solid var(--grid);">
            <h3>💰 Carbon Economics</h3>
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:1rem;">
                <div class='kpi-card' style="background:rgba(30,144,255,.05);">
                <h4>Carbon Credits</h4>
                <p style="color:var(--grid);font-size:1.8rem;">{avoided_emis:,.0f} kg</p>
                <small>Verified 0 kg</small>
                </div>
                <div class='kpi-card' style="background:rgba(30,144,255,.05);">
                <h4>Monetization</h4>
                <p style="color:var(--grid);font-size:1.8rem;">Rp{carbon_value:,.0f}</p>
                <small>${carbon_value_usd:,.0f} @{USD_IDR:,.0f}</small>
                </div>
            </div>
            <div class='glass-card' style="margin-top:1rem;background:linear-gradient(90deg,var(--pv),var(--grid));">
                <h4 style="color:white;">📈 30-Year Projection</h4>
                <p style="font-size:1.4rem;color:white;text-align:center;">
                Rp{(carbon_value+rec_value)*365*30:,.0f}
                </p>
            </div>
            </div>""", unsafe_allow_html=True)
            
        # ── Hitung variabel yang dipakai di Strategic Action Plan ──────────
        soc = float(raw.get("SOC", {"value": 0})["value"])          # Battery SOC %
        rec_generated = d_prod / 1000                               # MWh PV today
        rec_value     = rec_generated * REC_PRICE_IDR_PER_MWh       # Rp

        # Dapatkan aliran PV→Battery dari fungsi calculate_flows()
        flows = calculate_flows(raw)
        pv_to_batt = flows.get("PV→Battery", 0)
        
        # --- Strategic Action Plan ---------------------------------------
        st.markdown(
            """
            <div class='glass-card' style="background:linear-gradient(45deg,rgba(0,204,0,.1),rgba(30,144,255,.1));">
            <h2 style="color: var(--pv); border-bottom: 2px solid; padding-bottom: .5rem;">🚀 Strategic Action Plan</h2>
            </div>
            """,
            unsafe_allow_html=True
        )

        strategy_cols = st.columns(3)

        # -- Column 1 : Battery Opt ---------------------------------------
        strategy_cols[0].markdown(
            f"""
            <div class='glass-card' style="border-left:4px solid var(--pv);">
            <h4>🔋 Battery Optimization</h4>
            <ul style="padding-left:1rem;">
                <li>Target SOC : 80 % (Now {soc:.0f} %)</li>
                <li>Potential Savings : Rp{rec_value*0.3:,.0f} / hari</li>
                <li>🔌 Charge from PV : {pv_to_batt:.2f} kW</li>
            </ul>
            </div>
            """,
            unsafe_allow_html=True
        )

        # -- Column 2 : REC Strategy --------------------------------------
        strategy_cols[1].markdown(
            f"""
            <div class='glass-card' style="border-left:4px solid var(--grid);">
            <h4>📜 REC Strategy</h4>
            <ul style="padding-left:1rem;">
                <li>Certification : I-REC Standard</li>
                <li>Potential Buyers : {rec_buyers}</li>
                <li>📅 Expiry : 3 tahun</li>
            </ul>
            </div>
            """,
            unsafe_allow_html=True
        )

        # -- Column 3 : Net-Zero Roadmap -----------------------------------
        strategy_cols[2].markdown(
            f"""
            <div class='glass-card' style="border-left:4px solid var(--battery);">
            <h4>🌍 Net-Zero Roadmap</h4>
            <ul style="padding-left:1rem;">
                <li>Target Year : {net_zero_year}</li>
                <li>Required Offset : {remaining_emis:,.0f} ton/tahun</li>
                <li>💡 Investasi : Rp{investment:,.0f}</li>
            </ul>
            </div>
            """,
            unsafe_allow_html=True
        )

        # --- Live Carbon Market (static mock) -----------------------------
        st.markdown(
            """
            <div class='glass-card' style="background:rgba(0,0,0,.4);">
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;text-align:center;">
                <div>
                <h4>EU Carbon</h4>
                <p style="color: var(--pv);">€85.40</p>
                <small>+1.2 % today</small>
                </div>
                <div>
                <h4>California</h4>
                <p style="color: var(--pv);">$30.15</p>
                <small>Vol 1.2 M t</small>
                </div>
                <div>
                <h4>I-REC</h4>
                <p style="color: var(--pv);">$2.80/MWh</p>
                <small>±0 % month</small>
                </div>
                <div>
                <h4>IDX Karbon</h4>
                <p style="color: var(--pv);">Rp35 000</p>
                <small>Jakarta Carbon</small>
                </div>
            </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        

if __name__ == "__main__":
    main()