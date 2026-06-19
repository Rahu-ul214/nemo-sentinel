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
    page_title="NodeForge Sentinel | SpoolVault",
    page_icon="🧵",
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

# ── DESIGN SYSTEM ──────────────────────────────────────────────────────────
def _apply_design_system():
    """Injects a high-fidelity Glassmorphism CSS theme into the application."""
    st.markdown(
        """
        <style>
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #111118;
            --surface: rgba(255, 255, 255, 0.04);
            --surface-hover: rgba(255, 255, 255, 0.07);
            --border: rgba(255, 255, 255, 0.08);
            --accent-gold: #c9a84c;
            --accent-gold-dim: rgba(201, 168, 76, 0.15);
            --accent-gold-glow: rgba(201, 168, 76, 0.35);
            --text-primary: #f0f0f0;
            --text-secondary: #8a8a9a;
            --text-muted: #4a4a5a;
            --status-ok: #2ecc71;
            --status-warn: #f39c12;
            --status-error: #e74c3c;
        }

        [data-testid="stAppViewContainer"] {
            background-color: var(--bg-primary);
            color: var(--text-primary);
        }

        [data-testid="stSidebar"] {
            background-color: var(--bg-secondary);
            border-right: 1px solid var(--border);
        }

        .glass-card {
            background: var(--surface);
            backdrop-filter: blur(12px) saturate(160%);
            border: 1px solid var(--border);
            border-radius: 12px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.06);
            padding: 20px;
            margin-bottom: 20px;
        }

        [data-testid="stMetric"] {
            background: var(--surface);
            border-radius: 12px;
            border: 1px solid var(--border);
            border-top: 3px solid var(--accent-gold);
            padding: 15px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }

        div.stButton > button {
            background: var(--bg-secondary);
            color: var(--accent-gold);
            border: 1px solid var(--accent-gold);
            border-radius: 6px;
            transition: all 0.3s ease;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        div.stButton > button:hover {
            background: var(--accent-gold-dim);
            box-shadow: 0 0 15px var(--accent-gold-glow);
            transform: translateY(-1px);
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

def _render_manual_override_panel():
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Manual Override**", unsafe_allow_html=False)
    st.sidebar.caption("Direct hardware control. Bypasses automation scheduler.")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        sweep_triggered = st.button(
            "Trigger Sweep",
            key="hw_sweep_btn",
            use_container_width=True,
            type="primary",
        )
    with col2:
        st.button(
            "Abort",
            key="hw_abort_btn",
            use_container_width=True,
        )

    if sweep_triggered:
        _send_sweep_command()

# ── UI COMPONENTS ────────────────────────────────────────────────────────
def _render_telemetry_card():
    """Renders the live printer status with glassmorphism metrics."""
    with st.container():
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("🚀 Live Printer Telemetry")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Machine State", STATUS.gcode_state)
        with col2:
            st.metric("Print Progress", f"{STATUS.print_progress}%")
        with col3:
            st.metric("Est. Time Left", f"{STATUS.total_estimated_time} min")

        if STATUS.gcode_state == "PRINTING":
            st.status("⚙️ Printer is currently active and processing G-code...", expanded=False)

        st.markdown('</div>', unsafe_allow_html=True)

def _render_inventory_card():
    """Renders the professional SpoolVault inventory table."""
    with st.container():
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("📦 SpoolVault Inventory")

        data = _load_inventory()
        spools = data.get("spools", [])

        if not spools:
            st.info("No spools found in local inventory.json.")
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
                height=400,
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

# ── MAIN ENTRY POINT ────────────────────────────────────────────────────────
def main():
    _init_session_state()
    _apply_design_system()

    st.title("NodeForge Sentinel")
    st.markdown("Industrial Fleet Management Suite")

    _render_telemetry_card()
    st.markdown("<br>", unsafe_allow_html=True)
    _render_inventory_card()

    _render_manual_override_panel()

    mqtt_status = "🟢 Connected" if STATUS.mqtt_connected else "🔴 Disconnected"
    st.markdown(f"<div style='text-align: center; color: var(--text-muted); margin-top: 40px;'>Telemetry: {mqtt_status} | Device: {BAMBU_DEVICE_ID}P</div>", unsafe_allow_t_html=True)

if __name__ == "__main__":
    main()
