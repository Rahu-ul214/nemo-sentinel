import threading
import time
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Dict
from core.config import SWEEP_COOLDOWN_SEC, MAX_SWEEP_RETRIES

class SentinelState(Enum):
    IDLE                = auto()
    MONITORING          = auto()
    STARING_OBSERVATION = auto()
    RECOVERY_SWEEPING   = auto()
    EMERGENCY_LOCKDOWN  = auto()

class SpaghettiError(Exception):
    """Custom exception for fatal print failures that require immediate lockdown."""
    def __init__(self, message: str, severity: str = "CRITICAL"):
        self.message = message
        self.severity = severity
        super().__init__(self.message)

@dataclass
class SentinelStatus:
    # Telemetry Fields
    total_estimated_time:     int = 5
    current_layer:            int = 0
    total_layers:             int = 0
    print_progress:           int = 0
    gcode_state:              str = "IDLE"
    nozzle_temp:              float = 0.0
    bed_temp:                 float = 0.0
    ams_data:                 Dict[str, Any] = field(default_factory=dict)

    # State Fields
    state:                    SentinelState = SentinelState.IDLE
    pending_confirmation:     bool = False
    awaiting_ejection:        bool = False

    # Internal Tracking
    last_check_time:          float = 0.0
    last_mqtt_time:           float = field(default_factory=time.time)
    mqtt_connected:           bool = False

    lock: threading.Lock = field(default_factory=threading.Lock)

    def update(self, **kwargs) -> None:
        with self.lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)
            self.last_mqtt_time = time.time()

    def get_snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {k: v for k, v in self.__dict__.items() if k != "lock"}

class StateEngine:
    """
    Orchestrates transitions between print states and manages hardware retry logic.
    """
    def __init__(self, hardware_manager):
        self.hw = hardware_manager
        self.last_sweep_attempt = 0.0

    def process_event(self, event_type: str, data: Any = None):
        """
        Central event handler for the state machine.
        """
        if event_type == "PRINT_FINISH":
            self._handle_print_finish()
        elif event_type == "SPAGHETTI_DETECTED":
            self._handle_fatal_failure("Spaghetti detection triggered emergency stop.")

    def _handle_print_finish(self):
        """Implements the 3-try sweep retry logic."""
        current_time = time.time()
        if (current_time - self.last_sweep_attempt) < SWEEP_COOLDOWN_SEC:
            return # Cooldown active

        log = logging.getLogger("sentinel.state")
        log.info("Event: PRINT_FINISH. Initiating recovery sequence...")

        STATUS.update(state=SentinelState.RECOVERY_SWEEPING)

        for attempt in range(1, MAX_SWEEP_RETRIES + 1):
            log.info(f"Sweep Attempt {attempt}/{MAX_SWEEP_RETRIES}...")
            success, msg = self.hw.trigger_sweep()

            if success:
                log.info("Sweep successful. System returning to IDLE.")
                STATUS.update(state=SentinelState.IDLE)
                self.last_sweep_attempt = time.time()
                return

            log.warning(f"Attempt {attempt} failed: {msg}. Retrying in 10s...")
            time.sleep(10)

        log.error("All sweep attempts exhausted. Escalating to LOCKDOWN.")
        self._handle_fatal_failure("Hardware recovery failed after maximum retries.")

    def _handle_fatal_failure(self, reason: str):
        """Triggers emergency lockdown and logs critical failure."""
        log = logging.getLogger("sentinel.state")
        log.critical(f"FATAL SYSTEM FAILURE: {reason}")
        STATUS.update(state=SentinelState.EMERGENCY_LOCKDOWN)
        raise SpaghettiError(reason)

STATUS = SentinelStatus()
