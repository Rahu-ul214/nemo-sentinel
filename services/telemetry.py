import logging
import json
import ssl
import paho.mqtt.client as mqtt
import threading
import time
import random
from typing import Any, Dict

from core.config import BAMBU_TOKEN, BAMBU_DEVICE_ID, BAMBU_CLOUD_HOST, PRINTER_LOCAL_IP, PRINTER_ACCESS_CODE, USE_LOCAL_MQTT, MOCK_MODE
from core.state import STATUS
from services.mqtt_parser import BambuMqttParser

log = logging.getLogger("sentinel.telemetry")

class BambuMqttClient:
    """
    Handles live telemetry streaming from Bambu Lab printers.
    Supports Cloud, Local, and Mock Simulation modes for development.
    """

    def __init__(self):
        self.port = 8883
        self.username = "bblp"
        self.device_id = BAMBU_DEVICE_ID

        if not self.device_id:
            raise RuntimeError("BAMBU_DEVICE_ID is not set in .env. Telemetry requires a device ID.")

        # Resolve Host and Password based on connection mode
        if MOCK_MODE:
            log.info("[CONFIG] Mode: MOCK SIMULATION")
            self.host = "mock.local"
            self.password = "mock_pass"
            self._mock_thread = None
            self._stop_mock = threading.Event()
        elif USE_LOCAL_MQTT:
            log.info("[CONFIG] Mode: LOCAL MQTT")
            self.host = (PRINTER_LOCAL_IP or "").strip()
            self.password = (PRINTER_ACCESS_CODE or "").strip()
            if not self.host:
                raise RuntimeError("USE_LOCAL_MQTT is True, but PRINTER_LOCAL_IP is missing in .env")
            if not self.password:
                raise RuntimeError("USE_LOCAL_MQTT is True, but PRINTER_ACCESS_CODE is missing in .env")
        else:
            log.info("[CONFIG] Mode: CLOUD MQTT")
            self.host = (BAMBU_CLOUD_HOST or "eu.mqtt.bambulab.com").strip()
            self.password = (BAMBU_TOKEN or "").strip()
            if not self.password:
                raise RuntimeError("USE_LOCAL_MQTT is False, but BAMBU_TOKEN is missing in .env")

        self.parser = BambuMqttParser()
        self.client = mqtt.Client()

        # Assign callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            mode = "Local" if USE_LOCAL_MQTT else ("Cloud" if not MOCK_MODE else "Mock")
            log.info("[MQTT] Connected successfully to %s broker at %s", mode, self.host)
            topic = f"device/{self.device_id}/report"
            client.subscribe(topic)
            log.info("[MQTT] Subscribed to topic: %s", topic)
            STATUS.update(mqtt_connected=True)
        else:
            log.error("[MQTT] Connection failed with result code %d", rc)
            STATUS.update(mqtt_connected=False)

    def _on_disconnect(self, client, userdata, rc):
        log.info("[MQTT] Disconnected from broker.")
        STATUS.update(mqtt_connected=False)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            self._process_payload(payload)
        except Exception as e:
            log.error("[MQTT] Failed to parse incoming message: %s", e)

    def _process_payload(self, payload: Dict[str, Any]):
        """
        Common logic to parse payload and update the global state.
        Used by both real MQTT and Mock Simulator.
        """
        parsed_status = self.parser.parse_payload(payload)
        STATUS.update(
            gcode_state=parsed_status.gcode_state,
            print_progress=int(parsed_status.print_progress),
            total_estimated_time=parsed_status.remaining_time,
            nozzle_temp=parsed_status.nozzle_temp,
            bed_temp=parsed_status.bed_temp,
            ams_data=parsed_status.ams_slots
        )
        log.debug("[TELEMETRY] State updated: %s (%d%%)", parsed_status.gcode_state, parsed_status.print_progress)

    def _run_mock_simulator(self):
        """
        Simulates a realistic print lifecycle by injecting mock payloads.
        """
        log.info("[MOCK] Starting telemetry simulation loop...")

        # Simulation State
        percent = 0.0
        state = "PREPARING"
        nozzle = 20.0
        bed = 20.0

        while not self._stop_mock.is_set():
            # 1. Simulate Temperature Ramp-up
            if state == "PREPARING":
                nozzle = min(nozzle + 5.0, 220.0)
                bed = min(bed + 2.0, 60.0)
                if nozzle >= 220.0 and bed >= 60.0:
                    state = "PRINTING"
                    log.info("[MOCK] Temperature reached. Transitioning to PRINTING.")

            # 2. Simulate Printing Progress
            elif state == "PRINTING":
                percent += random.uniform(0.5, 2.0)
                nozzle = 220.0 + random.uniform(-1.0, 1.0)
                bed = 60.0 + random.uniform(-0.5, 0.5)

                if percent >= 100.0:
                    percent = 100.0
                    state = "FINISH"
                    log.info("[MOCK] Print complete. Transitioning to FINISH.")

            # 3. Construct Mock Payload (Matching real Bambu MQTT structure)
            mock_payload = {
                "print": {
                    "gcode_state": state,
                    "nozzle_temper": nozzle,
                    "bed_temper": bed,
                    "mc_percent": percent,
                    "mc_remaining_time": int((100 - percent) * 60) # Simple estimate
                }
            }

            # Pass through the actual parser to ensure downstream compatibility
            self._process_payload(mock_payload)

            time.sleep(3)

    def connect(self):
        """
        Establish connection. If MOCK_MODE is enabled, skips network setup
        and starts the internal simulation thread.
        """
        if MOCK_MODE:
            log.info("[MOCK] Bypassing TLS/MQTT handshake. Initializing simulation thread.")
            self._stop_mock = threading.Event()
            self._mock_thread = threading.Thread(target=self._run_mock_simulator, daemon=True)
            self._mock_thread.start()
            STATUS.update(mqtt_connected=True)
            return

        try:
            self.client.username_pw_set(self.username, self.password)
            clean_host = self.host.split(':')[0]

            if USE_LOCAL_MQTT:
                self.client.tls_set(cert_reqs=ssl.CERT_NONE)
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.client.tls_set(context=context)
            else:
                self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

            log.info("[MQTT] Connecting to %s on port %d...", clean_host, self.port)
            self.client.connect(clean_host, port=self.port, keepalive=60)
        except Exception as e:
            log.error("[MQTT] Connection setup failed: %s", e)
            raise

    def start(self):
        """Starts the MQTT loop in a background thread."""
        if not MOCK_MODE:
            self.client.loop_start()

    def stop(self):
        """Stops the MQTT loop or simulation thread."""
        if MOCK_MODE:
            self._stop_mock.set()
            if self._mock_thread:
                self._mock_thread.join(timeout=2)
        else:
            self.client.loop_stop()
            self.client.disconnect()
