import os
from pathlib import Path
from dotenv import load_dotenv

# ── CORE PATHS ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- BAMBU CLOUD CONFIGURATION ---
BAMBU_TOKEN = os.getenv("BAMBU_TOKEN")
BAMBU_REFRESH_TOKEN = os.getenv("BAMBU_REFRESH_TOKEN")
BAMBU_ORG_ID = os.getenv("BAMBU_ORG_ID")
BAMBU_DEVICE_ID = os.getenv("BAMBU_DEVICE_ID")
BAMBU_UID = os.getenv("BAMBU_UID")
BAMBU_CLOUD_HOST = os.getenv("BAMBU_CLOUD_HOST", "eu.mqtt.bambulab.com")

# --- LOCAL PRINTER CONFIGURATION ---
PRINTER_LOCAL_IP = os.getenv("PRINTER_LOCAL_IP")
PRINTER_ACCESS_CODE = os.getenv("PRINTER_ACCESS_CODE")
USE_LOCAL_MQTT = os.getenv("USE_LOCAL_MQTT", "False").lower() == "true"
MOCK_MODE = os.getenv("MOCK_MODE", "False").lower() == "true"

# --- HARDWARE ACTUATORS (ESP32) ---
ESP32_IP = os.getenv("ESP32_IP", "10.254.244.107")
ESP32_PORT = int(os.getenv("ESP32_PORT", "80"))
SWEEP_COOLDOWN_SEC = int(os.getenv("SWEEP_COOLDOWN_SEC", "300"))
MAX_SWEEP_RETRIES = int(os.getenv("MAX_SWEEP_RETRIES", "3"))

# --- SYSTEM PATHS ---
APP_DATA_DIR = Path.home() / ".flowstate_robotics"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = APP_DATA_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

INVENTORY_FILE = PROJECT_ROOT / "inventory.json"
SENTINEL_LOG = LOG_DIR / "sentinel.log"
SENTINEL_JSON = LOG_DIR / "sentinel.json"
STATS_CSV = LOG_DIR / "failure_events.csv"
UPLOAD_DIR = APP_DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
