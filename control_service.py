"""
Tactical Control Service
Handles remote commands (pause, resume, cancel, etc.) with safety checks
"""

import logging
from typing import Tuple, Optional
from datetime import datetime
from models import ControlCommand, PrinterStatus, PrinterTelemetry

logger = logging.getLogger("NEMO_CONTROL")


class TacticalControlService:
    """
    Manages printer control commands with safety validation.
    Prevents dangerous operations and logs all actions.
    """

    # Valid command types
    VALID_COMMANDS = {
        'pause': 'Pause current print job',
        'resume': 'Resume paused print job',
        'cancel': 'Cancel current print job',
        'home_all': 'Home all axes',
        'home_x': 'Home X axis only',
        'home_y': 'Home Y axis only',
        'home_z': 'Home Z axis only',
        'clear_bed': 'Trigger bed clearing (NEMO actuator)',
        'load_filament': 'Load filament into extruder',
        'unload_filament': 'Unload filament from extruder',
        'set_nozzle_temp': 'Set nozzle temperature',
        'set_bed_temp': 'Set bed temperature',
        'emergency_stop': 'Emergency stop all operations',
    }

    def __init__(self, mqtt_service):
        self.mqtt_service = mqtt_service
        self.command_queue = []

    def pause_job(self, printer_id: str, printer: PrinterTelemetry) -> Tuple[bool, str]:
        """Pause an active print job"""
        # Safety checks
        if printer.status != PrinterStatus.PRINTING:
            return False, f"Printer not printing (status: {printer.status.value})"

        if not printer.job:
            return False, "No active job detected"

        try:
            self.mqtt_service.send_command(printer_id, 'pause')
            logger.info(f"[CONTROL] Pause command sent to {printer_id}")
            return True, f"Pause command sent to {printer.printer_name}"
        except Exception as e:
            return False, f"Failed to send pause command: {str(e)}"

    def resume_job(self, printer_id: str, printer: PrinterTelemetry) -> Tuple[bool, str]:
        """Resume a paused print job"""
        if printer.status != PrinterStatus.PAUSED:
            return False, f"Printer not paused (status: {printer.status.value})"

        try:
            self.mqtt_service.send_command(printer_id, 'resume')
            logger.info(f"[CONTROL] Resume command sent to {printer_id}")
            return True, f"Resume command sent to {printer.printer_name}"
        except Exception as e:
            return False, f"Failed to send resume command: {str(e)}"

    def cancel_job(self, printer_id: str, printer: PrinterTelemetry) -> Tuple[bool, str]:
        """Cancel an active or paused job"""
        if printer.status not in [PrinterStatus.PRINTING, PrinterStatus.PAUSED]:
            return False, f"No active job to cancel (status: {printer.status.value})"

        try:
            self.mqtt_service.send_command(printer_id, 'stop_print')
            logger.info(f"[CONTROL] Cancel command sent to {printer_id}")
            return True, f"Job cancellation command sent to {printer.printer_name}"
        except Exception as e:
            return False, f"Failed to cancel job: {str(e)}"

    def clear_bed(self, printer_id: str, printer: PrinterTelemetry) -> Tuple[bool, str]:
        """
        Trigger NEMO actuator to clear the build plate.
        Safety checks: printer must be idle/offline or job must be completed.
        """
        # Check if safe to clear
        if printer.status == PrinterStatus.PRINTING:
            return False, "Cannot clear bed while printing. Pause or cancel first."

        if printer.status == PrinterStatus.PAUSED:
            return False, "Cannot clear bed while paused. Cancel job first."

        try:
            # Send clear_bed command via NEMO's MQTT interface
            self.mqtt_service.send_command(printer_id, 'clear_bed')
            logger.info(f"[CONTROL] Clear bed command sent to {printer_id} (NEMO actuator)")
            return True, f"Bed clearing initiated on {printer.printer_name}"
        except Exception as e:
            return False, f"Failed to trigger bed clear: {str(e)}"

    def set_temperature(self, printer_id: str, printer: PrinterTelemetry,
                       nozzle_temp: Optional[float] = None,
                       bed_temp: Optional[float] = None) -> Tuple[bool, str]:
        """
        Adjust nozzle and/or bed temperature.
        Safety limits: Nozzle (150-260°C), Bed (20-120°C)
        """
        if printer.status == PrinterStatus.OFFLINE:
            return False, "Printer is offline"

        errors = []

        if nozzle_temp is not None:
            if not (150 <= nozzle_temp <= 260):
                errors.append(f"Nozzle temp out of range: {nozzle_temp}°C (valid: 150-260°C)")
            else:
                try:
                    self.mqtt_service.send_command(
                        printer_id, 'set_nozzle_temp',
                        temperature=nozzle_temp
                    )
                except Exception as e:
                    errors.append(f"Failed to set nozzle temp: {str(e)}")

        if bed_temp is not None:
            if not (20 <= bed_temp <= 120):
                errors.append(f"Bed temp out of range: {bed_temp}°C (valid: 20-120°C)")
            else:
                try:
                    self.mqtt_service.send_command(
                        printer_id, 'set_bed_temp',
                        temperature=bed_temp
                    )
                except Exception as e:
                    errors.append(f"Failed to set bed temp: {str(e)}")

        if errors:
            return False, " | ".join(errors)

        msg = []
        if nozzle_temp:
            msg.append(f"Nozzle to {nozzle_temp}°C")
        if bed_temp:
            msg.append(f"Bed to {bed_temp}°C")

        logger.info(f"[CONTROL] Temperature adjustment on {printer_id}: {', '.join(msg)}")
        return True, f"Temperature command sent to {printer.printer_name}"

    def home_axis(self, printer_id: str, printer: PrinterTelemetry,
                  axis: str = 'all') -> Tuple[bool, str]:
        """
        Home specified axis/axes.
        Valid axes: 'x', 'y', 'z', 'all'
        """
        if printer.status == PrinterStatus.PRINTING:
            return False, "Cannot home axes while printing"

        if printer.status == PrinterStatus.OFFLINE:
            return False, "Printer is offline"

        axis = axis.lower()
        valid_axes = ['x', 'y', 'z', 'all']

        if axis not in valid_axes:
            return False, f"Invalid axis: {axis}. Valid: {', '.join(valid_axes)}"

        try:
            command = 'home_all' if axis == 'all' else f'home_{axis}'
            self.mqtt_service.send_command(printer_id, command)
            logger.info(f"[CONTROL] Home {axis.upper()} command sent to {printer_id}")
            return True, f"Home {axis.upper()} command sent to {printer.printer_name}"
        except Exception as e:
            return False, f"Failed to send home command: {str(e)}"

    def load_filament(self, printer_id: str, printer: PrinterTelemetry) -> Tuple[bool, str]:
        """Trigger filament load sequence"""
        if printer.status == PrinterStatus.PRINTING:
            return False, "Cannot load filament while printing"

        try:
            self.mqtt_service.send_command(printer_id, 'load_filament')
            logger.info(f"[CONTROL] Filament load command sent to {printer_id}")
            return True, f"Filament load sequence initiated on {printer.printer_name}"
        except Exception as e:
            return False, f"Failed to load filament: {str(e)}"

    def unload_filament(self, printer_id: str, printer: PrinterTelemetry) -> Tuple[bool, str]:
        """Trigger filament unload sequence"""
        if printer.status == PrinterStatus.PRINTING:
            return False, "Cannot unload filament while printing"

        try:
            self.mqtt_service.send_command(printer_id, 'unload_filament')
            logger.info(f"[CONTROL] Filament unload command sent to {printer_id}")
            return True, f"Filament unload sequence initiated on {printer.printer_name}"
        except Exception as e:
            return False, f"Failed to unload filament: {str(e)}"

    def emergency_stop(self, printer_id: str) -> Tuple[bool, str]:
        """
        Emergency stop - immediately kills all operations.
        Use sparingly!
        """
        try:
            self.mqtt_service.send_command(printer_id, 'emergency_stop')
            logger.critical(f"[CONTROL] EMERGENCY STOP issued on {printer_id}")
            return True, f"EMERGENCY STOP command sent to {printer_id}"
        except Exception as e:
            return False, f"Failed to issue emergency stop: {str(e)}"

    def validate_command(self, command_type: str) -> bool:
        """Check if command type is valid"""
        return command_type in self.VALID_COMMANDS

    def get_command_help(self) -> dict:
        """Return documentation of all available commands"""
        return self.VALID_COMMANDS
