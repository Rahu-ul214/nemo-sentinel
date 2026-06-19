import requests
import logging
import threading
import time
from typing import Tuple
from core.state import STATUS, SentinelState

# Configure logger for the hardware service
log = logging.getLogger("sentinel.hardware")

class CircuitBreaker:
    """
    Prevents the system from hammering a failing ESP32 node,
    allowing it time to reboot or recover.
    """
    def __init__(self, failure_threshold=3, recovery_timeout=30):
        self.failures = 0
        self.threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure = 0.0
        self.lock = threading.Lock()

    def can_attempt(self) -> bool:
        with self.lock:
            if self.failures >= self.threshold:
                if time.time() - self.last_failure > self.recovery_timeout:
                    self.failures = 0
                    return True
                return False
            return True

    def record_failure(self):
        with self.lock:
            self.failures += 1
            self.last_failure = time.time()

class ESP32Manager:
    """
    Handles physical actuators via the ESP32 HTTP interface.
    Isolates hardware communication from the core telemetry and vision logic.
    """
    def __init__(self, esp32_ip: str):
        self.esp32_ip = esp32_ip
        self.breaker = CircuitBreaker()

    def _send_command(self, endpoint: str, timeout: int = 25) -> Tuple[bool, str]:
        """
        Low-level HTTP request handler with circuit breaker integration.
        """
        if not self.esp32_ip or not self.breaker.can_attempt():
            return False, "circuit_breaker_isolated"

        try:
            # Use the full URL constructed from the IP
            url = f"{self.esp32_ip}/{endpoint}"
            r = requests.get(url, timeout=timeout)

            if r.status_code != 200:
                self.breaker.record_failure()
                return False, f"http_err_{r.status_code}"

            try:
                telemetry = r.json()
                if telemetry.get("status") == "success":
                    return True, "execution_success"
                return False, telemetry.get("error", "unspecified_hardware_fault")
            except ValueError:
                # Case for open-loop responses that aren't JSON but return 200
                return True, "open_loop_ack"

        except Exception as e:
            self.breaker.record_failure()
            log.error(f"[HW COMMUNICATION FAILURE] End-node endpoint error '{endpoint}': {e}")
            return False, "socket_timeout_or_crash"

    def open_door(self) -> Tuple[bool, str]:
        """Triggers the physical door opening actuator."""
        return self._send_command("open")

    def close_door(self) -> Tuple[bool, str]:
        """Triggers the physical door closing actuator."""
        return self._send_command("close")

    def trigger_sweep(self) -> Tuple[bool, str]:
        """Triggers the bed ejection/sweep mechanism."""
        log.info("[HARDWARE] Sending sweep command to ESP32 at %s", self.esp32_ip)
        return self._send_command("sweep")

    def execute_sweep_sequence(self, completion_callback=None):
        """
        Runs the physical sweep sequence in a background thread to avoid
        blocking the main application loop.
        """
        def _sequence():
            log.info("[HARDWARE] Initiating physical sweep sequence...")
            # Transition state to recovery
            STATUS.update(state=SentinelState.RECOVERY_SWEEPING)

            success, message = self.trigger_sweep()

            if not success:
                log.error(f"[HARDWARE] Sweep trigger failed: {message}")
                # Note: We leave the state as RECOVERY_SWEEPING or let the
                # coordination layer handle the failure.
                if completion_callback:
                    completion_callback(False, message)
                return

            log.info("[HARDWARE] Sweep actuator engaged. Monitoring physical movement...")

            # The physical sweep takes time. We sleep here because we are in a
            # dedicated background thread.
            time.sleep(22)

            log.info("[HARDWARE] Sweep movement duration elapsed.")
            if completion_callback:
                completion_callback(True, "sweep_completed")

        # Spawn the physical operation in its own thread
        threading.Thread(target=_sequence, daemon=True).start()
