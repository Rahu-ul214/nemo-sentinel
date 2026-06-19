# ── STANDARD LIBRARY ──────────────────────────────────────────────────────────
import logging
import time
from typing import Optional

# ── THIRD-PARTY ───────────────────────────────────────────────────────────────
import requests

# ── LOCAL ─────────────────────────────────────────────────────────────────────
from config import (
    ESP32_ABORT_ENDPOINT,
    ESP32_PUSH_ENDPOINT,
    ESP32_SWEEP_ENDPOINT,
    ESP32_TAP_ENDPOINT,
    ESP32_TIMEOUT_S,
    PUSH_REPEAT_COUNT,
    SWEEP_VELOCITY_DEFAULT,
    TAP_REPEAT_COUNT,
    VISION_MAX_CLEARANCE_RETRIES,
)

log = logging.getLogger("nemo.actuator")


# ── PRIVATE HTTP HELPER ────────────────────────────────────────────────────────

def _post(url: str, payload: Optional[dict] = None, timeout: int = ESP32_TIMEOUT_S) -> dict:
    """
    Executes a POST request to an ESP32 endpoint.
    Returns a standardised result dict — never raises to the caller.
    """
    start = time.monotonic()
    try:
        resp = requests.post(
            url,
            json=payload or {},
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        success = resp.status_code == 200
        if not success:
            log.warning("ESP32 %s returned HTTP %d.", url, resp.status_code)
        return {
            "success":     success,
            "status_code": resp.status_code,
            "latency_ms":  round(latency_ms, 2),
            "error":       None if success else f"HTTP {resp.status_code}",
        }
    except requests.exceptions.Timeout:
        latency_ms = (time.monotonic() - start) * 1000.0
        log.error("ESP32 %s timed out after %ds.", url, timeout)
        return {
            "success":     False,
            "status_code": None,
            "latency_ms":  round(latency_ms, 2),
            "error":       "timeout",
        }
    except requests.exceptions.ConnectionError as exc:
        latency_ms = (time.monotonic() - start) * 1000.0
        log.error("ESP32 %s connection error: %s", url, exc)
        return {
            "success":     False,
            "status_code": None,
            "latency_ms":  round(latency_ms, 2),
            "error":       "connection_error",
        }
    except requests.exceptions.RequestException as exc:
        latency_ms = (time.monotonic() - start) * 1000.0
        log.error("ESP32 %s request exception: %s", url, exc)
        return {
            "success":     False,
            "status_code": None,
            "latency_ms":  round(latency_ms, 2),
            "error":       str(exc),
        }


# ── PUBLIC ACTUATOR COMMANDS ───────────────────────────────────────────────────

def trigger_sweep(velocity: int = SWEEP_VELOCITY_DEFAULT) -> dict:
    """
    Triggers the bed sweep actuator at the specified velocity (10–100).
    Returns a result dict with success, status_code, latency_ms, error.
    """
    log.info("Triggering sweep at velocity %d.", velocity)
    return _post(ESP32_SWEEP_ENDPOINT, {"velocity": velocity})


def trigger_tap(count: int = TAP_REPEAT_COUNT) -> dict:
    """
    Sends a tap command to the ESP32 the specified number of times.
    Returns the result of the last tap.
    """
    log.info("Triggering tap x%d.", count)
    result: dict = {"success": False, "status_code": None, "latency_ms": 0.0, "error": None}
    for i in range(count):
        result = _post(ESP32_TAP_ENDPOINT, {"index": i + 1, "total": count})
        if not result["success"]:
            log.warning("Tap %d/%d failed: %s", i + 1, count, result.get("error"))
            break
        if i < count - 1:
            time.sleep(0.5)
    return result


def trigger_push(count: int = PUSH_REPEAT_COUNT) -> dict:
    """
    Sends a push command to the ESP32 the specified number of times.
    Returns the result of the last push.
    """
    log.info("Triggering push x%d.", count)
    result: dict = {"success": False, "status_code": None, "latency_ms": 0.0, "error": None}
    for i in range(count):
        result = _post(ESP32_PUSH_ENDPOINT, {"index": i + 1, "total": count})
        if not result["success"]:
            log.warning("Push %d/%d failed: %s", i + 1, count, result.get("error"))
            break
        if i < count - 1:
            time.sleep(0.5)
    return result


def trigger_abort() -> dict:
    """
    Sends an abort/emergency-stop command to the ESP32.
    Returns a result dict with success, status_code, latency_ms, error.
    """
    log.warning("ABORT command sent to ESP32.")
    return _post(ESP32_ABORT_ENDPOINT, {"source": "nemo_emergency"})


def execute_clearance_sequence() -> dict:
    """
    Executes the full tap-tap → push-push → vision verify clearance sequence.

    Retries up to VISION_MAX_CLEARANCE_RETRIES times. On each attempt:
      1. trigger_tap(TAP_REPEAT_COUNT)
      2. trigger_push(PUSH_REPEAT_COUNT)
      3. vision_service.verify_bed_cleared(latest camera frame)

    If all retries are exhausted, calls trigger_abort() and returns success=False.

    Returns:
        {
            "success": bool,
            "attempts": int,
            "final_status": str   # "cleared" | "abort_triggered" | "vision_unavailable"
        }
    """
    # Import vision_service here to allow the module to load even if camera is unavailable
    try:
        import vision_service
        vision_available = True
    except ImportError:
        log.error("vision_service could not be imported — clearance will use tap/push only.")
        vision_available = False

    # Try to get a camera frame for vision verification
    def _get_base64_frame() -> str:
        if not vision_available:
            return ""
        try:
            import base64
            import cv2
            from config import USE_LOCAL_MQTT, PRINTER_LOCAL_IP, PRINTER_ACCESS_CODE

            if USE_LOCAL_MQTT and PRINTER_LOCAL_IP and PRINTER_ACCESS_CODE:
                camera_url = (
                    f"rtsps://bblp:{PRINTER_ACCESS_CODE}@{PRINTER_LOCAL_IP}:322/streaming/live/1"
                )
                cap = cv2.VideoCapture(camera_url)
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None:
                    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    if ok:
                        return base64.b64encode(buf).decode("utf-8")
            return ""
        except Exception as exc:
            log.warning("Camera frame capture failed during clearance: %s", exc)
            return ""

    for attempt in range(1, VISION_MAX_CLEARANCE_RETRIES + 1):
        log.info("Clearance sequence attempt %d/%d.", attempt, VISION_MAX_CLEARANCE_RETRIES)

        tap_result = trigger_tap(TAP_REPEAT_COUNT)
        if not tap_result["success"]:
            log.warning("Tap failed on attempt %d: %s", attempt, tap_result.get("error"))

        time.sleep(1.0)

        push_result = trigger_push(PUSH_REPEAT_COUNT)
        if not push_result["success"]:
            log.warning("Push failed on attempt %d: %s", attempt, push_result.get("error"))

        time.sleep(2.0)

        # Vision verification
        frame_b64 = _get_base64_frame()
        if not frame_b64:
            log.warning("No camera frame available for clearance verification on attempt %d.", attempt)
            if not vision_available:
                # Without vision, assume cleared after successful tap+push
                return {
                    "success":      tap_result["success"] and push_result["success"],
                    "attempts":     attempt,
                    "final_status": "vision_unavailable",
                }
            # Vision available but no frame — retry
            continue

        cleared = vision_service.verify_bed_cleared(frame_b64)
        if cleared:
            log.info("Bed cleared confirmed by vision on attempt %d.", attempt)
            return {
                "success":      True,
                "attempts":     attempt,
                "final_status": "cleared",
            }

        log.warning("Bed NOT cleared after attempt %d — retrying.", attempt)
        time.sleep(3.0)

    # All retries exhausted
    log.error("Clearance sequence failed after %d attempts — triggering ABORT.", VISION_MAX_CLEARANCE_RETRIES)
    trigger_abort()
    return {
        "success":      False,
        "attempts":     VISION_MAX_CLEARANCE_RETRIES,
        "final_status": "abort_triggered",
    }
