import logging
import threading
import time
from typing import Optional, Any
from core.state import STATUS, SentinelState, Verdict

# Configure logger for the vision service
log = logging.getLogger("sentinel.vision")

class VisionWatchdog:
    """
    The vision orchestration layer. Responsible for analyzing print bed frames,
    managing the verification state machine, and triggering anomalies.
    """
    def __init__(self, capture_service: Any, ai_engine: Any, hardware_manager: Any):
        self.capture = capture_service
        self.ai_engine = ai_engine
        self.hardware = hardware_manager
        self._shutdown_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _on_sweep_complete(self, success: bool, message: str):
        """
        Callback invoked by the HardwareManager after a physical sweep operation.
        """
        if success:
            log.info("[VISION] Physical sweep acknowledged as complete. Verifying bed cleanliness...")
            # Trigger a special validation check
            self._verify_recovery()
        else:
            log.critical(f"[VISION] Recovery operation failed: {message}. Triggering emergency lockdown.")
            STATUS.update(state=SentinelState.EMERGENCY_LOCKDOWN)

    def _verify_recovery(self):
        """
        Performs the post-sweep cognitive check to see if the bed is truly cleared.
        """
        frame = self.capture.get_frame()
        if frame is None:
            log.error("[VISION] Post-sweep verification frame capture failed.")
            return

        # Custom prompt for recovery verification
        prompt = "Examine the 3D printer build plate. Is the bed completely empty of all plastic debris? If 100% clear, output: CLEARED. Otherwise: FAILED_SWEEP"
        verdict = self.ai_engine.query(frame, 0, 0, 0, custom_prompt=prompt)

        if verdict == Verdict.CLEARED.value:
            log.info("[VISION] Bed verified clean. Returning to IDLE.")
            STATUS.update(state=SentinelState.IDLE)
        else:
            log.warning(f"[VISION] Bed still contains debris after sweep ({verdict}).")
            STATUS.update(state=SentinelState.EMERGENCY_LOCKDOWN)

    def _analyze_cycle(self):
        """
        The core monitoring loop.
        """
        log.info("[VISION] Watchdog analysis cycle started.")

        while not self._shutdown_event.is_set():
            snapshot = STATUS.get_snapshot()
            current_state = snapshot.get("state")
            current_layer = snapshot.get("current_layer", 0)
            progress = snapshot.get("print_progress", 0)
            total_layers = snapshot.get("total_layers", 1)

            # Only monitor when actively printing
            if current_state not in (SentinelState.MONITORING, SentinelState.IDLE):
                time.sleep(5)
                continue

            frame = self.capture.get_frame()
            if frame is None:
                time.sleep(5)
                continue

            # 1. Baseline Analysis
            verdict = self.ai_engine.query(frame, progress, current_layer, total_layers)
            log.info(f"[VISION] Baseline Verdict: {verdict}")

            if verdict in (Verdict.PRINTING.value, Verdict.FINISHED.value, Verdict.CLEARED.value):
                time.sleep(30) # Pacing
                continue

            if verdict.startswith("FAILED"):
                log.warning(f"[VISION] Anomaly suspected: {verdict}. Entering STARING_OBSERVATION.")
                STATUS.update(state=SentinelState.STARING_OBSERVATION, pending_confirmation=True)

                # Phase 2: Verification Hold
                time.sleep(15)

                frame2 = self.capture.get_frame()
                if frame2 is None:
                    log.error("[VISION] Phase 2 capture failed. Forcing recovery.")
                    self._trigger_recovery()
                    continue

                verdict2 = self.ai_engine.query(frame2, progress, current_layer, total_layers)
                log.info(f"[VISION] Final Evaluative Verdict: {verdict2}")

                if verdict2 in (Verdict.PRINTING.value, Verdict.CLEARED.value, Verdict.FINISHED.value):
                    log.info("[VISION] False alarm. Resetting to monitoring.")
                    STATUS.update(state=SentinelState.MONITORING, pending_confirmation=False)
                else:
                    log.critical(f"[VISION] Failure confirmed: {verdict2}. Initiating recovery.")
                    self._trigger_recovery()

            time.sleep(30)

    def _trigger_recovery(self):
        """
        Coordinates the transition from sensing to hardware action.
        """
        # Note: We stop the printer first via the hardware manager or telemetry
        # For this framework, the HardwareManager handles the high-level sequence
        self.hardware.execute_sweep_sequence(completion_callback=self._on_sweep_complete)

    def start(self):
        self._thread = threading.Thread(target=self._analyze_cycle, daemon=True)
        self._thread.start()
        log.info("[VISION] Watchdog thread spawned.")

    def stop(self):
        self._shutdown_event.set()
        if self._thread:
            self._thread.join(timeout=5)
