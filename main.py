# ── STANDARD LIBRARY ──────────────────────────────────────────────────────────
import logging
import logging.handlers
import time
from pathlib import Path

# ── LOCAL ─────────────────────────────────────────────────────────────────────
from config import SENTINEL_LOG
from mqtt_client import start_mqtt_listener
from state_engine import StateEngine

# ── LOGGING SETUP ─────────────────────────────────────────────────────────────
_log_dir = Path(SENTINEL_LOG).parent
_log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            SENTINEL_LOG, maxBytes=5 * 1024 * 1024, backupCount=3
        ),
    ],
)

log = logging.getLogger(__name__)


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def main() -> None:
    """
    NEMO system entry point.
    Starts the MQTT telemetry listener and the print job state machine.
    Runs indefinitely until interrupted by SIGINT (Ctrl+C).
    """
    engine = StateEngine()
    start_mqtt_listener()
    engine.start()
    log.info("NEMO system online.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("NEMO shutting down.")
        engine.stop()


if __name__ == "__main__":
    main()
