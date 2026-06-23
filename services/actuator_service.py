import requests
import logging
from typing import Tuple
from core.config import ESP32_IP, ESP32_PORT

log = logging.getLogger("sentinel.actuator")

class ActuatorService:
    """
    Hardened interface for physical hardware triggers via ESP32 HTTP endpoints.
    """
    def __init__(self):
        self.base_url = f"http://{ESP32_IP}:{ESP32_PORT}"

    def trigger_sweeper_arm(self) -> Tuple[bool, str]:
        """
        Sends a hardened POST request to the sweep actuator.
        Returns (success_boolean, status_message).
        """
        endpoint = f"{self.base_url}/sweep"

        try:
            log.info(f"[ACTUATOR] Dispatching POST request to sweeper arm: {endpoint}")

            # Using a timeout to prevent the main loop from hanging if ESP32 crashes
            response = requests.post(
                endpoint,
                timeout=5,
                headers={"Content-Type": "application/json"},
                json={"command": "trigger_sweep", "timestamp": "system_clock"}
            )

            if response.status_code == 200:
                log.info("[ACTUATOR] Sweeper arm acknowledged command successfully.")
                return True, "success"

            log.error(f"[ACTUATOR] Hardware returned non-200 response: {response.status_code}")
            return False, f"http_error_{response.status_code}"

        except requests.exceptions.ConnectTimeout:
            log.error("[ACTUATOR] Connection timeout: ESP32 is unreachable.")
            return False, "timeout"
        except requests.exceptions.ConnectionError:
            log.error("[ACTUATOR] Connection refused: ESP32 network interface is down.")
            return False, "connection_refused"
        except Exception as e:
            log.error(f"[ACTUATOR] Unexpected failure in hardware bridge: {e}")
            return False, "internal_exception"
