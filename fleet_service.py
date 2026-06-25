"""
Fleet Aggregation Service
Computes fleet-wide metrics, system health, and operational analytics
"""

import logging
from typing import Dict, List
from datetime import datetime
from models import (
    PrinterTelemetry, FleetAggregates, PrinterStatus,
    ControlCommand
)

logger = logging.getLogger("NEMO_FLEET")


class FleetAggregationService:
    """
    Aggregates printer telemetry into fleet-level insights.
    Computes health diagnostics, operational metrics, and predictive ETAs.
    """

    def __init__(self):
        self.command_history: List[ControlCommand] = []
        self.alert_log: List[dict] = []
        self.system_start_time = datetime.now()

    def compute_fleet_aggregates(self, printers: Dict[str, PrinterTelemetry], 
                                mqtt_status: str) -> FleetAggregates:
        """
        Compute fleet-wide aggregates from all printer telemetry.
        Called every time dashboard updates.
        """
        if not printers:
            return FleetAggregates(
                total_printers=0,
                active_printers=0,
                idle_printers=0,
                printing_printers=0,
                error_printers=0,
                offline_printers=0,
                fleet_print_progress=0.0,
                total_active_jobs=0,
                estimated_completion_time=0,
                total_weight_in_progress=0.0,
                system_uptime_hours=self._get_system_uptime(),
                mqtt_connection_status=mqtt_status
            )

        # Status counters
        status_counts = {
            PrinterStatus.IDLE: 0,
            PrinterStatus.PRINTING: 0,
            PrinterStatus.PAUSED: 0,
            PrinterStatus.ERROR: 0,
            PrinterStatus.OFFLINE: 0,
            PrinterStatus.MAINTENANCE: 0,
        }

        printing_progresses = []
        completion_times = []
        total_weight_in_progress = 0.0

        for printer_id, printer in printers.items():
            # Count status
            status_counts[printer.status] += 1

            # Aggregate print progress
            if printer.job and printer.status == PrinterStatus.PRINTING:
                printing_progresses.append(printer.job.progress_percent)
                completion_times.append(printer.job.time_remaining)
                total_weight_in_progress += printer.job.weight_used

        # Calculate aggregates
        total_printers = len(printers)
        printing_printers = status_counts[PrinterStatus.PRINTING]
        paused_printers = status_counts[PrinterStatus.PAUSED]
        active_printers = printing_printers + paused_printers
        idle_printers = status_counts[PrinterStatus.IDLE]
        error_printers = status_counts[PrinterStatus.ERROR]
        offline_printers = status_counts[PrinterStatus.OFFLINE]

        # Fleet print progress (weighted average of active jobs)
        fleet_progress = (
            sum(printing_progresses) / len(printing_progresses)
            if printing_progresses else 0.0
        )

        # ETA for next job completion
        next_completion = min(completion_times) if completion_times else 0

        return FleetAggregates(
            total_printers=total_printers,
            active_printers=active_printers,
            idle_printers=idle_printers,
            printing_printers=printing_printers,
            error_printers=error_printers,
            offline_printers=offline_printers,
            fleet_print_progress=fleet_progress,
            total_active_jobs=printing_printers,
            estimated_completion_time=next_completion,
            total_weight_in_progress=total_weight_in_progress,
            system_uptime_hours=self._get_system_uptime(),
            mqtt_connection_status=mqtt_status
        )

    def get_system_health(self, printers: Dict[str, PrinterTelemetry]) -> dict:
        """
        Comprehensive system health diagnostics.
        Returns health score and detailed breakdown.
        """
        if not printers:
            return {
                'overall_health': 'critical',
                'health_score': 0,
                'connectivity': 'no_printers',
                'thermal_status': 'unknown',
                'inventory_status': 'unknown',
                'alerts': ['No printers registered']
            }

        alerts = []
        thermal_issues = 0
        connectivity_issues = 0
        inventory_warnings = 0

        for printer_id, printer in printers.items():
            # Thermal warnings
            if printer.thermal.nozzle_temp > 250:
                thermal_issues += 1
                alerts.append(f"🔥 {printer.printer_name}: Nozzle overheating ({printer.thermal.nozzle_temp}°C)")
            
            if printer.thermal.bed_temp > 110:
                thermal_issues += 1
                alerts.append(f"🔥 {printer.printer_name}: Bed overheating ({printer.thermal.bed_temp}°C)")

            # Connectivity issues
            if printer.status == PrinterStatus.OFFLINE:
                connectivity_issues += 1
                alerts.append(f"📡 {printer.printer_name}: Offline/Unreachable")
            
            if printer.wifi_signal_strength < -80:
                connectivity_issues += 1
                alerts.append(f"📡 {printer.printer_name}: Weak WiFi signal ({printer.wifi_signal_strength}dBm)")

            # Inventory warnings
            if printer.active_spool and printer.active_spool.percent_remaining < 15:
                inventory_warnings += 1
                alerts.append(f"📦 {printer.printer_name}: Filament running low ({printer.active_spool.percent_remaining:.1f}%)")

            # Error state
            if printer.status == PrinterStatus.ERROR:
                alerts.append(f"⚠️  {printer.printer_name}: In error state")

        # Compute health score (0-100)
        total_printers = len(printers)
        offline_count = sum(1 for p in printers.values() if p.status == PrinterStatus.OFFLINE)
        error_count = sum(1 for p in printers.values() if p.status == PrinterStatus.ERROR)

        connectivity_health = ((total_printers - offline_count) / total_printers) * 100
        thermal_health = max(0, 100 - (thermal_issues * 15))
        inventory_health = max(0, 100 - (inventory_warnings * 10))
        error_health = max(0, 100 - (error_count * 20))

        overall_score = (
            connectivity_health * 0.40 +
            thermal_health * 0.25 +
            inventory_health * 0.20 +
            error_health * 0.15
        )

        # Categorize health
        if overall_score >= 90:
            status = 'excellent'
        elif overall_score >= 75:
            status = 'good'
        elif overall_score >= 50:
            status = 'warning'
        else:
            status = 'critical'

        return {
            'overall_health': status,
            'health_score': round(overall_score, 1),
            'connectivity_health': round(connectivity_health, 1),
            'thermal_health': round(thermal_health, 1),
            'inventory_health': round(inventory_health, 1),
            'error_health': round(error_health, 1),
            'offline_printers': offline_count,
            'error_printers': error_count,
            'alerts': alerts[:10]  # Top 10 alerts
        }

    def get_inventory_summary(self, printers: Dict[str, PrinterTelemetry]) -> dict:
        """
        Aggregate all spool inventory across the fleet.
        Returns material types, quantities, and low-stock warnings.
        """
        inventory = {
            'by_material': {},
            'by_printer': {},
            'low_stock_alerts': [],
            'total_weight_grams': 0.0
        }

        for printer_id, printer in printers.items():
            if printer.active_spool:
                spool = printer.active_spool
                
                # Track by material
                if spool.material_type not in inventory['by_material']:
                    inventory['by_material'][spool.material_type] = {
                        'total_weight': 0.0,
                        'spools': []
                    }
                
                inventory['by_material'][spool.material_type]['total_weight'] += spool.weight_remaining
                inventory['by_material'][spool.material_type]['spools'].append({
                    'printer': printer.printer_name,
                    'weight': spool.weight_remaining,
                    'color': spool.color,
                    'percent': spool.percent_remaining
                })
                
                # Track by printer
                inventory['by_printer'][printer.printer_name] = {
                    'material': spool.material_type,
                    'weight_remaining': spool.weight_remaining,
                    'percent_remaining': spool.percent_remaining,
                    'color': spool.color
                }
                
                # Update total
                inventory['total_weight_grams'] += spool.weight_remaining
                
                # Low stock alert
                if spool.percent_remaining < 20:
                    inventory['low_stock_alerts'].append({
                        'printer': printer.printer_name,
                        'material': spool.material_type,
                        'percent': spool.percent_remaining,
                        'weight': spool.weight_remaining
                    })

        return inventory

    def detect_anomalies(self, printer: PrinterTelemetry) -> List[str]:
        """
        Detect operational anomalies in a single printer.
        Returns list of anomalies detected.
        """
        anomalies = []

        # Temperature anomalies
        if printer.thermal.nozzle_temp > 260:
            anomalies.append("NOZZLE_OVERHEAT")
        if printer.thermal.bed_temp > 120:
            anomalies.append("BED_OVERHEAT")
        if printer.status == PrinterStatus.PRINTING and printer.thermal.nozzle_temp < 190:
            anomalies.append("NOZZLE_UNDERHEAT")

        # Print quality issues
        if printer.job and printer.job.progress_percent > 0:
            # If printing for >30 mins but stuck at same %
            if printer.job.time_elapsed > 1800 and printer.job.progress_percent < 5:
                anomalies.append("PRINT_STALLED")

        # Connectivity issues
        if printer.wifi_signal_strength < -90:
            anomalies.append("POOR_WIFI")

        # Filament issues
        if printer.active_spool and printer.active_spool.percent_remaining < 5:
            anomalies.append("CRITICAL_FILAMENT_LOW")

        return anomalies

    def log_command(self, command: ControlCommand):
        """Log executed command to history"""
        self.command_history.append(command)
        # Keep last 1000 commands
        if len(self.command_history) > 1000:
            self.command_history = self.command_history[-1000:]

    def get_command_history(self, limit: int = 100) -> List[dict]:
        """Retrieve command execution history"""
        return [
            c.to_dict() for c in self.command_history[-limit:]
        ]

    def _get_system_uptime(self) -> float:
        """Calculate system uptime in hours since startup"""
        delta = datetime.now() - self.system_start_time
        return delta.total_seconds() / 3600
