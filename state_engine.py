# ── STANDARD LIBRARY ──────────────────────────────────────────────────────────
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

# ── LOCAL ─────────────────────────────────────────────────────────────────────
import actuator_service
import inventory_manager
import mqtt_client
from config import (
    BED_SAFE_TEMP_MAX_C,
    BED_SAFE_TEMP_MIN_C,
    VISION_MAX_CLEARANCE_RETRIES,
    VISION_WATCHDOG_INTERVAL_S,
)

log = logging.getLogger("nemo.state_engine")


# ── PRINT STATE ENUM ──────────────────────────────────────────────────────────

class PrintState(Enum):
    IDLE      = "idle"
    PREPARING = "preparing"
    PRINTING  = "printing"
    COOLING   = "cooling"
    CLEARING  = "clearing"
    ERROR     = "error"
    HALTED    = "halted"


# ── PRINT JOB DATACLASS ───────────────────────────────────────────────────────

@dataclass
class PrintJob:
    job_id:             str   = field(default_factory=lambda: str(uuid4()))
    file_name:          str   = "unknown"
    material:           str   = "PLA"
    start_time:         float = field(default_factory=time.time)
    cycle_count:        int   = 1
    cycles_completed:   int   = 0
    spool_id:           Optional[str] = None


# ── TRANSITION LOG ENTRY ──────────────────────────────────────────────────────

@dataclass
class TransitionEvent:
    timestamp:  str
    old_state:  str
    new_state:  str
    reason:     str


# ── STATE ENGINE ──────────────────────────────────────────────────────────────

class StateEngine:
    """
    Full-lifecycle print job state machine.
    Transitions: IDLE → PREPARING → PRINTING → COOLING → CLEARING → IDLE
    Error paths:  any → ERROR | HALTED
    """

    _POLL_INTERVAL_S        = 5
    _WATCHDOG_INTERVAL_S    = VISION_WATCHDOG_INTERVAL_S
    _MAX_TRANSITION_LOG     = 200

    def __init__(self) -> None:
        self._state       = PrintState.IDLE
        self._job:        Optional[PrintJob] = None
        self._lock        = threading.Lock()
        self._stop_event  = threading.Event()
        self._thread:     Optional[threading.Thread] = None
        self._transitions: list[TransitionEvent] = []
        self._last_watchdog_time = 0.0

        log.info("StateEngine initialised — state: %s", self._state.value)

    # ── STATE ACCESS ──────────────────────────────────────────────────────────

    @property
    def state(self) -> PrintState:
        with self._lock:
            return self._state

    @property
    def job(self) -> Optional[PrintJob]:
        with self._lock:
            return self._job

    # ── TRANSITION ────────────────────────────────────────────────────────────

    def transition(self, new_state: PrintState, reason: str) -> None:
        """
        Atomically transitions to a new state and records the event.
        Logs timestamp, old state, new state, and reason.
        """
        with self._lock:
            old_state = self._state
            self._state = new_state
            event = TransitionEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                old_state=old_state.value,
                new_state=new_state.value,
                reason=reason,
            )
            self._transitions.append(event)
            if len(self._transitions) > self._MAX_TRANSITION_LOG:
                self._transitions.pop(0)

        log.info(
            "STATE TRANSITION: %s → %s | reason: %s",
            old_state.value, new_state.value, reason,
        )

    # ── PUBLIC STATUS DICT ────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """
        Returns a dashboard-consumable dict of current engine state.
        Thread-safe deep copy — never exposes internal mutable objects.
        """
        with self._lock:
            job_info = None
            if self._job:
                job_info = {
                    "job_id":           self._job.job_id,
                    "file_name":        self._job.file_name,
                    "material":         self._job.material,
                    "start_time":       self._job.start_time,
                    "cycle_count":      self._job.cycle_count,
                    "cycles_completed": self._job.cycles_completed,
                    "spool_id":         self._job.spool_id,
                }
            return {
                "state":       self._state.value,
                "job":         job_info,
                "transitions": [
                    {
                        "timestamp": t.timestamp,
                        "old_state": t.old_state,
                        "new_state": t.new_state,
                        "reason":    t.reason,
                    }
                    for t in self._transitions[-50:]
                ],
            }

    # ── JOB LIFECYCLE METHODS ─────────────────────────────────────────────────

    def start_job(
        self,
        file_name: str = "unknown",
        material: str = "PLA",
        cycle_count: int = 1,
        spool_id: Optional[str] = None,
    ) -> str:
        """
        Registers a new print job and transitions from IDLE → PREPARING.
        Returns the job_id.
        """
        with self._lock:
            if self._state != PrintState.IDLE:
                raise RuntimeError(
                    f"Cannot start job while in state {self._state.value}. "
                    "Engine must be IDLE."
                )
            self._job = PrintJob(
                file_name=file_name,
                material=material,
                cycle_count=cycle_count,
                spool_id=spool_id,
            )
            job_id = self._job.job_id

        self.transition(PrintState.PREPARING, f"New job queued: {file_name}")
        if spool_id:
            inventory_manager.mark_spool_in_use(spool_id)
        log.info("Job started: %s (file=%s, cycles=%d)", job_id, file_name, cycle_count)
        return job_id

    # ── WATCHDOG ──────────────────────────────────────────────────────────────

    def _run_vision_watchdog(self, telemetry: dict) -> None:
        """
        Periodically calls vision_service.check_print_health() during PRINTING.
        If action_recommended == 'abort', transitions to ERROR.
        Skips if camera/vision is unavailable.
        """
        now = time.monotonic()
        if now - self._last_watchdog_time < self._WATCHDOG_INTERVAL_S:
            return
        self._last_watchdog_time = now

        try:
            import base64
            import cv2
            import vision_service
            from config import PRINTER_LOCAL_IP, PRINTER_ACCESS_CODE, USE_LOCAL_MQTT

            if not (USE_LOCAL_MQTT and PRINTER_LOCAL_IP and PRINTER_ACCESS_CODE):
                return

            camera_url = (
                f"rtsps://bblp:{PRINTER_ACCESS_CODE}@{PRINTER_LOCAL_IP}:322/streaming/live/1"
            )
            cap = cv2.VideoCapture(camera_url)
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                return

            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return
            frame_b64 = base64.b64encode(buf).decode("utf-8")

            health = vision_service.check_print_health(frame_b64)
            log.debug(
                "Watchdog health check: healthy=%s, issue=%s, action=%s",
                health.get("healthy"), health.get("issue_detected"), health.get("action_recommended"),
            )

            if health.get("action_recommended") == "abort":
                self.transition(
                    PrintState.ERROR,
                    f"Vision watchdog triggered abort: {health.get('issue_detected')}",
                )

        except ImportError:
            pass  # Vision or CV2 not available — skip watchdog silently
        except Exception as exc:
            log.warning("Vision watchdog error (non-fatal): %s", exc)

    # ── MAIN CYCLE ────────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        """
        Main orchestration loop. Called repeatedly by the background thread.
        Implements the full IDLE → PREPARING → PRINTING → COOLING → CLEARING → IDLE lifecycle.
        """
        current_state = self.state

        match current_state:

            case PrintState.IDLE:
                # Nothing to do — waiting for start_job() call
                pass

            case PrintState.PREPARING:
                # Transition to PRINTING once we see the printer is active
                telemetry = mqtt_client.get_telemetry()
                gcode = telemetry.get("gcode_state", "UNKNOWN")
                if gcode in ("PRINTING", "PREPARE"):
                    self.transition(PrintState.PRINTING, f"Printer gcode_state={gcode}")
                elif gcode in ("FINISH", "IDLE"):
                    # Printer already finished (or was idle) — jump straight to COOLING
                    self.transition(PrintState.COOLING, "Printer was already idle/finished during PREPARING")

            case PrintState.PRINTING:
                telemetry = mqtt_client.get_telemetry()
                pct = float(telemetry.get("print_percentage", 0))
                gcode = telemetry.get("gcode_state", "UNKNOWN")

                # Vision watchdog
                self._run_vision_watchdog(telemetry)

                # Check completion
                if pct >= 100.0 or gcode == "FINISH":
                    self.transition(PrintState.COOLING, f"Print complete (progress={pct:.1f}%, gcode={gcode})")

            case PrintState.COOLING:
                telemetry = mqtt_client.get_telemetry()
                bed_temp = float(telemetry.get("bed_temp", 999.0))

                if BED_SAFE_TEMP_MIN_C <= bed_temp <= BED_SAFE_TEMP_MAX_C:
                    log.info("Bed temp %.1f°C is within safe range — proceeding to clearance.", bed_temp)
                    self.transition(PrintState.CLEARING, f"Bed temp OK ({bed_temp:.1f}°C)")
                else:
                    log.debug("Cooling: bed_temp=%.1f°C (target %.1f–%.1f°C)", bed_temp, BED_SAFE_TEMP_MIN_C, BED_SAFE_TEMP_MAX_C)

            case PrintState.CLEARING:
                result = actuator_service.execute_clearance_sequence()

                if result["success"]:
                    spool_id = None
                    with self._lock:
                        if self._job:
                            spool_id = self._job.spool_id
                            self._job.cycles_completed += 1
                            cycles_done = self._job.cycles_completed
                            cycle_total = self._job.cycle_count
                    if spool_id:
                        inventory_manager.mark_spool_available(spool_id)

                    if cycles_done < cycle_total:
                        self.transition(PrintState.PREPARING, f"Cycle {cycles_done}/{cycle_total} complete — queuing next cycle")
                    else:
                        self.transition(PrintState.IDLE, f"All {cycle_total} cycles complete")
                        with self._lock:
                            self._job = None
                else:
                    self.transition(
                        PrintState.HALTED,
                        f"Clearance failed after {result['attempts']} attempts — status: {result['final_status']}",
                    )

            case PrintState.ERROR:
                log.error("Engine is in ERROR state. Manual intervention required.")
                # Engine stays in ERROR until manually reset

            case PrintState.HALTED:
                log.error("Engine is HALTED. Manual intervention required.")
                # Engine stays HALTED until manually reset

    # ── BACKGROUND THREAD ─────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Background daemon thread body."""
        log.info("StateEngine background loop started.")
        while not self._stop_event.is_set():
            try:
                self.run_cycle()
            except Exception as exc:
                log.error("Unhandled exception in run_cycle(): %s", exc)
            time.sleep(self._POLL_INTERVAL_S)
        log.info("StateEngine background loop stopped.")

    def start(self) -> None:
        """
        Starts the background orchestration thread.
        Safe to call once — subsequent calls are no-ops.
        """
        if self._thread and self._thread.is_alive():
            log.debug("StateEngine.start() called but thread already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="nemo-state-engine",
            daemon=True,
        )
        self._thread.start()
        log.info("StateEngine started.")

    def stop(self) -> None:
        """Signals the background thread to stop gracefully."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        log.info("StateEngine stopped.")

    def reset(self) -> None:
        """
        Resets engine from ERROR or HALTED back to IDLE.
        Clears the active job.
        """
        with self._lock:
            self._job = None
        self.transition(PrintState.IDLE, "Manual reset")
        log.info("StateEngine reset to IDLE.")
