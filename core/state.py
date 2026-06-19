import threading
import time
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Dict

class SentinelState(Enum):
    IDLE                = auto()
    MONITORING          = auto()
    STARING_OBSERVATION = auto()
    RECOVERY_SWEEPING   = auto()
    EMERGENCY_LOCKDOWN  = auto()

class Verdict(Enum):
    PRINTING     = "PRINTING"
    FINISHED     = "FINISHED"
    CLEARED      = "CLEARED"
    FAILED_FATAL = "FAILED_FATAL"
    FAILED_SWEEP = "FAILED_SWEEP"
    API_OFFLINE  = "API_OFFLINE"

@dataclass
class SentinelStatus:
    # Telemetry Fields
    total_estimated_time:     int = 5
    current_layer:            int = 0
    total_layers:             int = 0
    print_progress:           int = 0
    gcode_state:              str = "IDLE"

    # Vision/State Fields
    state:                    SentinelState = SentinelState.IDLE
    pending_confirmation:     bool = False

    # Internal Tracking
    last_check_time:          float = 0.0
    last_mqtt_time:           float = field(default_factory=time.time)

    # Other Status
    mqtt_connected:           bool = False
    retry_count:              int = 0
    motion_skip_counter:      int = 0
    consecutive_api_failures: int = 0
    fingerprint_frame:        Optional[Any] = None
    fingerprint_layer:        int = 0
    fingerprint_saved:        bool = False
    awaiting_ejection:        bool = False
    run_number:               int = 0
    first_layer_checked:      bool = False

    # Concurrency Primitive
    lock: threading.Lock = field(default_factory=threading.Lock)

    # Internal mapping for automatic timestamp updates
    _TELEMETRY_FIELDS = {
        "total_estimated_time", "current_layer", "total_layers",
        "print_progress", "gcode_state"
    }
    _VISION_FIELDS = {
        "state", "pending_confirmation"
    }

    def update(self, **kwargs) -> None:
        """
        Thread-safe update of status attributes.
        Automatically refreshes timestamps if telemetry or vision data changes.
        """
        with self.lock:
            telemetry_changed = False
            vision_changed = False

            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)
                    if key in self._TELEMETRY_FIELDS:
                        telemetry_changed = True
                    if key in self._VISION_FIELDS:
                        vision_changed = True
                else:
                    # We ignore attributes that don't exist to prevent runtime crashes
                    # during partial telemetry updates
                    pass

            if telemetry_changed:
                self.last_mqtt_time = time.time()
            if vision_changed:
                self.last_check_time = time.time()

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Returns a thread-safe dictionary copy of the current state.
        Prevents partial-reads during concurrent MQTT/Vision updates.
        """
        with self.lock:
            # Manually construct dict to avoid asdict crashing on non-serializable lock object
            return {
                "state": self.state,
                "total_estimated_time": self.total_estimated_time,
                "current_layer": self.current_layer,
                "total_layers": self.total_layers,
                "print_progress": self.print_progress,
                "gcode_state": self.gcode_state,
                "pending_confirmation": self.pending_confirmation,
                "last_check_time": self.last_check_time,
                "last_mqtt_time": self.last_mqtt_time,
                "mqtt_connected": self.mqtt_connected,
                "retry_count": self.retry_count,
                "motion_skip_counter": self.motion_skip_counter,
                "consecutive_api_failures": self.consecutive_api_failures,
                "fingerprint_layer": self.fingerprint_layer,
                "fingerprint_saved": self.fingerprint_saved,
                "awaiting_ejection": self.awaiting_ejection,
                "run_number": self.run_number,
                "first_layer_checked": self.first_layer_checked,
            }


# Global state instance to be imported across the framework
STATUS = SentinelStatus()

_BLOCKED_HARDWARE_STATES = {
    SentinelState.EMERGENCY_LOCKDOWN,
    SentinelState.RECOVERY_SWEEPING,
    SentinelState.STARING_OBSERVATION,
}


def is_hardware_blocked() -> bool:
    snapshot = STATUS.get_snapshot()
    if snapshot["state"] in _BLOCKED_HARDWARE_STATES:
        return True
    if snapshot.get("pending_confirmation"):
        return True
    if snapshot.get("awaiting_ejection"):
        return True
    return False
