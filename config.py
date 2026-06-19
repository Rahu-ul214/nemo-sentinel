# ── STANDARD LIBRARY ──────────────────────────────────────────────────────────
import os
from pathlib import Path

# ── THIRD-PARTY ───────────────────────────────────────────────────────────────
from dotenv import load_dotenv

# ── LOAD ENV ──────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")

# ── Hardware ───────────────────────────────────────────────────────────────────
ESP32_HOST = os.getenv("ESP32_IP", "10.254.244.107")
ESP32_SWEEP_ENDPOINT = f"http://{ESP32_HOST}/sweep"
ESP32_TAP_ENDPOINT   = f"http://{ESP32_HOST}/tap"
ESP32_PUSH_ENDPOINT  = f"http://{ESP32_HOST}/push"
ESP32_ABORT_ENDPOINT = f"http://{ESP32_HOST}/abort"
ESP32_TIMEOUT_S      = 4

# ── MQTT / Bambu Cloud ─────────────────────────────────────────────────────────
MQTT_HOST           = os.getenv("BAMBU_CLOUD_HOST", "eu.mqtt.bambulab.com")
MQTT_PORT           = 8883
MQTT_USERNAME       = "bblp"
MQTT_ACCESS_TOKEN   = os.getenv("BAMBU_TOKEN")
PRINTER_SERIAL      = os.getenv("BAMBU_DEVICE_ID")
MQTT_TOPIC_REPORT   = f"device/{PRINTER_SERIAL}/report" if PRINTER_SERIAL else "device/unknown/report"

# ── Connection Mode ─────────────────────────────────────────────────────────────
USE_LOCAL_MQTT        = os.getenv("USE_LOCAL_MQTT", "False").lower() == "true"
PRINTER_LOCAL_IP      = os.getenv("PRINTER_LOCAL_IP")
PRINTER_ACCESS_CODE   = os.getenv("PRINTER_ACCESS_CODE")
MOCK_MODE             = os.getenv("MOCK_MODE", "False").lower() == "true"

# ── Vision / NVIDIA ────────────────────────────────────────────────────────────
NVIDIA_API_KEY       = os.getenv("NVIDIA_API_KEY")
NVIDIA_BASE_URL      = "https://integrate.api.nvidia.com/v1"
NVIDIA_VISION_MODEL  = "meta/llama-3.2-90b-vision-instruct"
VISION_WATCHDOG_INTERVAL_S   = 20
VISION_MAX_CLEARANCE_RETRIES = 3

# ── Thermal Thresholds ─────────────────────────────────────────────────────────
BED_SAFE_TEMP_MIN_C = 22.0
BED_SAFE_TEMP_MAX_C = 25.0

# ── Inventory ──────────────────────────────────────────────────────────────────
INVENTORY_FILE_PATH    = str(_PROJECT_ROOT / "inventory.json")
INVENTORY_SCHEMA_VERSION = 1

# ── Sweep Sequence ─────────────────────────────────────────────────────────────
TAP_REPEAT_COUNT       = 2
PUSH_REPEAT_COUNT      = 2
SWEEP_VELOCITY_DEFAULT = 50

# ── Logging ────────────────────────────────────────────────────────────────────
_LOG_DIR  = Path.home() / ".flowstate_robotics" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
SENTINEL_LOG = _LOG_DIR / "sentinel.log"

# ── Device info (for dashboard display) ────────────────────────────────────────
BAMBU_DEVICE_ID = PRINTER_SERIAL
