import streamlit as st
import requests
import pandas as pd
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from core.config import BAMBU_DEVICE_ID
from core.state import STATUS
from services.telemetry import BambuMqttClient

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
def _init_session_state():
    """Initializes all mutable UI state to prevent KeyError."""
    if "mqtt_client" not in st.session_state:
        try:
            client = BambuMqttClient()
            client.connect()
            client.start()
            st.session_state.mqtt_client = client
        except Exception as e:
            log.error(f"Failed to initialize MQTT client: {e}")
            st.session_state.mqtt_client = None

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

# ── DESIGN SYSTEM: INDUSTRIAL OBSIDIAN ──────────────────────────────────────
def _apply_design_system():
    """Injects the high-fidelity Industrial Obsidian theme."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;600;800&display=swap');

        :root {
            --obsidian-deep: #050508;
            --obsidian-charcoal: #111118;
            --gold-primary: #c9a84c;
            --gold-glow: rgba(201, 168, 76, 0.2);
            --glass-border: rgba(255, 255, 255, 0.08);
            --glass-surface: rgba(17, 17, 24, 0.7);
            --text-primary: #f0f0f0;
            --text-secondary: #8a8a9a;
            --status-ok: #00FF9C;
            --status-warn: #FFB300;
            --status-error: #FF3B30;
        }

        [data-testid="stAppViewContainer"] {
            background-color: var(--obsidian-deep);
            color: var(--text-primary);
            font-family: 'Inter', sans-serif;
        }

        [data-testid="stSidebar"] {
            background-color: var(--obsidian-charcoal);
            border-right: 1px solid var(--glass-border);
        }

        /* Bento Grid Component */
        .bento-card {
            background: var(--glass-surface);
            backdrop-filter: blur(16px) saturate(180%);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 24px;
            transition: all 0.3s ease;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        }
        .bento-card:hover {
            border-color: var(--gold-primary);
            box-shadow: 0 0 20px var(--gold-glow);
        }

        /* Digital Readouts */
        .telemetry-readout {
            font-family: 'JetBrains Mono', monospace;
            color: var(--gold-primary);
            background: #000;
            padding: 4px 12px;
            border-radius: 6px;
            border: 1px solid var(--glass-border);
            display: inline-block;
            font-weight: 700;
            font-size: 1.2rem;
            box-shadow: inset 0 0 8px rgba(0,0,0,0.8);
        }

        /* Status LEDs */
        .status-led {
            height: 10px;
            width: 10px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
            box-shadow: 0 0 8px currentColor;
        }
        .led-ok { color: var(--status-ok); background-color: var(--status-ok); }
        .led-warn { color: var(--status-warn); background-color: var(--status-warn); }
        .led-error { color: var(--status-error); background-color: var(--status-error); }

        /* Tactile Industrial Buttons */
        .industrial-btn {
            background: var(--obsidian-charcoal);
            color: var(--gold-primary);
            border: 1px solid var(--gold-primary);
            border-bottom: 4px solid #8a6d2d;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            cursor: pointer;
            transition: all 0.1s ease;
            text-align: center;
            display: block;
            width: 100%;
        }
        .industrial-btn:active {
            border-bottom-width: 1px;
            transform: translateY(3px);
            background: var(--gold-glow);
        }

        /* SpoolVault Professional Table */
        .stDataFrame {
            border: 1px solid var(--glass-border) !important;
            border-radius: 12px !important;
        }

        #MainMenu, footer, header {
            visibility: hidden;
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

# ── HARDWARE INTERFACE ──────────────────────────────────────────────────────
def _send_sweep_command():
    ESP32_ENDPOINT = "http://10.254.244.107/sweep"
    try:
        response = requests.post(
            ESP32_ENDPOINT,
            timeout=4,
            headers={"Content-Type": "application/json"},
            json={"source": "sentinel_manual_override", "timestamp": datetime.utcnow().isoformat()}
        )
        if response.status_code == 200:
            st.sidebar.success(f"Sweep acknowledged ({response.elapsed.total_seconds():.2f}s)")
        else:
            st.sidebar.warning(f"ESP32 returned HTTP {response.status_code}")
    except requests.exceptions.Timeout:
        st.sidebar.error("Hardware timeout — no response within 4s")
    except requests.exceptions.ConnectionError:
        st.sidebar.error("Connection failed — check ESP32 network status")
    except Exception as e:
        st.sidebar.error(f"Unexpected error: {type(e).__name__}")

# ── FLEET DATA WRAPPER ─────────────────────────────────────────────────────
def get_fleet_data() -> List[Dict[str, Any]]:
    """
    Wraps the single-device STATUS singleton into a list to be 'Fleet Ready'.
    """
    return [
        {
            "id": BAMBU_DEVICE_ID,
            "name": f"Node-{BAMBU_DEVICE_ID}",
            "data": STATUS
        }
    ]

# ── UI COMPONENTS ─────────────────────────────────────────────────────────
def render_machine_card(machine: Dict[str, Any]):
    """Renders a high-fidelity Bento card for a single printer."""
    data = machine["data"]

    # Determine LED color based on state
    led_class = "led-warn"
    if data.gcode_state == "PRINTING":
        led_class = "led-ok"
    elif data.gcode_state == "ERROR":
        led_class = "led-error"

    with st.container():
        st.markdown(f"""
        <div class="bento-card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <div style="font-weight: 800; font-size: 1.4rem; color: var(--text-primary);">
                    <span class="status-led {led_class}"></span> {machine['name']}
                </div>
                <div style="color: var(--text-secondary); font-family: 'JetBrains Mono'; font-size: 0.9rem;">
                    ID: {machine['id']}
                </div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; text-align: center;">
                <div>
                    <div style="color: var(--text-secondary); font-size: 0.8rem; margin-bottom: 5px;">NOZZLE TEMP</div>
                    <div class="telemetry-readout">{data.nozzle_temp:.1f}°C</div>
                </div>
                <div>
                    <div style="color: var(--text-secondary); font-size: 0.8rem; margin-bottom: 5px;">BED TEMP</div>
                    <div class="telemetry-readout">{data.bed_temp:.1f}°C</div>
                </div>
                <div>
                    <div style="color: var(--text-secondary); font-size: 0.8rem; margin-bottom: 5px;">G-CODE STATE</div>
                    <div class="telemetry-readout" style="color: var(--status-ok);">{data.gcode_state}</div>
                </div>
            </div>

            <div style="margin-top: 25px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-family: 'JetBrains Mono'; font-size: 0.8rem;">
                    <span>PROGRESS</span>
                    <span>{data.print_progress}%</span>
                </div>
                <div style="background: rgba(0,0,0,0.3); border-radius: 10px; height: 12px; border: 1px solid var(--glass-border); overflow: hidden;">
                    <div style="background: var(--gold-primary); width: {data.print_progress}%; height: 100%; box-shadow: 0 0 10px var(--gold-glow);"></div>
                </div>
            </div>

            <div style="margin-top: 15px; text-align: right; font-family: 'JetBrains Mono'; font-size: 0.8rem; color: var(--text-secondary);">
                Est. Time Left: {data.total_estimated_time} min
            </div>
        </div>
        """, unsafe_allow_html=True)

def render_fleet_health():
    """Renders a compact health summary for the fleet."""
    with st.container():
        st.markdown(f"""
        <div class="bento-card">
            <div style="font-weight: 800; font-size: 1.1rem; color: var(--text-primary); margin-bottom: 15px;">
                SYSTEM HEALTH
            </div>
            <div style="display: flex; flex-direction: column; gap: 10px;">
                <div style="display: flex; justify-content: space-between; font-family: 'JetBrains Mono'; font-size: 0.9rem;">
                    <span style="color: var(--text-secondary);">Connectivity</span>
                    <span style="color: {'var(--status-ok)' if STATUS.mqtt_connected else 'var(--status-error)'}">
                        {'● Connected' if STATUS.mqtt_connected else '● Offline'}
                    </span>
                </div>
                <div style="display: flex; justify-content: space-between; font-family: 'JetBrains Mono'; font-size: 0.9rem;">
                    <span style="color: var(--text-secondary);">Active Nodes</span>
                    <span>1 / 1</span>
                </div>
                <div style="display: flex; justify-content: space-between; font-family: 'JetBrains Mono'; font-size: 0.9rem;">
                    <span style="color: var(--text-secondary);">System Load</span>
                    <span style="color: var(--status-ok);">NOMINAL</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

def render_spoolvault_ledger():
    """Renders the professional industrial inventory ledger."""
    with st.container():
        st.markdown('<div class="bento-card">', unsafe_allow_html=True)
        st.subheader("📦 SpoolVault Industrial Ledger")

        data = _load_inventory()
        spools = data.get("spools", [])

        if not spools:
            st.info("No spool data available in ledger.")
        else:
            records = []
            for idx, s in enumerate(spools):
                status = "Available"
                if STATUS.gcode_state == "PRINTING" and s.get("material") == "PLA":
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
                height=350,
                column_config={
                    "spool_id": st.column_config.TextColumn("ID", width="small"),
                    "material": st.column_config.TextColumn("Material", width="small"),
                    "color": st.column_config.TextColumn("Color"),
                    "remaining_g": st.column_config.ProgressColumn(
                        "Remaining",
                        help="Grams remaining on spool",
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
        st.markdown('</div>', unsafe_allow_html=True)

def render_control_slab():
    """Renders the tactile hardware control panel."""
    st.markdown('<div style="margin-top: 30px;">', unsafe_allow_html=True)
    st.markdown('<div style="font-weight: 800; font-size: 1.1rem; color: var(--text-primary); margin-bottom: 15px; text-align: center;">TACTICAL OVERRIDE</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Trigger Sweep", key="hw_sweep", use_container_width=True):
            _send_sweep_command()
    with col2:
        st.button("Abort Operation", key="hw_abort", use_container_width=True)
    with col3:
        st.button("Emergency Stop", key="hw_stop", use_container_width=True)

    # Custom CSS for the buttons to make them look "Industrial" (since st.button is limited)
    # Note: In a real app we'd use components, but for now we'll use st.markdown to overlay styles
    # or simply accept the standard streamlit look for the buttons while using CSS to target them.
    st.markdown("""
        <style>
        div.stButton > button {
            background: var(--obsidian-charcoal) !important;
            color: var(--gold-primary) !important;
            border: 1px solid var(--gold-primary) !important;
            border-bottom: 4px solid #8a6d2d !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 1px !important;
            transition: all 0.1s ease !important;
        }
        div.stButton > button:hover {
            background: var(--gold-glow) !important;
            border-color: var(--gold-primary) !important;
        }
        div.stButton > button:active {
            border-bottom-width: 1px !important;
            transform: translateY(3px) !important;
        }
        </style>
    """, unsafe_allow_html=True)

# ── MAIN ENTRY POINT ────────────────────────────────────────────────────────
def main():
    _init_session_state()
    _apply_design_system()

    st.title("NodeForge Sentinel")
    st.markdown(
        '<div style="color: var(--text-secondary); font-family: \'JetBrains Mono\'; font-size: 0.9rem; margin-bottom: 30px; letter-spacing: 2px;">'
        'INDUSTRIAL FLEET MANAGEMENT SUITE v8.2'
        '</div>',
        unsafe_allow_html=True
    )

    # Bento Grid Layout
    fleet = get_fleet_data()

    col_main, col_side = st.columns([2, 1])

    with col_main:
        for machine in fleet:
            render_machine_card(machine)

    with col_side:
        render_fleet_health()

    # SpoolVault Ledger
    render_spoolvault_ledger()

    # Tactical Controls
    render_control_slab()

    # Footer
    mqtt_status = "🟢 Connected" if STATUS.mqtt_connected else "🔴 Disconnected"
    st.markdown(
        f"""
        <div style='text-align: center; color: var(--text-secondary); margin-top: 50px; font-family: \'JetBrains Mono\'; font-size: 0.7rem;'>
            TELEMETRY: {mqtt_status} | SESSION: {BAMBU_DEVICE_ID}P | LAST REFRESH: {datetime.now().strftime("%H:%M:%S")}
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
