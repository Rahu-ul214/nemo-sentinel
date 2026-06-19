import requests
import base64
import cv2
import logging
from typing import Optional
from core.state import Verdict

log = logging.getLogger("sentinel.vision.ai")

class AIEngine:
    """
    Interface for the NVIDIA Llama-3.2-Vision API.
    """
    def __init__(self, api_key: str, api_url: str, model: str):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model

    def _generate_system_prompt(self) -> str:
        return (
            "You are the master safety monitoring AI for an industrial 3D print farm.\n"
            "Analyze the print bed image with EXTREME scrutiny. The bed plate and filament can be ANY color.\n\n"
            "MANDATORY ANOMALY CHECKLIST:\n"
            "1. SPAGHETTI / BIRD'S NEST: Thin, tangled, stringy filament strands. If present -> FAILED_SWEEP.\n"
            "2. DETACHED OBJECT: Solid piece NOT firmly attached. If tilted or shifted -> FAILED_SWEEP.\n"
            "3. NOZZLE BLOB: Large, irregular lump on toolhead. If present -> FAILED_FATAL.\n"
            "4. MISSING PRINT: Bed should have object but doesn't -> FAILED_SWEEP.\n\n"
            "Conclude with EXACTLY one of these keywords on its own separate final line:\n"
            "- PRINTING\n- FAILED_FATAL\n- FAILED_SWEEP\n- FINISHED\n- CLEARED"
        )

    def query(self, frame, progress: int, layer: int, total: int, custom_prompt: Optional[str] = None) -> str:
        try:
            ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok: return Verdict.PRINTING.value
            img_b64 = base64.b64encode(buf).decode()

            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            prompt_text = custom_prompt if custom_prompt else f"Progress: {progress}%, Layer {layer}/{total}. {self._generate_system_prompt()}"

            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}],
                "max_tokens": 400,
                "temperature": 0.1
            }

            r = requests.post(self.api_url, headers=headers, json=payload, timeout=40)
            if r.status_code == 200:
                raw = r.json()["choices"][0]["message"]["content"].strip().upper()
                for line in reversed(raw.split('\n')):
                    for v in Verdict:
                        if v.value in line: return v.value
                return Verdict.PRINTING.value
            return Verdict.API_OFFLINE.value
        except Exception as e:
            log.error(f"[AI] API Request failed: {e}")
            return Verdict.PRINTING.value
