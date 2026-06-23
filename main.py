import logging
import time

from core.config import ESP32_IP, SENTINEL_LOG
from core.state import STATUS, SentinelState, is_hardware_blocked
from services.hardware import ESP32Manager
from services.telemetry import BambuMqttClient
import services.actuator_service as actuator
from api_server import start_api_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(SENTINEL_LOG),
    ],
)
log = logging.getLogger("sentinel.main")

POLL_INTERVAL_SEC = 5
SWEEP_COOLDOWN_SEC = 300


def trigger_physical_sweep(hw_manager: ESP32Manager) -> bool:
    if is_hardware_blocked():
        snapshot = STATUS.get_snapshot()
        log.warning(
            "Physical sweep blocked by safety interlock (state=%s, awaiting_ejection=%s)",
            snapshot["state"].name,
            snapshot.get("awaiting_ejection"),
        )
        return False

    log.info(
        "[HARDWARE] Bambu Cloud reported FINISH — initiating physical bed sweep via ESP32 at %s",
        ESP32_IP,
    )
    STATUS.update(state=SentinelState.RECOVERY_SWEEPING, awaiting_ejection=True)

    success, message = hw_manager.trigger_sweep()
    if success:
        log.info("[HARDWARE] Physical sweep initiated successfully: %s", message)
        return True

    log.error("[HARDWARE] Physical sweep failed: %s", message)
    STATUS.update(awaiting_ejection=False)
    return False


def run_loop():
    try:
        # 1. Initialize API Server for the Dashboard
        log.info("[SYSTEM] Starting API Server on port 8000...")
        start_api_server(port=8000)

        # 2. Initialize MQTT telemetry client
        mqtt_client = BambuMqttClient()
        mqtt_client.connect()
        mqtt_client.start()
        log.info("[SYSTEM] MQTT telemetry stream started.")
    except Exception as exc:
        log.error("Critical initialization failure: %s", exc)
        return

    hw_manager = ESP32Manager(ESP32_IP)

    # Cooldown tracking
    last_sweep_time = 0

    while True:
        try:
            # Observe the global STATUS updated by MQTT callbacks
            gcode_state = STATUS.gcode_state

            if gcode_state == "FINISH":
                current_time = time.time()
                if (current_time - last_sweep_time) > SWEEP_COOLDOWN_SEC:
                    log.info("Detected print finish via MQTT. Triggering lauch of sweeper arm...")

                    if actuator.trigger_sweeper_arm():
                        last_sweep_time = current_time
                        STATUS.update(gcode_state="IDLE")
                    else:
                        log.error("Slicing hardware bridge failed to trigger arm.")
                else:
                    log.debug("Print is FINISH, but sweeper arm is in cooldown period.")

        except Exception as exc:
            log.error("Error in main loop: %s", exc)

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    run_loop()
