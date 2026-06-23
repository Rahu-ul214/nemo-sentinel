from fastapi import FastAPI
import uvicorn
import threading
from core.state import STATUS
from services.inventory_manager import InventoryManager

app = FastAPI(title="NEMO API Server")
inv_manager = InventoryManager()

@app.get("/api/status")
async def get_status():
    """
    Unified endpoint providing the full system state.
    Merges real-time telemetry from the state engine and local inventory data.
    """
    # Get snapshot of the system state
    system_state = STATUS.get_snapshot()

    # Load latest inventory
    inventory = inv_manager.load_inventory()

    return {
        "system": system_state,
        "inventory": inventory,
        "timestamp": STATUS.last_mqtt_time
    }

def start_api_server(port=8000):
    """Runs the FastAPI server in a background thread."""
    config = uvicorn.Config(app=app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server
