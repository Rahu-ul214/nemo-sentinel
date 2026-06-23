import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from core.config import INVENTORY_FILE

log = logging.getLogger("sentinel.inventory")

class InventoryManager:
    """
    Handles local persistence for the SpoolVault inventory system.
    Implements atomic writes to prevent data corruption during concurrent access.
    """

    def __init__(self):
        self._ensure_initialized()

    def _ensure_initialized(self):
        """Seeds the inventory file if it does not exist."""
        if not os.path.exists(INVENTORY_FILE):
            log.info(f"Initializing new inventory file at {INVENTORY_FILE}")
            self.save_inventory({
                "spools": [],
                "last_updated": None,
                "schema_version": 1
            })

    def load_inventory(self) -> Dict[str, Any]:
        """Reads inventory from disk with graceful error handling."""
        try:
            with open(INVENTORY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.error(f"Critical error reading inventory.json: {e}")
            return {"spools": [], "last_updated": None, "schema_version": 1}

    def save_inventory(self, data: Dict[str, Any]) -> bool:
        """
        Performs an atomic write of the inventory data.
        Writes to a temporary file first, then renames to avoid corruption.
        """
        try:
            data["last_updated"] = datetime.utcnow().isoformat()
            temp_file = f"{INVENTORY_FILE}.tmp"

            with open(temp_file, "w") as f:
                json.dump(data, f, indent=4)

            os.replace(temp_file, INVENTORY_FILE)
            return True
        except IOError as e:
            log.error(f"Atomic write failed for inventory.json: {e}")
            return False

    def update_spool(self, spool_id: str, updates: Dict[str, Any]) -> bool:
        """Updates a specific spool's data by ID."""
        data = self.load_inventory()
        spools = data.get("spools", [])

        for spool in spools:
            if spool.get("id") == spool_id:
                spools[index] = {**spool, **updates}
                data["spools"] = spools
                return self.save_inventory(data)

        log.warning(f"Spool ID {spool_id} not found in inventory.")
        return False
