import cv2
import os
import logging
from typing import Optional, Tuple
from pathlib import Path

log = logging.getLogger("sentinel.vision.capture")

class FrameCapture:
    """
    Handles the RTSPS stream capture and image preprocessing.
    """
    def __init__(self, camera_url: str, audit_dir: Path):
        self.camera_url = camera_url
        self.audit_dir = audit_dir
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "tls_verify;0"

    def get_frame(self) -> Optional[any]:
        """Captures a frame with bed-area optimization."""
        try:
            cap = cv2.VideoCapture(self.camera_url)
            if not cap.isOpened():
                return None

            best_frame = None
            best_score = -1

            # Grab 15 frames and pick the one with the most visible bed area
            for _ in range(15):
                cap.grab()
                ret, frame = cap.retrieve()
                if ret and frame is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    edges = cv2.Canny(gray, 50, 150)
                    edge_score = cv2.countNonZero(edges)
                    brightness = int(gray.mean())
                    score = edge_score + (brightness * 10)
                    if score > best_score:
                        best_score = score
                        best_frame = frame
            cap.release()

            if best_frame is not None:
                return self._preprocess(best_frame)
        except Exception as e:
            log.error(f"[CAPTURE] Error retrieving frame: {e}")
        return None

    def _preprocess(self, frame):
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
        return cv2.fastNlMeansDenoisingColored(cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR), None, 3, 3, 7, 21)

    def save_audit_image(self, frame, verdict: str, phase: str) -> Optional[Path]:
        if frame is None: return None
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        fname = self.audit_dir / f"{phase}_{verdict}_{ts}.jpg"
        try:
            cv2.imwrite(str(fname), frame)
            return fname
        except Exception: return None
