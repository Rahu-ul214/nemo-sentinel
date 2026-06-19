# ── STANDARD LIBRARY ──────────────────────────────────────────────────────────
import json
import logging
import re
from typing import Optional

# ── LOCAL ─────────────────────────────────────────────────────────────────────
from config import NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_VISION_MODEL

log = logging.getLogger("nemo.vision")

# ── OPENAI CLIENT (pointed at NVIDIA endpoint) ─────────────────────────────────
def _get_client():
    """
    Returns an OpenAI client configured for the NVIDIA API.
    Lazy-initialised to avoid import-time failure if openai is not installed.
    """
    try:
        from openai import OpenAI
        return OpenAI(
            api_key=NVIDIA_API_KEY or "no-key-configured",
            base_url=NVIDIA_BASE_URL,
        )
    except ImportError as exc:
        log.error("openai package not installed: %s", exc)
        return None


# ── SHARED HELPERS ─────────────────────────────────────────────────────────────

def _strip_markdown_fences(text: str) -> str:
    """Removes ```json ... ``` fences that the model sometimes wraps around JSON."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "").strip()
    return cleaned


def _call_vision_model(base64_image: str, prompt: str, max_tokens: int = 512) -> Optional[str]:
    """
    Sends a base64-encoded image + prompt to the NVIDIA vision model.
    Returns the raw response text, or None on any failure.
    """
    client = _get_client()
    if client is None:
        log.error("Vision model unavailable — OpenAI client could not be created.")
        return None

    try:
        response = client.chat.completions.create(
            model=NVIDIA_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text",      "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                    ],
                }
            ],
            max_tokens=max_tokens,
            temperature=0.1,
        )
        raw = response.choices[0].message.content
        return raw.strip() if raw else None
    except Exception as exc:
        log.error("NVIDIA vision API call failed: %s", exc)
        return None


# ── 4A: LABEL SCANNER ─────────────────────────────────────────────────────────

_LABEL_SCANNER_PROMPT = (
    "You are an inventory scanner for an industrial 3D printing facility. "
    "Analyze this image of a filament spool or its label. "
    "Extract the following fields and return ONLY a valid JSON object with no markdown, no explanation: "
    "material (string), color (string), brand (string), remaining_g (integer or null), "
    "total_g (integer or null), serial_number (string or null). "
    "If a field is not visible, set it to null."
)


def capture_for_ai(base64_image: str) -> dict:
    """
    Sends a base64-encoded image to the NVIDIA vision API.
    Returns a structured dict of extracted spool data.
    Returns an empty dict on any failure — never raises to the caller.
    """
    if not base64_image:
        log.warning("capture_for_ai called with empty image data.")
        return {}

    raw = _call_vision_model(base64_image, _LABEL_SCANNER_PROMPT, max_tokens=256)
    if raw is None:
        return {}

    try:
        cleaned = _strip_markdown_fences(raw)
        result = json.loads(cleaned)
        if not isinstance(result, dict):
            log.warning("Vision label scan returned non-dict JSON: %r", result)
            return {}
        log.info("Label scan extracted: %s", result)
        return result
    except json.JSONDecodeError:
        log.warning("Label scan JSON decode failed. Raw response: %r", raw)
        return {}


# ── 4B: PRINT HEALTH WATCHDOG ─────────────────────────────────────────────────

_WATCHDOG_PROMPT = (
    "You are a quality control system monitoring a 3D printer. "
    "Analyze this image of the print bed. "
    "Determine if the print is healthy or if there is a failure. "
    "Look specifically for: spaghetti (filament spaghetti from a detached print), "
    "bed detachment, or no print present. "
    "Return ONLY a valid JSON object: "
    "{\"healthy\": bool, \"issue_detected\": string (spaghetti|detachment|none), "
    "\"confidence\": float 0.0-1.0, "
    "\"action_recommended\": string (continue|pause|abort)}."
)

_WATCHDOG_FALLBACK: dict = {
    "healthy":            True,
    "issue_detected":     "none",
    "confidence":         0.0,
    "action_recommended": "continue",
}


def check_print_health(base64_image: str) -> dict:
    """
    Returns a health assessment of the current print state.
    Falls back to a safe 'healthy/continue' response on any failure.
    """
    if not base64_image:
        log.warning("check_print_health called with empty image data.")
        return dict(_WATCHDOG_FALLBACK)

    raw = _call_vision_model(base64_image, _WATCHDOG_PROMPT, max_tokens=128)
    if raw is None:
        return dict(_WATCHDOG_FALLBACK)

    try:
        cleaned = _strip_markdown_fences(raw)
        result = json.loads(cleaned)
        if not isinstance(result, dict):
            log.warning("Watchdog returned non-dict JSON. Defaulting to safe fallback.")
            return dict(_WATCHDOG_FALLBACK)

        # Enforce expected keys with safe defaults
        return {
            "healthy":            bool(result.get("healthy", True)),
            "issue_detected":     str(result.get("issue_detected", "none")),
            "confidence":         float(result.get("confidence", 0.0)),
            "action_recommended": str(result.get("action_recommended", "continue")),
        }
    except json.JSONDecodeError:
        log.warning("Watchdog JSON decode failed. Raw: %r", raw)
        return dict(_WATCHDOG_FALLBACK)


# ── 4C: BED CLEARANCE VERIFIER ────────────────────────────────────────────────

_CLEARANCE_PROMPT = (
    "You are a 3D printer bed clearance verification system. "
    "Analyze this image of the printer bed. "
    "Determine if the bed is completely clear and empty, ready for the next print. "
    "A clear bed has no filament, no printed part, and no debris. "
    "Return ONLY a valid JSON object: "
    "{\"bed_clear\": bool, \"confidence\": float 0.0-1.0, \"notes\": string}."
)


def verify_bed_cleared(base64_image: str) -> bool:
    """
    Returns True if the bed appears empty and ready for the next print.
    Returns False if a part is still present, image is ambiguous, or any error occurs.
    Fails closed (returns False) on uncertainty.
    """
    if not base64_image:
        log.warning("verify_bed_cleared called with empty image data — assuming not cleared.")
        return False

    raw = _call_vision_model(base64_image, _CLEARANCE_PROMPT, max_tokens=128)
    if raw is None:
        log.warning("verify_bed_cleared: API call failed — assuming not cleared (fail-closed).")
        return False

    try:
        cleaned = _strip_markdown_fences(raw)
        result = json.loads(cleaned)
        if not isinstance(result, dict):
            log.warning("Clearance check returned non-dict — assuming not cleared.")
            return False

        bed_clear = bool(result.get("bed_clear", False))
        confidence = float(result.get("confidence", 0.0))

        # Only confirm cleared if confidence is reasonably high
        if bed_clear and confidence >= 0.75:
            log.info("Bed clearance confirmed (confidence=%.2f).", confidence)
            return True

        log.info(
            "Bed not confirmed clear: bed_clear=%s, confidence=%.2f.", bed_clear, confidence
        )
        return False

    except json.JSONDecodeError:
        log.warning("Clearance check JSON decode failed. Raw: %r — assuming not cleared.", raw)
        return False
