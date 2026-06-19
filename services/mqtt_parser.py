import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

log = logging.getLogger("sentinel.mqtt_parser")

@dataclass
class AMSSlot:
    slot_index: int
    material: str = "Unknown"
    color: str = "Unknown"
    remaining: float = 0.0

@dataclass
class PrinterStatus:
    gcode_state: str = "UNKNOWN"
    nozzle_temp: float = 0.0
    bed_temp: float = 0.0
    print_progress: float = 0.0
    remaining_time: int = 0
    ams_slots: List[AMSSlot] = field(default_factory=list)

class BambuMqttParser:
    """
    Parses incoming JSON payloads from Bambu Lab printers over MQTT.
    Ensures safe extraction of telemetry data to prevent dashboard crashes
    when payloads are partial or malformed.
    """

    def __init__(self):
        pass

    def parse_payload(self, payload: Dict[str, Any]) -> PrinterStatus:
        """
        Extracts printer telemetry from a raw MQTT JSON dictionary.
        """
        # Bambu payloads often nest print data under a 'print' or 'status' key
        # We check for both to ensure robustness.
        print_data = payload.get("print") or payload.get("status") or payload

        # Safe extraction of primary keys
        status = PrinterStatus(
            gcode_state=str(print_data.get("gcode_state", "UNKNOWN")),
            nozzle_temp=self._safe_float(print_data.get("nozzle_temper", 0.0)),
            bed_temp=self._safe_float(print_data.get("bed_temper", 0.0)),
            print_progress=self._safe_float(print_data.get("mc_percent", 0.0)),
            remaining_time=self._safe_int(print_data.get("mc_remaining_time", 0))
        )

        # Parse AMS Data
        # Structure: "ams": [ { "slots": [ { "material": "...", "color": "..." }, ... ] }, ... ]
        ams_data = payload.get("ams")
        if isinstance(ams_data, list):
            status.ams_slots = self._parse_ams(ams_data)

        return status

    def _parse_ams(self, ams_list: List[Dict[str, Any]]) -> List[AMSSlot]:
        """
        Processes the nested AMS array to extract materials and colors from all trays.
        """
        slots = []
        for tray_idx, tray in enumerate(ams_list):
            # Each tray has a list of slots
            tray_slots = tray.get("slots", [])
            if not isinstance(tray_slots, list):
                continue

            for slot_idx, slot in enumerate(tray_slots):
                slots.append(AMSSlot(
                    slot_index=slot_idx + 1, # 1-based indexing for UI
                    material=slot.get("material", "Unknown"),
                    color=slot.get("color", "Unknown"),
                    remaining=self._safe_float(slot.get("remaining", 0.0))
                ))
        return slots

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
