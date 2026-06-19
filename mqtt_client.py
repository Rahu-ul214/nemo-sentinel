# ── STANDARD LIBRARY ──────────────────────────────────────────────────────────
import logging
import threading
import time
from copy import deepcopy
from typing import Any

# ── LOCAL ─────────────────────────────────────────────────────────────────────
import inventory_manager
from config import MOCK_MODE, PRINTER_SERIAL

log = logging.getLogger("nemo.mqtt")

# ── MODULE STATE ──────────────────────────────────────────────────────────────
_telemetry_lock = threading.Lock()
_latest_telemetry: dict = {
    "gcode_state":           "UNKNOWN",
    "print_percentage":       0,
    "current_layer":          0,
    "total_layers":           0,
    "nozzle_temp":            0.0,
    "bed_temp":               0.0,
    "remaining_time_min":     0,
    "ams_slots":              [],
    "error_codes":            [],
    "mqtt_connected":         False,
    "last_message_timestamp": None,
}

_client_thread: threading.Thread | None = None
_started = threading.Event()

# ── INTERNAL TELEMETRY UPDATER ────────────────────────────────────────────────

def _update_telemetry(**kwargs: Any) -> None:
    """Thread-safe update of the module-level telemetry dict."""
    with _telemetry_lock:
        _latest_telemetry.update(kwargs)
        _latest_telemetry["last_message_timestamp"] = time.time()


# ── AMS SYNC BRIDGE ───────────────────────────────────────────────────────────

def _handle_ams_payload(ams_list: list) -> None:
    """
    Converts raw MQTT AMS payload into the format expected by
    inventory_manager.sync_from_ams() and calls it.
    """
    slots = []
    for tray_idx, tray in enumerate(ams_list):
        for slot_idx, slot in enumerate(tray.get("slots", [])):
            slots.append({
                "ams_slot":  slot_idx,
                "material":  slot.get("material", "Unknown"),
                "remaining": slot.get("remain", slot.get("remaining", 0)),
            })

    if slots:
        inventory_manager.sync_from_ams({"slots": slots})


# ── MQTT LOOP THREAD ───────────────────────────────────────────────────────────

def _run_listener() -> None:
    """
    Background daemon thread that owns the BambuMqttClient lifecycle.
    Wraps the existing services/telemetry.py implementation so that the
    hard-won Bambu authentication flow is never reimplemented.
    """
    # We import inside the thread function so that import errors are contained
    # and do not crash the Streamlit UI on startup.
    try:
        from services.telemetry import BambuMqttClient
        from core.state import STATUS
    except ImportError as exc:
        log.error("Could not import BambuMqttClient: %s — MQTT listener aborted.", exc)
        _update_telemetry(mqtt_connected=False)
        return

    backoff = 5
    max_backoff = 60

    while True:
        try:
            client = BambuMqttClient()

            # Monkey-patch the on_message callback to also populate our telemetry dict
            original_on_message = client._on_message

            def _patched_on_message(mqtt_client, userdata, msg):
                # Let the original handler update STATUS (global state object)
                original_on_message(mqtt_client, userdata, msg)

                # Also update our module-level telemetry dict for the dashboard
                try:
                    import json as _json
                    payload = _json.loads(msg.payload.decode("utf-8"))
                    print_data = payload.get("print") or payload.get("status") or payload

                    _update_telemetry(
                        gcode_state=str(print_data.get("gcode_state", "UNKNOWN")),
                        print_percentage=float(print_data.get("mc_percent", 0)),
                        current_layer=int(print_data.get("layer_num", 0)),
                        total_layers=int(print_data.get("total_layer_num", 0)),
                        nozzle_temp=float(print_data.get("nozzle_temper", 0.0)),
                        bed_temp=float(print_data.get("bed_temper", 0.0)),
                        remaining_time_min=int(print_data.get("mc_remaining_time", 0)),
                        error_codes=print_data.get("error_codes", []),
                        mqtt_connected=True,
                    )

                    # AMS sync
                    ams_raw = payload.get("ams")
                    if isinstance(ams_raw, list):
                        _handle_ams_payload(ams_raw)

                except Exception as exc:
                    log.warning("Telemetry update from MQTT message failed: %s", exc)

            client._on_message = _patched_on_message

            # Patch the on_connect and on_disconnect callbacks for connection state tracking
            original_on_connect = client._on_connect
            original_on_disconnect = client._on_disconnect

            def _patched_on_connect(mqtt_client, userdata, flags, rc):
                original_on_connect(mqtt_client, userdata, flags, rc)
                _update_telemetry(mqtt_connected=(rc == 0))
                nonlocal backoff
                backoff = 5  # Reset backoff on successful connect

            def _patched_on_disconnect(mqtt_client, userdata, rc):
                original_on_disconnect(mqtt_client, userdata, rc)
                _update_telemetry(mqtt_connected=False)

            client._on_connect    = _patched_on_connect
            client._on_disconnect = _patched_on_disconnect

            client.connect()
            client.start()

            _update_telemetry(mqtt_connected=True)
            log.info("NEMO MQTT listener started (device=%s, mock=%s).", PRINTER_SERIAL, MOCK_MODE)

            # Keep thread alive; BambuMqttClient runs its own loop internally
            while True:
                time.sleep(10)
                # In mock mode, the simulator thread handles updates.
                # In live mode, on_disconnect will trigger a new loop iteration.
                if not MOCK_MODE and not STATUS.mqtt_connected:
                    log.warning("MQTT disconnected — scheduling reconnect in %ds.", backoff)
                    break

        except Exception as exc:
            log.error("MQTT listener error: %s — retrying in %ds.", exc, backoff)
            _update_telemetry(mqtt_connected=False)

        time.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def start_mqtt_listener() -> None:
    """
    Idempotent — starts the background MQTT listener thread exactly once.
    Safe to call multiple times.
    """
    global _client_thread

    if _started.is_set():
        log.debug("start_mqtt_listener() called but listener already running.")
        return

    _started.set()
    _client_thread = threading.Thread(
        target=_run_listener,
        name="nemo-mqtt-listener",
        daemon=True,
    )
    _client_thread.start()
    log.info("NEMO MQTT listener thread started.")


def get_telemetry() -> dict:
    """
    Returns a safe deep copy of the latest parsed telemetry.
    Thread-safe. Never raises.
    """
    with _telemetry_lock:
        return deepcopy(_latest_telemetry)
