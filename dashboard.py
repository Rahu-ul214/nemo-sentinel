# ── STANDARD LIBRARY ──────────────────────────────────────────────────────────
import base64
import io
import json
import logging
import logging.handlers
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── THIRD-PARTY ───────────────────────────────────────────────────────────────
import pandas as pd
import streamlit as st

# ── LOCAL ─────────────────────────────────────────────────────────────────────
import actuator_service
import inventory_manager
import mqtt_client
import vision_service
from config import (
    BAMBU_DEVICE_ID,
    ESP32_HOST,
    SENTINEL_LOG,
    SWEEP_VELOCITY_DEFAULT,
)
from state_engine import PrintState, StateEngine

# ── LOGGING ───────────────────────────────────────────────────────────────────
_log_dir = Path(SENTINEL_LOG).parent
_log_dir.mkdir(parents=True, exist_ok=True)

_log_handler = logging.handlers.RotatingFileHandler(
    SENTINEL_LOG, maxBytes=5 * 1024 * 1024, backupCount=3
)
_log_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.StreamHandler(), _log_handler],
)
log = logging.getLogger("nemo.dashboard")

# ── PAGE CONFIG (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="NEMO — Print Factory",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

_SPOOL_STATUS_OPTIONS = inventory_manager.SPOOL_STATUS_OPTIONS
_MATERIAL_OPTIONS = ["PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC", "PLA-CF", "PETG-CF"]


# ── DESIGN SYSTEM ─────────────────────────────────────────────────────────────

def _apply_design_system() -> None:
    """Injects the complete NEMO CSS design system. Called once at the top of main()."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        :root {
            --bg-primary:       #0a0a0f;
            --bg-secondary:     #111118;
            --surface:          rgba(255,255,255,0.04);
            --surface-hover:    rgba(255,255,255,0.07);
            --border:           rgba(255,255,255,0.08);
            --accent-gold:      #c9a84c;
            --accent-gold-dim:  rgba(201,168,76,0.15);
            --accent-gold-glow: rgba(201,168,76,0.35);
            --text-primary:     #f0f0f0;
            --text-secondary:   #8a8a9a;
            --text-muted:       #4a4a5a;
            --status-ok:        #2ecc71;
            --status-warn:      #f39c12;
            --status-error:     #e74c3c;
            --font-stack:       'Inter', 'Roboto', system-ui, sans-serif;
        }

        html, body, [data-testid="stAppViewContainer"] {
            background-color: var(--bg-primary) !important;
            color: var(--text-primary);
            font-family: var(--font-stack);
        }

        [data-testid="stSidebar"] {
            background: var(--bg-secondary) !important;
            border-right: 1px solid var(--border) !important;
        }
        [data-testid="stSidebar"] * { color: var(--text-primary) !important; }

        #MainMenu { visibility: hidden !important; }
        footer     { visibility: hidden !important; }
        header     { visibility: hidden !important; }

        .glass-card {
            background:              var(--surface);
            backdrop-filter:         blur(12px) saturate(160%);
            -webkit-backdrop-filter: blur(12px) saturate(160%);
            border:                  1px solid var(--border);
            border-radius:           12px;
            box-shadow:              0 4px 24px rgba(0,0,0,0.4),
                                     inset 0 1px 0 rgba(255,255,255,0.06);
            padding:                 24px;
            margin-bottom:           16px;
        }

        [data-testid="stMetric"] {
            background:    var(--surface) !important;
            border:        1px solid var(--border) !important;
            border-top:    3px solid var(--accent-gold) !important;
            border-radius: 12px !important;
            padding:       1rem 1.25rem !important;
            backdrop-filter: blur(12px);
        }
        [data-testid="stMetricLabel"] {
            color: var(--text-secondary) !important;
            font-size: 0.75rem !important;
            letter-spacing: 0.08em !important;
            text-transform: uppercase !important;
        }
        [data-testid="stMetricValue"] {
            color: var(--text-primary) !important;
            font-weight: 600 !important;
        }

        .stButton > button {
            background:    transparent !important;
            color:         var(--accent-gold) !important;
            border:        1px solid var(--accent-gold) !important;
            border-radius: 6px !important;
            font-weight:   600 !important;
            letter-spacing:0.05em !important;
            transition:    box-shadow 0.2s ease !important;
        }
        .stButton > button:hover {
            box-shadow:          0 0 16px var(--accent-gold-glow) !important;
            background-color:    var(--accent-gold-dim) !important;
        }
        .stButton > button[kind="primary"] {
            background-color: var(--accent-gold-dim) !important;
        }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--border) !important;
            border-radius: 8px !important;
        }

        .nemo-section-header {
            color:          var(--accent-gold);
            font-size:      0.7rem;
            font-weight:    700;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            border-bottom:  1px solid var(--border);
            padding-bottom: 0.4rem;
            margin-bottom:  0.75rem;
            margin-top:     1.25rem;
        }

        .status-badge {
            display:        inline-block;
            padding:        0.2rem 0.6rem;
            border-radius:  4px;
            font-size:      0.7rem;
            font-weight:    700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .status-ok    { background: rgba(46,204,113,0.15); color: var(--status-ok);    border: 1px solid rgba(46,204,113,0.3); }
        .status-warn  { background: rgba(243,156,18,0.15);  color: var(--status-warn);  border: 1px solid rgba(243,156,18,0.3); }
        .status-error { background: rgba(231,76,60,0.15);   color: var(--status-error); border: 1px solid rgba(231,76,60,0.3); }

        [data-testid="stCaptionContainer"] p {
            color: var(--text-muted) !important;
            font-size: 0.72rem !important;
        }

        [data-testid="stSelectbox"] > div > div,
        [data-testid="stTextInput"] > div > div > input,
        [data-testid="stNumberInput"] > div > div > input {
            background-color: var(--bg-secondary) !important;
            border:           1px solid var(--border) !important;
            color:            var(--text-primary) !important;
            border-radius:    6px !important;
        }

        hr { border-color: var(--border) !important; opacity: 1 !important; }

        [data-testid="stAlert"] {
            background-color: var(--surface) !important;
            border:           1px solid var(--border) !important;
            border-radius:    8px !important;
        }

        [data-testid="stSlider"] > div { color: var(--accent-gold) !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ── SESSION STATE ─────────────────────────────────────────────────────────────

def _init_session_state() -> None:
    """Initialises all session state keys. Every key used in this module lives here."""
    defaults: dict[str, Any] = {
        "page":                "Overview",
        "sweep_velocity":      SWEEP_VELOCITY_DEFAULT,
        "add_spool_form_open": False,
        "scanned_spool_data":  {},
        "last_refresh":        None,
        "engine":              None,
        "engine_started":      False,
        "hw_last_result":      None,
        "delete_confirm_id":   None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ── STATE ENGINE LIFECYCLE ────────────────────────────────────────────────────

def _ensure_engine() -> StateEngine:
    """Returns the singleton StateEngine for this session, creating it if needed."""
    if st.session_state.engine is None:
        engine = StateEngine()
        st.session_state.engine = engine

    if not st.session_state.engine_started:
        mqtt_client.start_mqtt_listener()
        st.session_state.engine.start()
        st.session_state.engine_started = True
        log.info("Dashboard started NEMO engine and MQTT listener.")

    return st.session_state.engine


# ── ESP32 CONNECTION CHECK ────────────────────────────────────────────────────

def _check_esp32_connection() -> tuple[bool, Optional[float]]:
    """
    Attempts a HEAD request to the ESP32 host. Returns (reachable, latency_ms).
    Times out quickly to avoid blocking the UI render.
    """
    import requests as _req
    start = time.monotonic()
    try:
        resp = _req.head(f"http://{ESP32_HOST}", timeout=2)
        latency = (time.monotonic() - start) * 1000.0
        return resp.status_code < 500, latency
    except _req.exceptions.Timeout:
        return False, None
    except _req.exceptions.ConnectionError:
        return False, None
    except Exception:
        return False, None


# ── SIDEBAR ───────────────────────────────────────────────────────────────────

def _render_sidebar(engine: StateEngine) -> None:
    """Renders branding, navigation buttons, and manual override panel."""
    st.sidebar.markdown(
        """
        <div style="padding:0.5rem 0 1rem 0;">
            <p style="font-size:1.15rem;font-weight:700;color:#c9a84c;letter-spacing:0.08em;margin:0;">NEMO</p>
            <p style="font-size:0.65rem;color:#8a8a9a;letter-spacing:0.2em;text-transform:uppercase;margin:0;">
                Autonomous Print Factory
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.markdown(
        '<p class="nemo-section-header">Navigation</p>', unsafe_allow_html=True
    )

    pages = ["Overview", "Inventory", "Hardware", "Logs"]
    for page in pages:
        if st.sidebar.button(page, key=f"nav_{page}", use_container_width=True):
            st.session_state.page = page
            st.rerun()

    _render_manual_override_panel()
    _render_sidebar_footer(engine)


def _render_sidebar_footer(engine: StateEngine) -> None:
    """Renders state engine status + MQTT connection badge at the sidebar bottom."""
    st.sidebar.markdown("---")
    status = engine.get_status()
    state_val = status.get("state", "unknown")
    telemetry = mqtt_client.get_telemetry()
    mqtt_ok = telemetry.get("mqtt_connected", False)

    badge = "status-ok" if mqtt_ok else "status-error"
    label = "Stream Live" if mqtt_ok else "Stream Offline"
    device_str = BAMBU_DEVICE_ID or "not configured"

    st.sidebar.markdown(
        f"""
        <div style="margin-top:0.5rem;">
            <span class="status-badge {badge}">{label}</span>
            <p style="font-size:0.68rem;color:#4a4a5a;margin-top:0.3rem;">
                Device: {device_str}
            </p>
            <p style="font-size:0.68rem;color:#4a4a5a;margin-top:0.1rem;">
                Engine: <strong style="color:#c9a84c;">{state_val.upper()}</strong>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_manual_override_panel() -> None:
    """Sidebar manual override controls for direct hardware command."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Manual Override**")
    st.sidebar.caption("Direct hardware control. Bypasses automation scheduler.")

    velocity = st.sidebar.slider(
        "Sweep Velocity",
        min_value=10,
        max_value=100,
        value=st.session_state.sweep_velocity,
        key="velocity_slider",
    )
    st.session_state.sweep_velocity = velocity

    c1, c2 = st.sidebar.columns(2)
    with c1:
        if st.button("Sweep", key="btn_sweep", use_container_width=True):
            result = actuator_service.trigger_sweep(velocity)
            st.session_state.hw_last_result = result
            st.sidebar.json(result)
    with c2:
        if st.button("Abort", key="btn_abort", use_container_width=True):
            result = actuator_service.trigger_abort()
            st.session_state.hw_last_result = result
            st.sidebar.json(result)


# ── PAGE HEADER ───────────────────────────────────────────────────────────────

def _render_page_header(page: str) -> None:
    """Renders the top-of-page branded header."""
    st.markdown(
        f"""
        <div style="padding:0.5rem 0 1.5rem 0;border-bottom:1px solid var(--border);margin-bottom:1.5rem;">
            <h1 style="font-size:1.6rem;font-weight:700;color:var(--text-primary);margin:0;letter-spacing:0.04em;">
                NEMO <span style="color:var(--accent-gold);">{page}</span>
            </h1>
            <p style="color:var(--text-secondary);font-size:0.8rem;margin:0.25rem 0 0 0;letter-spacing:0.06em;text-transform:uppercase;">
                Autonomous 3D Print Factory — Industrial Fleet Orchestration
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── OVERVIEW PAGE ─────────────────────────────────────────────────────────────

def _render_overview(engine: StateEngine) -> None:
    """Four-metric summary row + live telemetry + event log + optional auto-refresh."""
    st.markdown('<p class="nemo-section-header">System Status</p>', unsafe_allow_html=True)

    status    = engine.get_status()
    telemetry = mqtt_client.get_telemetry()
    spools    = inventory_manager.get_all_spools()

    # Determine active spool label
    active_spool_label = "—"
    job = status.get("job")
    if job and job.get("spool_id"):
        spool = inventory_manager.get_spool_by_id(job["spool_id"])
        if spool:
            active_spool_label = f"{spool.get('material')} / {spool.get('color')}"

    _render_overview_metrics(status, telemetry, active_spool_label)
    _render_telemetry_detail(telemetry)
    _render_event_log(status)
    _render_overview_controls(engine, status)


def _render_overview_metrics(status: dict, telemetry: dict, active_spool: str) -> None:
    """Four primary metric cards."""
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Engine State", status.get("state", "unknown").upper())
    with c2:
        bed_temp = telemetry.get("bed_temp", 0.0)
        st.metric("Bed Temp", f"{bed_temp:.1f}°C")
    with c3:
        pct = telemetry.get("print_percentage", 0)
        st.metric("Print Progress", f"{pct:.0f}%")
    with c4:
        st.metric("Active Spool", active_spool)


def _render_telemetry_detail(telemetry: dict) -> None:
    """Secondary telemetry row: nozzle temp, layer, remaining time."""
    st.markdown('<p class="nemo-section-header">Live Telemetry</p>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Nozzle Temp", f"{telemetry.get('nozzle_temp', 0.0):.1f}°C")
    with c2:
        layer     = telemetry.get("current_layer", 0)
        total_l   = telemetry.get("total_layers", 0)
        st.metric("Layer", f"{layer} / {total_l}")
    with c3:
        remaining = telemetry.get("remaining_time_min", 0)
        hrs, mins = divmod(remaining, 60)
        st.metric("Time Remaining", f"{hrs}h {mins:02d}m" if hrs > 0 else f"{mins}m")
    with c4:
        gcode = telemetry.get("gcode_state", "UNKNOWN")
        st.metric("G-Code State", gcode)

    # MQTT freshness badge
    last_ts = telemetry.get("last_message_timestamp")
    if last_ts:
        age = time.time() - last_ts
        if age < 30:
            badge_cls, badge_lbl = "status-ok", f"Fresh ({age:.0f}s ago)"
        elif age < 120:
            badge_cls, badge_lbl = "status-warn", f"Stale ({age:.0f}s ago)"
        else:
            badge_cls, badge_lbl = "status-error", f"Lost ({age:.0f}s ago)"
    else:
        badge_cls, badge_lbl = "status-error", "No Data"

    st.markdown(
        f'<span class="status-badge {badge_cls}">{badge_lbl}</span>',
        unsafe_allow_html=True,
    )


def _render_event_log(status: dict) -> None:
    """Last 50 state transition entries as a compact table."""
    st.markdown('<p class="nemo-section-header">State Transition Log</p>', unsafe_allow_html=True)
    transitions = status.get("transitions", [])
    if not transitions:
        st.info("No transitions recorded yet.")
        return

    df = pd.DataFrame(transitions[::-1])  # newest first
    df.rename(columns={
        "timestamp": "Time",
        "old_state": "From",
        "new_state": "To",
        "reason":    "Reason",
    }, inplace=True)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=280,
        column_config={
            "Time":   st.column_config.TextColumn("Time", width="medium"),
            "From":   st.column_config.TextColumn("From", width="small"),
            "To":     st.column_config.TextColumn("To",   width="small"),
            "Reason": st.column_config.TextColumn("Reason"),
        },
    )


def _render_overview_controls(engine: StateEngine, status: dict) -> None:
    """Manual job controls and auto-refresh toggle."""
    st.markdown("---")
    state = PrintState(status.get("state", "idle"))

    c1, c2, c3 = st.columns(3)
    with c1:
        if state == PrintState.IDLE:
            if st.button("Start Print Job", key="btn_start_job", type="primary"):
                try:
                    engine.start_job(file_name="manual_job", material="PLA", cycle_count=1)
                    st.success("Job started — engine now in PREPARING state.")
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
        else:
            st.button("Start Print Job", key="btn_start_job", disabled=True)

    with c2:
        if state in (PrintState.ERROR, PrintState.HALTED):
            if st.button("Reset Engine", key="btn_reset", type="primary"):
                engine.reset()
                st.success("Engine reset to IDLE.")
                st.rerun()

    with c3:
        if st.button("Refresh Now", key="btn_refresh"):
            st.rerun()

    # Auto-refresh when printing
    if state in (PrintState.PRINTING, PrintState.PREPARING, PrintState.COOLING, PrintState.CLEARING):
        st.caption("Auto-refresh active (every 5s — print in progress).")
        time.sleep(5)
        st.rerun()


# ── INVENTORY PAGE ────────────────────────────────────────────────────────────

def _render_inventory() -> None:
    """Full spool management UI: summary metrics, table, add/scan form, delete."""
    st.markdown('<p class="nemo-section-header">SpoolVault Inventory</p>', unsafe_allow_html=True)
    spools = inventory_manager.get_all_spools()
    _render_inventory_metrics(spools)
    _render_spool_table(spools)
    _render_add_spool_form()
    _render_delete_spool_panel(spools)


def _render_inventory_metrics(spools: list) -> None:
    """Summary count metrics above the spool table."""
    total     = len(spools)
    available = sum(1 for s in spools if s.get("status") == "Available")
    low       = sum(1 for s in spools if s.get("status") == "Low")
    depleted  = sum(1 for s in spools if s.get("status") == "Depleted")

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Total Spools", total)
    with c2: st.metric("Available",    available)
    with c3: st.metric("Low Stock",    low)
    with c4: st.metric("Depleted",     depleted)

    bc1, bc2, bc3, _ = st.columns([1, 1, 1, 3])
    with bc1:
        if st.button("Add Spool", key="btn_add_spool", type="primary"):
            st.session_state.add_spool_form_open = not st.session_state.add_spool_form_open
    with bc2:
        if st.button("Refresh", key="btn_inv_refresh"):
            st.rerun()


def _render_spool_table(spools: list) -> None:
    """Interactive spool dataframe with rich column configuration."""
    if not spools:
        st.info("No spools registered. Use 'Add Spool' to register your first spool.")
        return

    df = pd.DataFrame(spools)

    # Normalise expected columns
    for col, default in [
        ("spool_id",    "—"),
        ("material",    "Unknown"),
        ("color",       "Unknown"),
        ("brand",       "Unknown"),
        ("remaining_g", 0),
        ("status",      "Available"),
        ("last_used",   None),
    ]:
        if col not in df.columns:
            df[col] = default

    df["remaining_g"] = pd.to_numeric(df["remaining_g"], errors="coerce").fillna(0).astype(int)
    df["last_used"]   = pd.to_datetime(df["last_used"], errors="coerce", utc=True)

    display_cols = ["spool_id", "material", "color", "brand", "remaining_g", "status", "last_used"]
    df = df[[c for c in display_cols if c in df.columns]]

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=400,
        column_config={
            "spool_id":    st.column_config.TextColumn("ID",        width="small"),
            "material":    st.column_config.TextColumn("Material",  width="small"),
            "color":       st.column_config.TextColumn("Color"),
            "brand":       st.column_config.TextColumn("Brand"),
            "remaining_g": st.column_config.ProgressColumn(
                "Remaining",
                format="%d g",
                min_value=0,
                max_value=1000,
            ),
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=_SPOOL_STATUS_OPTIONS,
            ),
            "last_used": st.column_config.DatetimeColumn(
                "Last Used",
                format="DD MMM YYYY, HH:mm",
            ),
        },
    )


def _render_add_spool_form() -> None:
    """Collapsible add spool form with optional camera scan for AI auto-population."""
    if not st.session_state.add_spool_form_open:
        return

    st.markdown("---")
    st.markdown('<p class="nemo-section-header">Register New Spool</p>', unsafe_allow_html=True)

    # Camera scan section
    with st.expander("Scan Spool Label with Camera", expanded=False):
        camera_image = st.camera_input("Point camera at spool label", key="spool_camera_scan")
        if camera_image is not None:
            img_bytes = camera_image.getvalue()
            b64_img   = base64.b64encode(img_bytes).decode("utf-8")
            with st.spinner("Scanning label with NVIDIA vision model..."):
                scanned = vision_service.capture_for_ai(b64_img)
            if scanned:
                st.session_state.scanned_spool_data = scanned
                st.success("Label scanned successfully — fields auto-populated below.")
            else:
                st.warning("Could not extract data from the label. Fill in fields manually.")

    pre = st.session_state.scanned_spool_data

    with st.form(key="add_spool_form", clear_on_submit=True):
        r1c1, r1c2, r1c3 = st.columns(3)
        with r1c1:
            spool_id = st.text_input("Spool ID", value="", placeholder="SP-2024-001")
        with r1c2:
            brand    = st.text_input("Brand", value=pre.get("brand", ""), placeholder="Bambu Lab")
        with r1c3:
            mat_opts = _MATERIAL_OPTIONS
            mat_val  = pre.get("material", "PLA")
            mat_idx  = mat_opts.index(mat_val) if mat_val in mat_opts else 0
            material = st.selectbox("Material", options=mat_opts, index=mat_idx)

        r2c1, r2c2, r2c3 = st.columns(3)
        with r2c1:
            color = st.text_input("Color", value=pre.get("color", ""), placeholder="Matte Black")
        with r2c2:
            default_remaining = int(pre.get("remaining_g", 1000) or 1000)
            remaining_g = st.number_input(
                "Remaining (g)", min_value=0, max_value=2000, value=default_remaining, step=10
            )
        with r2c3:
            total_g = st.number_input(
                "Total (g)", min_value=0, max_value=2000, value=int(pre.get("total_g", 1000) or 1000), step=10
            )

        r3c1, r3c2, r3c3 = st.columns(3)
        with r3c1:
            status = st.selectbox("Status", options=_SPOOL_STATUS_OPTIONS)
        with r3c2:
            serial = st.text_input("Serial #", value=pre.get("serial_number", "") or "", placeholder="Optional")
        with r3c3:
            ams_slot_val = st.number_input("AMS Slot", min_value=0, max_value=16, value=0, step=1)

        submitted = st.form_submit_button("Register Spool", type="primary")

    if submitted:
        _handle_add_spool(
            spool_id=spool_id.strip(),
            brand=brand.strip(),
            material=material,
            color=color.strip(),
            remaining_g=int(remaining_g),
            total_g=int(total_g),
            status=status,
            serial_number=serial.strip() or None,
            ams_slot=int(ams_slot_val) if ams_slot_val > 0 else None,
        )


def _handle_add_spool(
    spool_id: str,
    brand:    str,
    material: str,
    color:    str,
    remaining_g: int,
    total_g: int,
    status: str,
    serial_number: Optional[str],
    ams_slot: Optional[int],
) -> None:
    """Validates and persists a new spool via inventory_manager."""
    if not spool_id:
        st.error("Spool ID is required.")
        return

    all_spools = inventory_manager.get_all_spools()
    existing_ids = {s.get("spool_id") for s in all_spools}
    if spool_id in existing_ids:
        st.error(f"Spool ID '{spool_id}' already exists. Use a unique identifier.")
        return

    new_spool = inventory_manager.add_spool({
        "spool_id":      spool_id,
        "brand":         brand or "Unknown",
        "material":      material,
        "color":         color or "Unknown",
        "remaining_g":   remaining_g,
        "total_g":       total_g,
        "status":        status,
        "serial_number": serial_number,
        "ams_slot":      ams_slot,
    })

    st.success(f"Spool {new_spool['spool_id']} registered successfully.")
    st.session_state.add_spool_form_open = False
    st.session_state.scanned_spool_data  = {}
    st.rerun()


def _render_delete_spool_panel(spools: list) -> None:
    """Inline delete control for removing a spool by ID."""
    if not spools:
        return

    st.markdown("---")
    st.markdown('<p class="nemo-section-header">Remove Spool</p>', unsafe_allow_html=True)

    spool_options = [s.get("spool_id", "—") for s in spools]
    dc1, dc2, _ = st.columns([2, 1, 3])
    with dc1:
        del_id = st.selectbox("Select spool to delete", options=spool_options, key="del_spool_select")
    with dc2:
        if st.button("Delete", key="btn_del_spool"):
            deleted = inventory_manager.delete_spool(del_id)
            if deleted:
                st.success(f"Spool {del_id} deleted.")
                st.rerun()
            else:
                st.error(f"Spool {del_id} not found.")


# ── HARDWARE PAGE ─────────────────────────────────────────────────────────────

def _render_hardware() -> None:
    """ESP32 status, manual override controls, result viewer."""
    st.markdown('<p class="nemo-section-header">ESP32 Hardware Controller</p>', unsafe_allow_html=True)

    # Connection status check
    with st.spinner("Pinging ESP32..."):
        reachable, latency_ms = _check_esp32_connection()

    if reachable:
        lbl = f"Online ({latency_ms:.0f}ms)" if latency_ms else "Online"
        st.markdown(
            f'<span class="status-badge status-ok">{lbl}</span>'
            f'<span style="font-size:0.75rem;color:#8a8a9a;margin-left:0.5rem;">'
            f'ESP32 at {ESP32_HOST}</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<span class="status-badge status-error">Unreachable</span>'
            f'<span style="font-size:0.75rem;color:#8a8a9a;margin-left:0.5rem;">'
            f'ESP32 at {ESP32_HOST}</span>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<p class="nemo-section-header">Direct Actuator Commands</p>', unsafe_allow_html=True)

    velocity = st.slider(
        "Sweep Velocity",
        min_value=10,
        max_value=100,
        value=st.session_state.sweep_velocity,
        key="hw_page_velocity",
    )
    st.session_state.sweep_velocity = velocity

    bc1, bc2, bc3, bc4 = st.columns(4)
    hw_result = None

    with bc1:
        if st.button("Trigger Sweep", key="hw_btn_sweep", type="primary", use_container_width=True):
            with st.spinner("Sending sweep command..."):
                hw_result = actuator_service.trigger_sweep(velocity)
            st.session_state.hw_last_result = hw_result

    with bc2:
        if st.button("Trigger Tap", key="hw_btn_tap", use_container_width=True):
            with st.spinner("Sending tap command..."):
                hw_result = actuator_service.trigger_tap()
            st.session_state.hw_last_result = hw_result

    with bc3:
        if st.button("Trigger Push", key="hw_btn_push", use_container_width=True):
            with st.spinner("Sending push command..."):
                hw_result = actuator_service.trigger_push()
            st.session_state.hw_last_result = hw_result

    with bc4:
        if st.button("ABORT", key="hw_btn_abort", use_container_width=True):
            with st.spinner("Sending abort command..."):
                hw_result = actuator_service.trigger_abort()
            st.session_state.hw_last_result = hw_result

    # Show last result
    if st.session_state.hw_last_result:
        result = st.session_state.hw_last_result
        if result.get("success"):
            st.success(f"Command succeeded ({result.get('latency_ms', '—')}ms)")
        else:
            st.error(f"Command failed: {result.get('error', 'unknown')}")
        with st.expander("Full result payload", expanded=False):
            st.json(result)

    st.markdown("---")
    st.markdown('<p class="nemo-section-header">Full Clearance Sequence</p>', unsafe_allow_html=True)
    st.caption("Runs tap-tap → push-push → vision verify. Retries up to 3 times. Triggers ABORT if all retries fail.")
    if st.button("Execute Clearance Sequence", key="hw_btn_clearance", type="primary"):
        with st.spinner("Running clearance sequence..."):
            result = actuator_service.execute_clearance_sequence()
        if result.get("success"):
            st.success(f"Bed cleared in {result.get('attempts')} attempt(s).")
        else:
            st.error(f"Clearance failed after {result.get('attempts')} attempts — {result.get('final_status')}.")
        with st.expander("Sequence result", expanded=True):
            st.json(result)


# ── LOGS PAGE ─────────────────────────────────────────────────────────────────

def _render_logs(engine: StateEngine) -> None:
    """State transition history table + MQTT status + raw telemetry JSON."""
    st.markdown('<p class="nemo-section-header">State Transition History</p>', unsafe_allow_html=True)

    status = engine.get_status()
    transitions = status.get("transitions", [])
    if transitions:
        df = pd.DataFrame(transitions[::-1])
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=300,
            column_config={
                "timestamp": st.column_config.TextColumn("Time"),
                "old_state": st.column_config.TextColumn("From", width="small"),
                "new_state": st.column_config.TextColumn("To",   width="small"),
                "reason":    st.column_config.TextColumn("Reason"),
            },
        )
    else:
        st.info("No state transitions recorded yet.")

    st.markdown('<p class="nemo-section-header">MQTT Telemetry</p>', unsafe_allow_html=True)
    telemetry = mqtt_client.get_telemetry()
    mqtt_ok   = telemetry.get("mqtt_connected", False)
    last_ts   = telemetry.get("last_message_timestamp")

    badge_cls = "status-ok" if mqtt_ok else "status-error"
    badge_lbl = "Connected" if mqtt_ok else "Disconnected"
    last_str  = (
        datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if last_ts else "Never"
    )

    st.markdown(
        f'<span class="status-badge {badge_cls}">{badge_lbl}</span>'
        f'<span style="font-size:0.75rem;color:#8a8a9a;margin-left:0.5rem;">Last message: {last_str}</span>',
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<p class="nemo-section-header">Raw Telemetry</p>', unsafe_allow_html=True)
    st.json(telemetry)

    st.markdown('<p class="nemo-section-header">System Log File</p>', unsafe_allow_html=True)
    log_lines = _read_recent_log_lines(80)
    if log_lines:
        st.code("\n".join(log_lines), language=None)
    else:
        st.info("Log file is empty or not yet created.")

    if st.button("Refresh Logs", key="btn_refresh_logs"):
        st.rerun()


def _read_recent_log_lines(n: int) -> list:
    """Returns the last n lines from the sentinel log file."""
    try:
        text = Path(SENTINEL_LOG).read_text(encoding="utf-8", errors="replace")
        return text.splitlines()[-n:]
    except FileNotFoundError:
        return []
    except OSError as exc:
        log.warning("Could not read log file: %s", exc)
        return []


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Streamlit application entry point. Called on every script rerun."""
    _apply_design_system()
    _init_session_state()

    engine = _ensure_engine()
    _render_sidebar(engine)

    page = st.session_state.page
    _render_page_header(page)

    match page:
        case "Overview":
            _render_overview(engine)
        case "Inventory":
            _render_inventory()
        case "Hardware":
            _render_hardware()
        case "Logs":
            _render_logs(engine)
        case _:
            log.warning("Unknown page '%s' — falling back to Overview.", page)
            st.session_state.page = "Overview"
            _render_overview(engine)


if __name__ == "__main__":
    main()
