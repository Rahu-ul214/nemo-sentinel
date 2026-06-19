import requests
import logging
from core.config import ESP32_IP

log = logging.getLogger("sentinel.actuator")

def trigger_sweeper_arm():
    """
    Triggers the physical bed sweep actuator via a POST request.
    Endpoint: http://<ESP32_IP>/sweep
    """
    url = f"http://{ESP32_IP}/sweep"

    try:
        log.info(f"[ACTUATOR] Triggering sweeper arm POST request to {url}...")
        # Using a POST request as specified by the hardware requirements
        response = requests.post(url, timeout=5)

        if response.status_code == 200:
            log.info("[ACTUATOR] Sweeper arm successfully triggered.")
            return True
        else:
            log.error(f"[ACTUATOR] Sweeper arm request failed with status {response.status_code}")
            return False

    except requests.exceptions.RequestException as e:
        log.error(f"[ACTUATOR] Connection error while triggering sweeper arm: {e}")
        return False
