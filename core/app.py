from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn
import logging
import os
import platform
import subprocess
import shutil
import ctypes
from pathlib import Path
from typing import List

# --- Core Framework Imports ---
from core.state import STATUS
from services.hardware import ESP32Manager
from core.config import APP_DATA_DIR, ESP32_IP, SENTINEL_LOG, UPLOAD_DIR

# Configure Rotating Logger
from logging.handlers import RotatingFileHandler
logger = logging.getLogger("sentinel.web")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(SENTINEL_LOG, maxBytes=5*1024*1024, backupCount=5)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
log = logger

app = FastAPI(title="NodeForge Sentinel Dashboard")

# ==============================================================================
# CONFIGURATION
# ==============================================================================
import sys

if hasattr(sys, '_MEIPASS'):
    # Running inside PyInstaller bundle temp directory
    base_path = Path(sys._MEIPASS)
else:
    # Running inside normal development environment
    base_path = Path(__file__).resolve().parent.parent

DASHBOARD_HTML = base_path / "Print Farm (2)(1).html"
# We use the standardized paths from core.config
LOG_FILE_PATH = SENTINEL_LOG

# Singleton instance of Hardware Manager for the web process
hw_manager = ESP32Manager(ESP32_IP)

# ==============================================================================
# OS PERMISSION HELPERS
# ==============================================================================

def request_admin_privileges(command_array: List[str]):
    """
    Re-executes a command with administrative privileges using native OS prompts.
    """
    cmd_string = " ".join(command_array)
    system = platform.system()

    log.info(f"[SYSTEM] Attempting privilege escalation for: {cmd_string}")

    if system == "Windows":
        try:
            # ShellExecuteW with 'runas' triggers the UAC prompt
            # Params: (hwnd, operation, file, params, directory, showCmd)
            ctypes.windll.shell32.ShellExecuteW(None, "runas", command_array[0], " ".join(command_array[1:]), None, 1)
            return True
        except Exception as e:
            log.error(f"Windows UAC prompt failed: {e}")
            return False

    elif system == "Darwin":  # macOS
        try:
            # Wraps command in osascript to trigger the 'do shell script ... with administrator privileges' prompt
            script = f'do shell script "{cmd_string}" with administrator privileges'
            subprocess.run(["osascript", "-e", script], check=True)
            return True
        except subprocess.CalledProcessError as e:
            log.error(f"macOS Admin prompt failed or was cancelled: {e}")
            return False
    else:
        log.error(f"Unsupported OS for privilege escalation: {system}")
        return False

# ==============================================================================
# ENDPOINTS
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
async def read_dashboard():
    """
    Serves the custom Print Farm orchestration interface.
    """
    try:
        if not DASHBOARD_HTML.exists():
             return f"<h1>Dashboard HTML Not Found</h1><p>Please place 'Print Farm (2)(1).html' in: {DASHBOARD_HTML.absolute()}</p>"

        with open(DASHBOARD_HTML, "r") as f:
            return f.read()
    except Exception as e:
        log.error(f"Unexpected error serving dashboard: {e}")
        return f"<h1>Server Error</h1><p>{str(e)}</p>"

@app.get("/status")
async def get_status():
    """
    Returns a live snapshot of the system state.
    """
    return STATUS.get_snapshot()

@app.post("/sweep")
async def trigger_sweep(background_tasks: BackgroundTasks):
    """
    Triggers the physical bed sweep actuator.
    """
    log.info("[WEB] Manual sweep request received.")

    def run_sweep():
        hw_manager.execute_sweep_sequence()

    background_tasks.add_task(run_sweep)
    return {"status": "Sweep sequence initiated", "state": "RECOVERY_SWEEPING"}

@app.get("/logs")
async def get_logs():
    """
    Reads and streams the most recent entries from the system log.
    """
    if not LOG_FILE_PATH.exists():
        return {"error": "Log file not yet created."}

    try:
        with open(LOG_FILE_PATH, "r") as f:
            lines = f.readlines()
            recent_logs = "".join(lines[-100:])
            return {"logs": recent_logs}
    except Exception as e:
        log.error(f"Error reading log file: {e}")
        return {"error": str(e)}

@app.get("/api/logs")
async def api_get_logs():
    """
    Returns the last 20 lines of the sentinel log as a JSON list for the monitor.
    """
    if not LOG_FILE_PATH.exists():
        return []

    try:
        with open(LOG_FILE_PATH, "r") as f:
            lines = f.readlines()
            return [line.strip() for line in lines[-20:]]
    except Exception as e:
        log.error(f"Error reading log file for API: {e}")
        return [f"Error reading logs: {str(e)}"]

@app.post("/upload-and-slice")
async def handle_upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), loops: int = 4):
    """
    Handles the 3D model dropzone upload and triggers the background slicing pipeline.
    """
    file_path = UPLOAD_DIR / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    log.info(f"[UPLOAD] File saved to {file_path}. Initiating slicing pipeline...")

    def slicing_pipeline():
        try:
            # 1. Define the slicing command (Example using a hypothetical Bambu Studio CLI)
            # This is where the core slicing, macro injection, and cloud deployment occurs.
            slicing_cmd = ["bambu-studio-cli", "--file", str(file_path), "--loops", str(loops), "--inject-sweep-macro"]

            log.info(f"[SLICE] Executing: {' '.join(slicing_cmd)}")

            # Attempt to execute the slicing command
            try:
                subprocess.run(slicing_cmd, check=True)
            except subprocess.CalledProcessError as e:
                log.error(f"[SLICE] Slicing failed for file {file.filename}. Return code: {e.returncode}. Command: {' '.join(slicing_cmd)}")
                return

            log.info("[SLICE] Slicing complete. Deploying to cloud...")
            # Add cloud deployment logic here

        except PermissionError:
            log.warning("[SYSTEM] Permission block detected. Launching native OS credential prompt.")
            # Trigger the native OS privilege escalation
            if request_admin_privileges(slicing_cmd):
                log.info("[SYSTEM] Privilege escalation successful. Resuming slicing pipeline.")
                try:
                    subprocess.run(slicing_cmd, check=True)
                except subprocess.CalledProcessError as e:
                    log.error(f"[SLICE] Slicing failed after escalation for file {file.filename}. Return code: {e.returncode}. Command: {' '.join(slicing_cmd)}")
            else:
                log.error("[SYSTEM] User denied administrative privileges. Slicing failed.")

        except Exception as e:
            log.error(f"[SLICE] Unexpected error in pipeline: {e}")

    background_tasks.add_task(slicing_pipeline)
    return {"status": "File uploaded. Slicing pipeline initiated in background.", "file": file.filename}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
