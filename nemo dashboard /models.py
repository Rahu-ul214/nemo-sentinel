"""
Data models for NEMO Fleet Management System
Defines all structures for printers, telemetry, inventory, and system health
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum
import json


class PrinterStatus(str, Enum):
    IDLE = "idle"
    PRINTING = "printing"
    PAUSED = "paused"
    ERROR = "error"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class PrinterModel(str, Enum):
    X1 = "X1"
    X1_CARBON = "X1_CARBON"
    P1P = "P1P"
    P1S = "P1S"
    A1 = "A1"
    CUSTOM = "CUSTOM"


@dataclass
class ThermalMetrics:
    """Current temperature readings from a printer"""
    nozzle_temp: float
    nozzle_target: float
    bed_temp: float
    bed_target: float
    chamber_temp: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self):
        return {
            'nozzle_temp': self.nozzle_temp,
            'nozzle_target': self.nozzle_target,
            'bed_temp': self.bed_temp,
            'bed_target': self.bed_target,
            'chamber_temp': self.chamber_temp,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class JobMetrics:
    """Current print job progress"""
    job_name: str
    print_type: str  # "nylon" / "pla" / "tpu" etc
    progress_percent: float  # 0-100
    print_speed: float  # mm/s
    layer_height: float
    current_layer: int
    total_layers: int
    time_elapsed: int  # seconds
    time_remaining: int  # seconds (estimated)
    weight_used: float  # grams
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self):
        return {
            'job_name': self.job_name,
            'print_type': self.print_type,
            'progress_percent': self.progress_percent,
            'print_speed': self.print_speed,
            'layer_height': self.layer_height,
            'current_layer': self.current_layer,
            'total_layers': self.total_layers,
            'time_elapsed': self.time_elapsed,
            'time_remaining': self.time_remaining,
            'weight_used': self.weight_used,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class SpoolInventory:
    """Filament spool tracking"""
    spool_id: str
    material_type: str  # PLA, PETG, TPU, Nylon, etc
    color: str
    weight_remaining: float  # grams
    weight_total: float  # grams
    percent_remaining: float  # 0-100
    last_used: datetime
    location: str  # Printer slot identifier

    def to_dict(self):
        return {
            'spool_id': self.spool_id,
            'material_type': self.material_type,
            'color': self.color,
            'weight_remaining': self.weight_remaining,
            'weight_total': self.weight_total,
            'percent_remaining': self.percent_remaining,
            'last_used': self.last_used.isoformat(),
            'location': self.location
        }


@dataclass
class PrinterTelemetry:
    """Complete telemetry snapshot for a single printer"""
    printer_id: str
    printer_name: str
    model: PrinterModel
    status: PrinterStatus
    thermal: ThermalMetrics
    job: Optional[JobMetrics] = None
    active_spool: Optional[SpoolInventory] = None
    uptime_hours: float = 0.0
    print_count: int = 0
    error_count: int = 0
    last_update: datetime = field(default_factory=datetime.now)
    wifi_signal_strength: int = -1  # dBm
    ip_address: str = "0.0.0.0"

    def to_dict(self):
        return {
            'printer_id': self.printer_id,
            'printer_name': self.printer_name,
            'model': self.model.value,
            'status': self.status.value,
            'thermal': self.thermal.to_dict(),
            'job': self.job.to_dict() if self.job else None,
            'active_spool': self.active_spool.to_dict() if self.active_spool else None,
            'uptime_hours': self.uptime_hours,
            'print_count': self.print_count,
            'error_count': self.error_count,
            'last_update': self.last_update.isoformat(),
            'wifi_signal_strength': self.wifi_signal_strength,
            'ip_address': self.ip_address
        }


@dataclass
class FleetAggregates:
    """System-level metrics aggregated across all printers"""
    total_printers: int
    active_printers: int
    idle_printers: int
    printing_printers: int
    error_printers: int
    offline_printers: int
    fleet_print_progress: float  # weighted average %
    total_active_jobs: int
    estimated_completion_time: int  # seconds for next job to finish
    total_weight_in_progress: float  # grams
    system_uptime_hours: float
    mqtt_connection_status: str  # "connected" / "reconnecting" / "disconnected"
    last_sync: datetime = field(default_factory=datetime.now)

    def to_dict(self):
        return {
            'total_printers': self.total_printers,
            'active_printers': self.active_printers,
            'idle_printers': self.idle_printers,
            'printing_printers': self.printing_printers,
            'error_printers': self.error_printers,
            'offline_printers': self.offline_printers,
            'fleet_print_progress': self.fleet_print_progress,
            'total_active_jobs': self.total_active_jobs,
            'estimated_completion_time': self.estimated_completion_time,
            'total_weight_in_progress': self.total_weight_in_progress,
            'system_uptime_hours': self.system_uptime_hours,
            'mqtt_connection_status': self.mqtt_connection_status,
            'last_sync': self.last_sync.isoformat()
        }


@dataclass
class ControlCommand:
    """Command to be sent to a printer"""
    printer_id: str
    command_type: str  # "pause" / "resume" / "cancel" / "clear_bed" / "home" / "load_filament"
    parameters: Dict = field(default_factory=dict)
    issued_at: datetime = field(default_factory=datetime.now)
    executed: bool = False
    execution_time: Optional[datetime] = None

    def to_dict(self):
        return {
            'printer_id': self.printer_id,
            'command_type': self.command_type,
            'parameters': self.parameters,
            'issued_at': self.issued_at.isoformat(),
            'executed': self.executed,
            'execution_time': self.execution_time.isoformat() if self.execution_time else None
        }
