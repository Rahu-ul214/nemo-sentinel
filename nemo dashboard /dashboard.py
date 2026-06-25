"""
NEMO Fleet Management Dashboard
Real-time monitoring and tactical control of autonomous 3D printing fleet
Built with Streamlit + MQTT telemetry + Bambu Cloud integration
"""

import streamlit as st
import time
from datetime import datetime
import pandas as pd
from mqtt_service import MQTTTelemetryService
from fleet_service import FleetAggregationService
from control_service import TacticalControlService
from models import PrinterStatus
import os

# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title="NEMO Fleet Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

if 'mqtt_service' not in st.session_state:
    # Initialize services on first load
    st.session_state.mqtt_service = None
    st.session_state.fleet_service = FleetAggregationService()
    st.session_state.control_service = None
    st.session_state.connection_initialized = False
    st.session_state.last_update = None
    st.session_state.update_interval = 2  # seconds

# ============================================================================
# CONFIGURATION
# ============================================================================

MQTT_CONFIG = {
    'broker_host': os.getenv('BAMBU_MQTT_HOST', 'us.mqtt.bambulab.com'),
    'broker_port': int(os.getenv('BAMBU_MQTT_PORT', '8883')),
    'username': os.getenv('BAMBU_MQTT_USER', ''),
    'password': os.getenv('BAMBU_MQTT_PASS', ''),
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def initialize_connection():
    """Initialize MQTT connection"""
    if not MQTT_CONFIG['username'] or not MQTT_CONFIG['password']:
        st.error("❌ MQTT credentials not configured. Set BAMBU_MQTT_USER and BAMBU_MQTT_PASS environment variables.")
        return False

    try:
        st.session_state.mqtt_service = MQTTTelemetryService(
            broker_host=MQTT_CONFIG['broker_host'],
            broker_port=MQTT_CONFIG['broker_port'],
            username=MQTT_CONFIG['username'],
            password=MQTT_CONFIG['password'],
        )
        st.session_state.control_service = TacticalControlService(st.session_state.mqtt_service)
        st.session_state.mqtt_service.connect()
        st.session_state.connection_initialized = True
        time.sleep(2)  # Give MQTT time to connect
        return True
    except Exception as e:
        st.error(f"❌ Failed to initialize MQTT: {str(e)}")
        return False

def get_printers():
    """Fetch all printer telemetry"""
    if not st.session_state.mqtt_service:
        return {}
    return st.session_state.mqtt_service.get_all_printers()

def get_mqtt_status():
    """Get MQTT connection status"""
    if not st.session_state.mqtt_service:
        return "not_initialized"
    return st.session_state.mqtt_service.connection_status

def format_time(seconds: int) -> str:
    """Format seconds to HH:MM:SS"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def get_status_color(status: PrinterStatus) -> str:
    """Get Streamlit color for printer status"""
    colors = {
        PrinterStatus.IDLE: '🟢',
        PrinterStatus.PRINTING: '🔵',
        PrinterStatus.PAUSED: '🟡',
        PrinterStatus.ERROR: '🔴',
        PrinterStatus.OFFLINE: '⚫',
        PrinterStatus.MAINTENANCE: '🟠',
    }
    return colors.get(status, '⚪')

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.title("⚙️ NEMO Control Panel")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("**Fleet Management System**")
    with col2:
        if st.button("🔄", help="Reconnect to MQTT", use_container_width=True):
            if st.session_state.mqtt_service:
                st.session_state.mqtt_service.disconnect()
            st.session_state.mqtt_service = None
            st.session_state.connection_initialized = False
            st.rerun()

    st.divider()

    # Connection Status
    mqtt_status = get_mqtt_status()
    status_icon = "🟢" if mqtt_status == "connected" else "🔴"
    st.markdown(f"{status_icon} **MQTT Status:** {mqtt_status.upper()}")

    if not st.session_state.connection_initialized:
        if st.button("🚀 Connect to Bambu Cloud", use_container_width=True):
            with st.spinner("Connecting to MQTT broker..."):
                if initialize_connection():
                    st.success("✅ Connected to Bambu Cloud")
                    st.rerun()
    else:
        service_status = st.session_state.mqtt_service.get_status()
        st.metric("Printers Detected", service_status['total_printers'])
        st.metric("Messages Received", service_status['messages_received'])

    st.divider()

    # Update interval
    st.session_state.update_interval = st.slider(
        "Update Interval (seconds)",
        min_value=1,
        max_value=10,
        value=st.session_state.update_interval
    )

    st.divider()

    # Navigation
    st.markdown("**Quick Navigation**")
    page = st.radio(
        "Select View",
        ["📊 Dashboard", "🖨️ Fleet Status", "📡 Telemetry Feed", "🎮 Controls", "📦 Inventory", "🔍 Diagnostics"],
        label_visibility="collapsed"
    )

    st.divider()
    st.caption("NEMO v1.0 | Autonomous Fleet Management")

# ============================================================================
# MAIN CONTENT
# ============================================================================

# Main heading
col1, col2 = st.columns([3, 1])
with col1:
    st.title("🤖 NEMO Fleet Dashboard")
    st.markdown("Real-time autonomous 3D printing fleet orchestration")
with col2:
    if st.session_state.connection_initialized:
        st.metric("", "🟢 CONNECTED")
    else:
        st.metric("", "🔴 OFFLINE")

st.divider()

if not st.session_state.connection_initialized:
    st.warning("⚠️ MQTT connection not initialized. Click 'Connect to Bambu Cloud' in the sidebar to start.")
    st.stop()

# ============================================================================
# PAGE: DASHBOARD
# ============================================================================

if page == "📊 Dashboard":
    printers = get_printers()
    mqtt_status = get_mqtt_status()
    
    if printers:
        # Compute aggregates
        aggregates = st.session_state.fleet_service.compute_fleet_aggregates(
            printers, mqtt_status
        )
        health = st.session_state.fleet_service.get_system_health(printers)

        # TOP METRICS
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("Total Printers", aggregates.total_printers, delta=aggregates.active_printers)
        with col2:
            st.metric("Printing", aggregates.printing_printers)
        with col3:
            st.metric("Idle", aggregates.idle_printers)
        with col4:
            st.metric("Errors", aggregates.error_printers)
        with col5:
            st.metric("Offline", aggregates.offline_printers)
        with col6:
            st.metric("System Health", f"{health['health_score']:.0f}%")

        st.divider()

        # FLEET PROGRESS
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("📈 Fleet Print Progress")
            st.progress(aggregates.fleet_print_progress / 100)
            st.caption(f"Average progress: {aggregates.fleet_print_progress:.1f}%")
        with col2:
            st.subheader("⏱️ Next Completion")
            eta = format_time(aggregates.estimated_completion_time)
            st.metric("ETA", eta)

        st.divider()

        # PRINTER GRID
        st.subheader("🖨️ Fleet Overview")
        cols = st.columns(min(3, len(printers)))
        
        for idx, (printer_id, printer) in enumerate(printers.items()):
            with cols[idx % len(cols)]:
                with st.container(border=True):
                    # Header
                    st.markdown(
                        f"{get_status_color(printer.status)} **{printer.printer_name}** | {printer.model.value}"
                    )
                    st.caption(f"ID: {printer_id[:8]}... | {printer.ip_address}")

                    # Thermal
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.metric(
                            "Nozzle",
                            f"{printer.thermal.nozzle_temp:.0f}°C",
                            f"→{printer.thermal.nozzle_target:.0f}°C"
                        )
                    with col_b:
                        st.metric(
                            "Bed",
                            f"{printer.thermal.bed_temp:.0f}°C",
                            f"→{printer.thermal.bed_target:.0f}°C"
                        )

                    # Job progress
                    if printer.job and printer.status == PrinterStatus.PRINTING:
                        st.progress(printer.job.progress_percent / 100)
                        st.caption(
                            f"{printer.job.progress_percent:.1f}% | "
                            f"{format_time(printer.job.time_remaining)} remaining"
                        )
                    else:
                        st.caption(f"Status: {printer.status.value}")

    else:
        st.info("⏳ Waiting for printer data from Bambu Cloud...")
        st.info("Make sure printers are powered on and connected to the same cloud account.")

# ============================================================================
# PAGE: FLEET STATUS
# ============================================================================

elif page == "🖨️ Fleet Status":
    printers = get_printers()
    
    if printers:
        st.subheader("Detailed Fleet Status")
        
        # Build status dataframe
        status_data = []
        for printer_id, printer in printers.items():
            status_data.append({
                'Printer': printer.printer_name,
                'Model': printer.model.value,
                'Status': printer.status.value,
                'Nozzle (°C)': f"{printer.thermal.nozzle_temp:.0f}",
                'Bed (°C)': f"{printer.thermal.bed_temp:.0f}",
                'WiFi (dBm)': printer.wifi_signal_strength,
                'IP Address': printer.ip_address,
                'Uptime (h)': f"{printer.uptime_hours:.1f}",
            })

        df = pd.DataFrame(status_data)
        st.dataframe(df, use_container_width=True)

        st.divider()

        # Anomalies
        st.subheader("🚨 Detected Anomalies")
        anomalies_found = False
        for printer_id, printer in printers.items():
            anomalies = st.session_state.fleet_service.detect_anomalies(printer)
            if anomalies:
                anomalies_found = True
                with st.container(border=True):
                    st.warning(f"**{printer.printer_name}**: {', '.join(anomalies)}")

        if not anomalies_found:
            st.success("✅ No anomalies detected")
    else:
        st.info("⏳ No printer data available")

# ============================================================================
# PAGE: TELEMETRY FEED
# ============================================================================

elif page == "📡 Telemetry Feed":
    st.subheader("Live Telemetry Stream")
    
    printers = get_printers()
    if printers:
        # Telemetry table
        telemetry_data = []
        for printer_id, printer in printers.items():
            if printer.job and printer.status == PrinterStatus.PRINTING:
                telemetry_data.append({
                    'Printer': printer.printer_name,
                    'Job': printer.job.job_name,
                    'Material': printer.job.print_type,
                    'Progress': f"{printer.job.progress_percent:.1f}%",
                    'Speed': f"{printer.job.print_speed:.0f} mm/s",
                    'Layer': f"{printer.job.current_layer}/{printer.job.total_layers}",
                    'Elapsed': format_time(printer.job.time_elapsed),
                    'Remaining': format_time(printer.job.time_remaining),
                    'Weight': f"{printer.job.weight_used:.1f}g",
                })

        if telemetry_data:
            df_telemetry = pd.DataFrame(telemetry_data)
            st.dataframe(df_telemetry, use_container_width=True)
        else:
            st.info("No active print jobs")

        st.divider()

        # Thermal overview
        st.subheader("🌡️ Thermal Telemetry")
        thermal_data = []
        for printer_id, printer in printers.items():
            thermal_data.append({
                'Printer': printer.printer_name,
                'Nozzle Current': printer.thermal.nozzle_temp,
                'Nozzle Target': printer.thermal.nozzle_target,
                'Bed Current': printer.thermal.bed_temp,
                'Bed Target': printer.thermal.bed_target,
                'Chamber': printer.thermal.chamber_temp or 'N/A',
            })

        df_thermal = pd.DataFrame(thermal_data)
        st.dataframe(df_thermal, use_container_width=True)

    else:
        st.info("⏳ No data available")

# ============================================================================
# PAGE: CONTROLS
# ============================================================================

elif page == "🎮 Controls":
    st.subheader("Tactical Control Interface")
    
    printers = get_printers()
    if printers:
        col1, col2 = st.columns([1, 3])
        
        with col1:
            printer_name = st.selectbox(
                "Select Printer",
                list(printers.keys()),
                format_func=lambda x: printers[x].printer_name
            )
        
        selected_printer = printers[printer_name]

        with col2:
            st.markdown(
                f"{get_status_color(selected_printer.status)} "
                f"**{selected_printer.printer_name}** - {selected_printer.status.value.upper()}"
            )

        st.divider()

        # Command buttons
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("⏸️ Pause Job", use_container_width=True):
                success, msg = st.session_state.control_service.pause_job(printer_name, selected_printer)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

        with col2:
            if st.button("▶️ Resume Job", use_container_width=True):
                success, msg = st.session_state.control_service.resume_job(printer_name, selected_printer)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

        with col3:
            if st.button("❌ Cancel Job", use_container_width=True):
                success, msg = st.session_state.control_service.cancel_job(printer_name, selected_printer)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

        st.divider()

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("🧹 Clear Bed (NEMO)", use_container_width=True, type="secondary"):
                success, msg = st.session_state.control_service.clear_bed(printer_name, selected_printer)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

        with col2:
            if st.button("🏠 Home All", use_container_width=True, type="secondary"):
                success, msg = st.session_state.control_service.home_axis(printer_name, selected_printer, 'all')
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

        with col3:
            if st.button("🎬 Emergency Stop", use_container_width=True, type="secondary"):
                success, msg = st.session_state.control_service.emergency_stop(printer_name)
                if success:
                    st.warning(msg)
                else:
                    st.error(msg)

        st.divider()

        # Temperature control
        st.subheader("🌡️ Temperature Control")
        col1, col2 = st.columns(2)

        with col1:
            nozzle_temp = st.number_input(
                "Nozzle Temperature (°C)",
                min_value=150,
                max_value=260,
                value=int(selected_printer.thermal.nozzle_target),
                step=5
            )

        with col2:
            bed_temp = st.number_input(
                "Bed Temperature (°C)",
                min_value=20,
                max_value=120,
                value=int(selected_printer.thermal.bed_target),
                step=5
            )

        if st.button("📤 Apply Temperature Settings", use_container_width=True):
            success, msg = st.session_state.control_service.set_temperature(
                printer_name, selected_printer,
                nozzle_temp=nozzle_temp,
                bed_temp=bed_temp
            )
            if success:
                st.success(msg)
            else:
                st.error(msg)

        st.divider()

        # Filament control
        st.subheader("🎛️ Filament Management")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("📥 Load Filament", use_container_width=True):
                success, msg = st.session_state.control_service.load_filament(printer_name, selected_printer)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

        with col2:
            if st.button("📤 Unload Filament", use_container_width=True):
                success, msg = st.session_state.control_service.unload_filament(printer_name, selected_printer)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

    else:
        st.info("⏳ No printers available")

# ============================================================================
# PAGE: INVENTORY
# ============================================================================

elif page == "📦 Inventory":
    st.subheader("Fleet Inventory & Spool Management")
    
    printers = get_printers()
    if printers:
        inventory = st.session_state.fleet_service.get_inventory_summary(printers)

        # Summary metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Filament", f"{inventory['total_weight_grams']:.0f}g")
        with col2:
            st.metric("Material Types", len(inventory['by_material']))
        with col3:
            st.metric("Low Stock Alerts", len(inventory['low_stock_alerts']))

        st.divider()

        # By Material
        st.subheader("📊 Inventory by Material")
        for material, data in inventory['by_material'].items():
            with st.container(border=True):
                st.markdown(f"**{material}** - {data['total_weight']:.0f}g total")
                for spool in data['spools']:
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.caption(f"🖨️ {spool['printer']}")
                    with col2:
                        st.progress(spool['percent'] / 100)
                    with col3:
                        st.caption(f"{spool['percent']:.0f}% ({spool['weight']:.0f}g)")

        st.divider()

        # Low Stock Warnings
        if inventory['low_stock_alerts']:
            st.subheader("⚠️ Low Stock Alerts")
            for alert in inventory['low_stock_alerts']:
                st.warning(
                    f"**{alert['printer']}**: {alert['material']} at {alert['percent']:.1f}% "
                    f"({alert['weight']:.1f}g remaining)"
                )
        else:
            st.success("✅ All spools have adequate filament")

    else:
        st.info("⏳ No inventory data available")

# ============================================================================
# PAGE: DIAGNOSTICS
# ============================================================================

elif page == "🔍 Diagnostics":
    st.subheader("System Health Diagnostics")
    
    printers = get_printers()
    if printers:
        health = st.session_state.fleet_service.get_system_health(printers)

        # Health score
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Overall Health", f"{health['health_score']:.0f}%")
        with col2:
            st.metric("Connectivity", f"{health['connectivity_health']:.0f}%")
        with col3:
            st.metric("Thermal", f"{health['thermal_health']:.0f}%")
        with col4:
            st.metric("Inventory", f"{health['inventory_health']:.0f}%")
        with col5:
            st.metric("Error Status", f"{health['error_health']:.0f}%")

        st.divider()

        # Status
        if health['overall_health'] == 'excellent':
            st.success(f"✅ **System Status: EXCELLENT** ({health['health_score']:.1f}/100)")
        elif health['overall_health'] == 'good':
            st.info(f"ℹ️ **System Status: GOOD** ({health['health_score']:.1f}/100)")
        elif health['overall_health'] == 'warning':
            st.warning(f"⚠️ **System Status: WARNING** ({health['health_score']:.1f}/100)")
        else:
            st.error(f"🔴 **System Status: CRITICAL** ({health['health_score']:.1f}/100)")

        st.divider()

        # Alerts
        if health['alerts']:
            st.subheader("🚨 Active Alerts")
            for alert in health['alerts']:
                st.warning(alert)
        else:
            st.success("✅ No active alerts")

    else:
        st.info("⏳ No diagnostic data available")

# ============================================================================
# AUTO-REFRESH
# ============================================================================

placeholder = st.empty()
time.sleep(st.session_state.update_interval)
st.rerun()
