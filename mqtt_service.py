"""
MQTT Telemetry Service for NEMO Fleet Management
Handles real-time connection to Bambu Cloud broker and message parsing
"""

import paho.mqtt.client as mqtt
import json
import logging
from typing import Dict, Callable, Optional
from datetime import datetime
import threading
from collections import deque
from models import (
    PrinterTelemetry, ThermalMetrics, JobMetrics, SpoolInventory,
    PrinterStatus, PrinterModel
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEMO_MQTT")


class MQTTTelemetryService:
    """
    Manages MQTT connection to Bambu Lab Cloud broker and parses printer telemetry.
    Maintains thread-safe queues for real-time data streaming.
    """

    def __init__(self, broker_host: str, broker_port: int, username: str, password: str):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password
        
        self.client = mqtt.Client(client_id="nemo_fleet_dashboard")
        self.client.username_pw_set(username, password)
        
        # Callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        
        # Data storage
        self.printer_telemetry: Dict[str, PrinterTelemetry] = {}
        self.telemetry_queue = deque(maxlen=1000)  # Keep last 1000 messages
        self.connection_status = "disconnected"
        self.message_count = 0
        
        # Thread safety
        self.lock = threading.RLock()
        self.custom_callbacks: Dict[str, Callable] = {}
        
        # Connection state
        self.is_connected = False

    def connect(self):
        """Establish connection to MQTT broker"""
        try:
            logger.info(f"[MQTT] Connecting to {self.broker_host}:{self.broker_port}")
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()  # Start background thread
            self.is_connected = True
        except Exception as e:
            logger.error(f"[MQTT] Connection failed: {e}")
            self.connection_status = "error"

    def disconnect(self):
        """Gracefully disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()
        self.is_connected = False
        logger.info("[MQTT] Disconnected")

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when MQTT client connects"""
        if rc == 0:
            logger.info("[MQTT] Connected successfully")
            self.connection_status = "connected"
            # Subscribe to all printer topics
            client.subscribe("device/+/report")
            client.subscribe("device/+/request")
        else:
            logger.error(f"[MQTT] Connection failed with code {rc}")
            self.connection_status = "failed"

    def _on_message(self, client, userdata, msg):
        """Callback when message received from broker"""
        try:
            with self.lock:
                self.message_count += 1
                
                topic = msg.topic
                payload = json.loads(msg.payload.decode('utf-8'))
                
                # Parse device report: device/{serial}/report
                if "/report" in topic:
                    parts = topic.split("/")
                    if len(parts) >= 2:
                        device_id = parts[1]
                        self._parse_device_report(device_id, payload)
                
                # Store in queue
                self.telemetry_queue.append({
                    'timestamp': datetime.now().isoformat(),
                    'topic': topic,
                    'device_id': topic.split("/")[1] if "/" in topic else None,
                    'payload': payload
                })
                
                # Trigger custom callbacks
                for callback in self.custom_callbacks.values():
                    try:
                        callback(device_id, payload)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")
                        
        except json.JSONDecodeError:
            logger.warning(f"[MQTT] Failed to parse JSON: {msg.payload}")
        except Exception as e:
            logger.error(f"[MQTT] Message processing error: {e}")

    def _on_disconnect(self, client, userdata, rc):
        """Callback when MQTT client disconnects"""
        if rc != 0:
            logger.warning(f"[MQTT] Unexpected disconnection with code {rc}")
            self.connection_status = "reconnecting"
        else:
            logger.info("[MQTT] Intentional disconnection")
            self.connection_status = "disconnected"
        self.is_connected = False

    def _parse_device_report(self, device_id: str, payload: dict):
        """
        Parse Bambu Lab device report and extract telemetry.
        Bambu reports have this structure: {"print": {...}, "printer": {...}, ...}
        """
        try:
            # Extract printer metadata
            printer_name = payload.get('name', device_id)
            model = payload.get('dev_id', 'CUSTOM')
            
            # Map Bambu model codes to our enum
            model_map = {
                'X1': PrinterModel.X1,
                'X1C': PrinterModel.X1_CARBON,
                'P1P': PrinterModel.P1P,
                'P1S': PrinterModel.P1S,
                'A1': PrinterModel.A1,
            }
            printer_model = model_map.get(model, PrinterModel.CUSTOM)
            
            # Extract printer status
            status_str = payload.get('print_state', 'offline').lower()
            status_map = {
                'idle': PrinterStatus.IDLE,
                'printing': PrinterStatus.PRINTING,
                'paused': PrinterStatus.PAUSED,
                'pausing': PrinterStatus.PAUSED,
                'error': PrinterStatus.ERROR,
                'offline': PrinterStatus.OFFLINE,
            }
            status = status_map.get(status_str, PrinterStatus.OFFLINE)
            
            # Thermal metrics
            nozzle_temp = payload.get('nozzle_temper', 0)
            nozzle_target = payload.get('nozzle_target_temper', 0)
            bed_temp = payload.get('bed_temper', 0)
            bed_target = payload.get('bed_target_temper', 0)
            chamber_temp = payload.get('chamber_temper')
            
            thermal = ThermalMetrics(
                nozzle_temp=float(nozzle_temp),
                nozzle_target=float(nozzle_target),
                bed_temp=float(bed_temp),
                bed_target=float(bed_target),
                chamber_temp=float(chamber_temp) if chamber_temp else None
            )
            
            # Job metrics (if printing)
            job = None
            if status == PrinterStatus.PRINTING and 'print' in payload:
                print_data = payload['print']
                job = JobMetrics(
                    job_name=print_data.get('task_id', 'Unknown'),
                    print_type=print_data.get('filament_type', 'unknown'),
                    progress_percent=float(print_data.get('progress', 0)) * 100,
                    print_speed=float(print_data.get('spd_lvl', 0)),
                    layer_height=float(print_data.get('layer_num', 0)) * 0.2,  # Approximate
                    current_layer=int(print_data.get('layer_num', 0)),
                    total_layers=int(print_data.get('total_layer_num', 0)),
                    time_elapsed=int(print_data.get('elapsed_time', 0)),
                    time_remaining=int(print_data.get('remain_time', 0)),
                    weight_used=float(print_data.get('weight_used', 0)) / 1000  # Convert to grams
                )
            
            # Spool inventory
            spool = None
            if 'ams' in payload and len(payload['ams'].get('ams', [])) > 0:
                ams_data = payload['ams']['ams'][0]  # First AMS unit
                if 'tray' in ams_data and len(ams_data['tray']) > 0:
                    tray = ams_data['tray'][0]  # Current tray
                    spool = SpoolInventory(
                        spool_id=tray.get('id', 'unknown'),
                        material_type=tray.get('type', 'unknown'),
                        color=tray.get('color', '#000000'),
                        weight_remaining=float(tray.get('weight', 0)),
                        weight_total=1000.0,  # Bambu standard spool
                        percent_remaining=(float(tray.get('weight', 0)) / 1000.0) * 100,
                        last_used=datetime.now(),
                        location=f"AMS_0_Tray_0"
                    )
            
            # System stats
            wifi_signal = payload.get('wifi_signal', '-1')
            ip_address = payload.get('ip', '0.0.0.0')
            uptime = float(payload.get('total_printing_time', 0)) / 3600  # Convert to hours
            print_count = int(payload.get('print_count', 0))
            error_count = int(payload.get('error_count', 0))
            
            # Build complete telemetry object
            telemetry = PrinterTelemetry(
                printer_id=device_id,
                printer_name=printer_name,
                model=printer_model,
                status=status,
                thermal=thermal,
                job=job,
                active_spool=spool,
                uptime_hours=uptime,
                print_count=print_count,
                error_count=error_count,
                wifi_signal_strength=int(wifi_signal) if wifi_signal != '-1' else -1,
                ip_address=ip_address
            )
            
            # Store in memory
            with self.lock:
                self.printer_telemetry[device_id] = telemetry
                
        except Exception as e:
            logger.error(f"[PARSE] Error parsing device report for {device_id}: {e}")

    def get_printer_telemetry(self, printer_id: str) -> Optional[PrinterTelemetry]:
        """Retrieve latest telemetry for a specific printer"""
        with self.lock:
            return self.printer_telemetry.get(printer_id)

    def get_all_printers(self) -> Dict[str, PrinterTelemetry]:
        """Retrieve telemetry for all printers (thread-safe copy)"""
        with self.lock:
            return dict(self.printer_telemetry)

    def get_status(self) -> dict:
        """Get MQTT service status"""
        return {
            'connection_status': self.connection_status,
            'is_connected': self.is_connected,
            'total_printers': len(self.printer_telemetry),
            'messages_received': self.message_count,
            'queue_size': len(self.telemetry_queue)
        }

    def register_callback(self, name: str, callback: Callable):
        """Register custom callback for message processing"""
        self.custom_callbacks[name] = callback

    def send_command(self, device_id: str, command: str, **kwargs):
        """
        Send command to printer via MQTT.
        Commands: pause, resume, cancel, home_all, load_filament, etc.
        """
        try:
            payload = {
                'command': command,
                'params': kwargs
            }
            topic = f"device/{device_id}/request"
            self.client.publish(topic, json.dumps(payload), qos=1)
            logger.info(f"[CMD] Sent {command} to {device_id}")
        except Exception as e:
            logger.error(f"[CMD] Failed to send command: {e}")
