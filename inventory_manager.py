# ── STANDARD LIBRARY ──────────────────────────────────────────────────────────
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

# ── LOCAL ─────────────────────────────────────────────────────────────────────
from config import INVENTORY_FILE_PATH, INVENTORY_SCHEMA_VERSION

log = logging.getLogger("nemo.inventory")

# ── Module-level concurrency primitive ────────────────────────────────────────
_lock = threading.Lock()

# ── SEED STRUCTURE ────────────────────────────────────────────────────────────
_EMPTY_STORE: dict = {
    "schema_version": INVENTORY_SCHEMA_VERSION,
    "last_updated":   None,
    "spools":         [],
}

# ── SPOOL STATUS OPTIONS ───────────────────────────────────────────────────────
SPOOL_STATUS_OPTIONS = ["Available", "In Use", "Low", "Depleted"]


# ── PRIVATE I/O LAYER ─────────────────────────────────────────────────────────

def _load_inventory() -> dict:
    """
    Reads inventory.json from disk. Thread-safe via module lock.
    Returns an empty seeded structure on FileNotFoundError or JSONDecodeError.
    Never raises to callers.
    """
    try:
        with open(INVENTORY_FILE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "spools" not in data:
            log.warning("inventory.json has unexpected structure — resetting to seed.")
            return dict(_EMPTY_STORE)
        return data
    except FileNotFoundError:
        log.warning("inventory.json not found — seeding empty store at %s.", INVENTORY_FILE_PATH)
        _save_inventory(dict(_EMPTY_STORE))
        return dict(_EMPTY_STORE)
    except json.JSONDecodeError as exc:
        log.warning("inventory.json is malformed (%s) — returning empty store.", exc)
        return dict(_EMPTY_STORE)


def _save_inventory(data: dict) -> None:
    """
    Writes inventory to disk atomically via a temp file + os.replace().
    Logs a warning on any OSError; never raises to callers.
    """
    tmp_path = INVENTORY_FILE_PATH + ".tmp"
    try:
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        os.replace(tmp_path, INVENTORY_FILE_PATH)
    except OSError as exc:
        log.warning("Failed to persist inventory.json: %s", exc)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def get_all_spools() -> list:
    """Returns a list of all spool records."""
    with _lock:
        data = _load_inventory()
        return list(data.get("spools", []))


def get_spool_by_id(spool_id: str) -> Optional[dict]:
    """Returns the spool matching spool_id, or None if not found."""
    with _lock:
        data = _load_inventory()
        for spool in data.get("spools", []):
            if spool.get("spool_id") == spool_id:
                return dict(spool)
        return None


def add_spool(spool: dict) -> dict:
    """
    Adds a new spool record. Assigns a UUID if no spool_id is provided.
    Sets created_at to the current UTC timestamp.
    Returns the completed spool record.
    """
    with _lock:
        data = _load_inventory()
        now_iso = datetime.now(timezone.utc).isoformat()
        new_spool: dict = {
            "spool_id":      spool.get("spool_id") or str(uuid4()),
            "material":      spool.get("material", "PLA"),
            "color":         spool.get("color", "Unknown"),
            "brand":         spool.get("brand", "Unknown"),
            "remaining_g":   int(spool.get("remaining_g", 1000)),
            "total_g":       int(spool.get("total_g", 1000)),
            "status":        spool.get("status", "Available"),
            "tray_id":       spool.get("tray_id"),
            "ams_slot":      spool.get("ams_slot"),
            "serial_number": spool.get("serial_number"),
            "last_used":     spool.get("last_used"),
            "created_at":    now_iso,
        }
        data["spools"].append(new_spool)
        _save_inventory(data)
        log.info("Spool added: %s (%s %s)", new_spool["spool_id"], new_spool["material"], new_spool["color"])
        return dict(new_spool)


def update_spool(spool_id: str, updates: dict) -> Optional[dict]:
    """
    Applies updates to an existing spool record.
    Returns the updated record, or None if spool_id is not found.
    """
    with _lock:
        data = _load_inventory()
        for idx, spool in enumerate(data.get("spools", [])):
            if spool.get("spool_id") == spool_id:
                data["spools"][idx].update(updates)
                _save_inventory(data)
                log.info("Spool updated: %s — %s", spool_id, list(updates.keys()))
                return dict(data["spools"][idx])
        log.warning("update_spool: spool_id '%s' not found.", spool_id)
        return None


def delete_spool(spool_id: str) -> bool:
    """
    Removes a spool by ID. Returns True on success, False if not found.
    """
    with _lock:
        data = _load_inventory()
        original_count = len(data.get("spools", []))
        data["spools"] = [s for s in data["spools"] if s.get("spool_id") != spool_id]
        if len(data["spools"]) == original_count:
            log.warning("delete_spool: spool_id '%s' not found.", spool_id)
            return False
        _save_inventory(data)
        log.info("Spool deleted: %s", spool_id)
        return True


def mark_spool_in_use(spool_id: str) -> None:
    """Sets status to 'In Use' and records last_used timestamp."""
    update_spool(spool_id, {
        "status":    "In Use",
        "last_used": datetime.now(timezone.utc).isoformat(),
    })
    log.info("Spool %s marked In Use.", spool_id)


def mark_spool_available(spool_id: str) -> None:
    """Sets status back to 'Available'."""
    update_spool(spool_id, {"status": "Available"})
    log.info("Spool %s marked Available.", spool_id)


def sync_from_ams(ams_data: dict) -> None:
    """
    Cross-references an AMS MQTT payload with local inventory.
    Updates remaining_g and status for matched spools.
    ams_data format: {"slots": [{"ams_slot": int, "material": str, "remaining": float}, ...]}
    """
    slots = ams_data.get("slots", [])
    if not slots:
        return

    with _lock:
        data = _load_inventory()
        changed = False

        for slot in slots:
            slot_idx = slot.get("ams_slot") or slot.get("slot_index")
            remaining_pct = slot.get("remaining", None)

            if slot_idx is None or remaining_pct is None:
                continue

            for spool in data.get("spools", []):
                if spool.get("ams_slot") == slot_idx:
                    total_g = spool.get("total_g", 1000)
                    new_remaining = int((remaining_pct / 100.0) * total_g)
                    spool["remaining_g"] = new_remaining

                    if new_remaining < 50:
                        spool["status"] = "Depleted"
                    elif new_remaining < 200:
                        spool["status"] = "Low"

                    changed = True
                    log.debug(
                        "AMS sync: slot %s → spool %s remaining=%dg",
                        slot_idx, spool.get("spool_id"), new_remaining,
                    )

        if changed:
            _save_inventory(data)
