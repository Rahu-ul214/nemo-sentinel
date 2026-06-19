import cv2
import os
import time
import requests
import base64
import logging
from pathlib import Path

# Import modular components for integration testing
try:
    from vision.capture import FrameCapture
    from vision.ai_engine import AIEngine
    from core.state import STATUS
    print("✔ Integration mode: Using modular framework components.")
except ImportError:
    print("⚠ Framework imports failed. Falling back to standalone mode.")
    FrameCapture = None
    AIEngine = None

# ==============================================================================
# CONFIGURATION (Overrides for testing)
# ==============================================================================
PRINTER_IP = "10.254.244.124"
ACCESS_CODE = "d3390131"
NVIDIA_API_KEY = "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"
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "meta/llama-3.2-11b-vision-instruct"
CAMERA_URL = f"rtsps://bblp:{ACCESS_CODE}@{PRINTER_IP}:322/streaming/live/1"

def test_vision_pipeline():
    print("\n--- STEP 1: INITIALIZING CAMERA STREAM ---")

    if FrameCapture:
        # Test the modular capture service
        capture = FrameCapture(CAMERA_URL, Path("sentinel_logs/audit"))
        print(f"Using FrameCapture service for stream: {CAMERA_URL}")
        frame = capture.get_frame()
    else:
        # Fallback to raw OpenCV for standalone testing
        print(f"Standalone capture from: {CAMERA_URL}")
        cap = cv2.VideoCapture(CAMERA_URL)
        time.sleep(2)
        ret, frame = cap.read()
        cap.release()

    if frame is None:
        print("\n❌ ERROR: Could not read RTSPS stream.")
        return

    img_path = "test_snapshot.jpg"
    cv2.imwrite(img_path, frame)
    print(f"✔ SUCCESS: Frame captured and saved locally as '{img_path}'.")

    print("\n--- STEP 2: HITTING NVIDIA VISION API ---")

    if AIEngine:
        # Test the modular AI engine
        ai = AIEngine(NVIDIA_API_KEY, NVIDIA_API_URL, MODEL)
        print(f"Using AIEngine service with model: {MODEL}")
        # We pass dummy progress/layer for the test
        status_verdict = ai.query(frame, 0, 0, 0, custom_prompt="Analyze this 3D printer bed. Is the print: 'PRINTING', 'FAILED', or 'FINISHED'? Reply with ONLY ONE word.")
    else:
        # Fallback to manual request for standalone testing
        print("Standalone API request...")
        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')

        headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Accept": "application/json", "Content-Type": "application/json"}
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Analyze this 3D printer bed. Is the print: 'PRINTING', 'FAILED', or 'FINISHED'? Reply with ONLY ONE word."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]}],
            "max_tokens": 15, "temperature": 0.1
        }
        try:
            response = requests.post(NVIDIA_API_URL, headers=headers, json=payload)
            if response.status_code == 200:
                status_verdict = response.json()['choices'][0]['message']['content'].strip().upper()
            else:
                status_verdict = f"ERROR_{response.status_code}"
        except Exception as e:
            status_verdict = f"CRASH_{e}"

    print(f"\n🎉 SUCCESS! Response received!")
    print(f"🤖 AI VERDICT FOR YOUR BED: {status_verdict}")

    # Optional: Update global status if in integration mode
    if 'STATUS' in globals():
        STATUS.update(last_check_time=time.time())
        print("✔ Updated STATUS.last_check_time via core.state")

if __name__ == "__main__":
    test_vision_pipeline()
