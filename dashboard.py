import streamlit as st
import pandas as pd
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

# New Production Services
from mqtt_service import MQTTTelemetryService
from fleet_service import FleetAggregationService
from control_service import TacticalControlService
from models import PrinterTelemetry, PrinterStatus

# ── LOGGING CONFIGURATION ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sentinel.dashboard")

# --- CONSTANTS ---
INVENTORY_FILE = "inventory.json"

st.set_page_config(
    page_title="NodeForge Sentinel | Fleet Suite",
    page_icon="🛠️",
    layout="wide"
)

# ── SESSION STATE MANAGEMENT ───────────────────────────────────────────────
def _init_services():
    """Initializes the production fleet services in session state."""
    if "mqtt_service" not in st.session_state:
        import os
        from dotenv import load_dotenv
        load_dotenv()

        try:
            mqtt = MQTTTelemetryService(
                broker_host=os.getenv("BAMBU_MQTT_HOST", "us.mqtt.bambulab.com"),
                broker_port=int(os.getenv("BAMBU_MQTT_PORT", 8883)),
                username=os.getenv("BAMBU_MQTT_USER", ""),
                password=os.getenv("BAMBU_MQTT_PASS", "")
            )
            mqtt.connect()
            st.session_state.mqtt_service = mqtt
        except Exception as e:
            log.error(f"Failed to initialize MQTT service: {e}")
            st.session_state.mqtt_service = None

    if "fleet_service" not in st.session_state:
        st.session_state.fleet_service = FleetAggregationService()

    if "control_service" not in st.session_state:
        st.session_state.control_service = TacticalControlService(st.session_state.mqtt_service)

    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = time.time()

# ── INVENTORY PERSISTENCE LAYER ────────────────────────────────────────────
def _load_inventory() -> Dict[str, Any]:
    """Loads inventory from a local JSON file with error handling."""
    try:
        import os
        import json
        if not os.path.exists(INVENTORY_FILE):
            initial_data = {"spools": [], "last_updated": None, "schema_version": 1}
            _save_inventory(initial_data)
            return initial_data

        with open(INVENTORY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f"Inventory load failed: {e}. Returning empty structure.")
        return {"spools": [], "last_updated": None, "schema_version": 1}

def _save_inventory(data: Dict[str, Any]) -> None:
    """Persists inventory data to the local JSON file."""
    try:
        import json
        data["last_updated"] = datetime.utcnow().isoformat()
        with open(INVENTORY_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        log.error(f"Failed to save inventory to {INVENTORY_FILE}: {e}")

# ── DESIGN SYSTEM: INDUSTRIAL OBSIDIAN (CSS INJECTION) ────────────────────────
def _apply_design_system():
    """Injects a professional, high-contrast Obsidian theme."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;600;800&display=swap');

        [data-testid="stAppViewContainer"] {
            background-color: #0A0A0A !important;
            color: #F0F0F0 !important;
            font-family: 'Inter', sans-serif !important;
        }

        [data-testid="stHeader"] {
            background: transparent !important;
        }

        [data-testid="stSidebar"] {
            background-color: #0F0F0F !important;
            border-right: 1px solid #1F1F1F !important;
        }

        div[data-testid="stVerticalBlock"] > div:has(div.stMetric) {
            background-color: #111111 !important;
            border: 1px solid #1F1F1F !important;
            border-radius: 12px !important;
            padding: 20px !important;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5) !important;
        }

        h1, h2, h3 {
            font-family: 'Inter', sans-serif !important;
            font-weight: 800 !important;
            letter-spacing: -0.02em !important;
            color: #F0F0F0 !important;
        }

        .stMetric label {
            font-family: 'Inter', sans-serif !important;
            color: #8A8A9A !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            font-size: 0.75rem !important;
            letter-spacing: 0.05em !important;
        }

        .stMetric div[data-testid="stMetricValue"] {
            font-family: 'JetBrains Mono', monospace !important;
            color: #C9A84C !important;
            font-weight: 700 !important;
        }

        .stDataFrame {
            border: 1px solid #1F1F1F !important;
            border-radius: 12px !important;
            background-color: #0A0A0A !important;
        }

        div.stButton > button {
            background-color: #111111 !important;
            color: #C9A84C !important;
            border: 1px solid #C9A84C !important;
            border-radius: 8px !important;
            font-family: 'Inter', sans-serif !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            transition: all 0.2s ease !important;
        }

        div.stButton > button:hover {
            background-color: rgba(201, 168, 76, 0.1) !important;
            border-color: #F0F0F0 !important;
            color: #F0F0F0 !important;
        }

        #MainMenu, footer, header {
            visibility: hidden;
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

# ── MAIN ENTRY POINT ────────────────────────────────────────────────────────
def main():
    _init_services()
    _apply_design_system()

    mqtt_service = st.session_state.mqtt_service
    fleet_service = st.session_state.fleet_service
    control_service = st.session_state.control_service

    # --- SIDEBAR NAVIGATION & CONTROLS ---
    with st.sidebar:
        st.title("⚙️ Command")
        st.markdown("---")

        st.subheader("Tactical Override")
        # We iterate through printers for control actions
        printers = mqtt_service.get_all_printers() if mqtt_service else {}

        if not printers:
            st.warning("No printers connected")
        else:
            for p_id, p_telemetry in printers.items():
                st.markdown(f"**{p_telemetry.printer_name}**")
                if st.button(f"Clear Bed: {p_id}", key=f"sweep_{p_id}", use_container_width=True):
                    success, msg = control_service.clear_bed(p_id, p_telemetry)
                    if success: st.sidebar.success(msg)
                    else: st.sidebar.error(msg)
                if st.button(f"Stop: {p_id}", key=f"stop_{p_id}", use_container_width=True):
                    success, msg = control_service.emergency_stop(p_id)
                    if success: st.sidebar.error(msg)
                    else: st.sidebar.error(msg)
                st.markdown("---")

        st.markdown("---")

        st.subheader("Fleet Health")
        conn_status = mqtt_service.get_status()['connection_status'] if mqtt_service else "disconnected"
        mqtt_label = "🟢 Connected" if conn_status == "connected" else "🔴 Offline"
        st.markdown(f"**Connectivity:** {mqtt_label}")
        st.markdown(f"**Active Nodes:** {len(printers)}")

        st.markdown("---")
        st.caption("NEMO Fleet Suite v1.0")

    # --- MAIN DASHBOARD ---
    st.title("NodeForge Sentinel")
    st.markdown(
        f'<div style="color: #8A8A9A; font-family: \'JetBrains Mono\'; font-size: 0.8rem; margin-bottom: 30px; letter-spacing: 2px;">'
        f'INDUSTRIAL FLEET MANAGEMENT SUITE | LAST REFRESH: {datetime.now().strftime("%H:%M:%S")}'
        f'</div>',
        unsafe_allow_html=True
    )

    # 1. Fleet Aggregates (Top Row)
    if mqtt_service:
        aggregates = fleet_service.compute_fleet_aggregates(printers, conn_status)
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("ACTIVE JOBS", aggregates.total_active_jobs)
        with col2:
            st.metric("FLEET PROGRESS", f"{aggregates.fleet_print_progress:.1f}%")
        with col3:
            st.metric("EST. NEXT COMPLETION", f"{aggregates.estimated_completion_time}s")
        with col4:
            st.metric("TOTAL WEIGHT", f"{aggregates.total_weight_in_progress:.1f}g")
    else:
        st.error("MQTT Service unavailable. Please check .env credentials.")
        return

    st.markdown("<br>", unsafe_allow_html=True)

    # 2. Printer Grid (Bento)
    st.subheader("Fleet Telemetry")
    if not printers:
        st.info("Waiting for printer telemetry...")
    else:
        # Render printers in a grid
        # For simplicity, we use columns for the fleet
        rows = [printers[k] for k in printers]
        for i in range(0, len(rows), 2):
            cols = st.columns(2)
            for j in range(min(2, len(rows)-i)):
                printer = rows[i+j]
                with cols[j]:
                    with st.container():
                        st.markdown(f"### {printer.printer_name} ({printer.model.value})")

                        # Thermal Metrics
                        t1, t2 = st.columns(2)
                        with t1:
                            st.metric("Nozzle", f"{printer.thermal.nozzle_temp:.1f}°C", f"{printer.thermal.nozzle_target:.1f} Target")
                        with t2:
                            st.metric("Bed", f"{printer.thermal.bed_temp:.1f}°C", f"{printer.thermal.bed_target:.1f} Target")

                        # Job Metrics
                        if printer.job:
                            st.markdown(f"**Job:** `{printer.job.job_name}` | **Layer:** `{printer.job.current_layer}/{printer.job.total_layers}`")
                            st.progress(printer.job.progress_percent / 100)
                            st.markdown(f"**Speed:** `{printer.job.print_speed} mm/s` | **Remaining:** `{printer.job.time_remaining}s`")
                        else:
                            st.info("No active print job.")

                        st.markdown(f"**Status:** `{printer.status.value.upper()}` | **Signal:** `{printer.wifi_signal_strength} dBm`")
                        st.markdown("---")

    st.markdown("<br>", unsafe_allow_html=True)

    # 3. SpoolVault Ledger
    st.subheader("📦 SpoolVault Industrial Ledger")
    data = _load_inventory()
    spools = data.get("spools", [])

    if not spools:
        st.info("No spool data available in ledger.")
    else:
        records = []
        for idx, s in enumerate(spools):
            status = "Available"
            # Match material to any active job in the fleet
            is_in_use = any(
                p.job and p.job.print_type.lower() == s.get("material", "").lower()
                for p in printers.values()
            )
            if is_in_use:
                status = "In Use"
            elif s.get("remaining", 100) < 100:
                status = "Low"

            records.append({
                "spool_id": f"S-{idx+1:03d}",
                "material": s.get("material", "Unknown"),
                "color": s.get("color", "Unknown"),
                "remaining_g": s.get("remaining", 0),
                "status": status,
                "last_used": s.get("last_used", datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
            })

        df = pd.DataFrame(records)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "spool_id": st.column_config.TextColumn("ID", width="small"),
                "material": st.column_config.TextColumn("Material", width="small"),
                "color": st.column_config.TextColumn("Color"),
                "remaining_g": st.column_config.ProgressColumn(
                    "Remaining",
                    format="%d g",
                    min_value=0,
                    max_value=1000,
                ),
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    options=["Available", "In Use", "Low", "Depleted"],
                    width="small",
                ),
                "last_used": st.column_config.DatetimeColumn(
                    "Last Used",
                    format="DD MMM YYYY, HH:mm",
                ),
            }
        )

if __name__ == "__main__":
    main()
