# NEMO Fleet Management Dashboard - Setup Guide

## Overview

The NEMO Fleet Dashboard is a real-time monitoring and control system for autonomous 3D printing fleets. It connects directly to Bambu Lab's cloud MQTT broker to ingest telemetry from all connected printers.

**Architecture:**
- **Frontend**: Streamlit (rapid UI development)
- **Telemetry**: MQTT via Bambu Cloud (`us.mqtt.bambulab.com:8883`)
- **Services**: Modular Python services for fleet aggregation and control
- **Data Flow**: MQTT → Telemetry Parser → Fleet Aggregates → Dashboard UI

---

## Installation

### 1. Prerequisites

- Python 3.9+
- pip or conda
- A Bambu Lab cloud account with at least one connected printer

### 2. Clone and Install Dependencies

```bash
cd nemo_fleet
pip install -r requirements.txt
```

### 3. Environment Configuration

Create a `.env` file in the project root:

```bash
# Bambu Cloud MQTT credentials
BAMBU_MQTT_HOST=us.mqtt.bambulab.com
BAMBU_MQTT_PORT=8883
BAMBU_MQTT_USER=<your_bambu_email@example.com>
BAMBU_MQTT_PASS=<your_bambu_cloud_password>
```

**How to get your credentials:**
1. Log in to your Bambu Lab account at https://account.bambulab.com
2. Your email is your `BAMBU_MQTT_USER`
3. Your account password is your `BAMBU_MQTT_PASS`
4. Ensure all printers you want to monitor are linked to this account

### 4. Run the Dashboard

```bash
streamlit run dashboard.py
```

The app will open at `http://localhost:8501`

---

## Architecture Overview

### Service Layers

#### 1. **MQTT Telemetry Service** (`mqtt_service.py`)
- Manages connection to Bambu Cloud broker
- Subscribes to device telemetry topics (`device/{serial}/report`)
- Parses incoming JSON payloads
- Maintains thread-safe printer state

**Key Features:**
- Automatic reconnection on disconnect
- Message queuing for high-frequency updates
- Custom callback registration for extensions

#### 2. **Fleet Aggregation Service** (`fleet_service.py`)
- Computes fleet-wide metrics from individual printers
- Detects anomalies and system health issues
- Tracks inventory across the fleet
- Generates diagnostic reports

**Key Functions:**
- `compute_fleet_aggregates()` - System-level KPIs
- `get_system_health()` - Health score calculation
- `get_inventory_summary()` - Material tracking
- `detect_anomalies()` - Anomaly detection per printer

#### 3. **Tactical Control Service** (`control_service.py`)
- Issues remote commands to printers
- Validates commands before execution
- Safety checks (temperature limits, state validation)
- Command history logging

**Available Commands:**
- `pause` - Pause current job
- `resume` - Resume paused job
- `cancel` - Cancel and clear bed
- `clear_bed` - Trigger NEMO actuator
- `home_all / home_x / home_y / home_z` - Axis homing
- `load_filament / unload_filament` - AMS operations
- `set_nozzle_temp / set_bed_temp` - Temperature control
- `emergency_stop` - Kill all operations

#### 4. **Data Models** (`models.py`)
Pydantic/dataclass models for type safety:
- `PrinterTelemetry` - Complete printer state snapshot
- `ThermalMetrics` - Temperature readings
- `JobMetrics` - Print job progress
- `SpoolInventory` - Filament tracking
- `FleetAggregates` - System-level metrics
- `ControlCommand` - Command execution log

---

## Dashboard Sections

### 1. **Dashboard** (Home)
- Fleet-level KPIs: total printers, printing count, errors
- Fleet print progress (weighted average)
- Individual printer cards with thermal + job status
- Real-time health score

### 2. **Fleet Status**
- Detailed status table (model, IP, temp, uptime)
- Anomaly detection results
- WiFi signal strength monitoring

### 3. **Telemetry Feed**
- Live job metrics (progress, speed, layer count)
- Thermal telemetry (nozzle, bed, chamber temps)
- Real-time data tables

### 4. **Controls**
- Printer selection dropdown
- Job control buttons (pause/resume/cancel)
- Bed clearing (NEMO integration)
- Axis homing
- Temperature adjustment
- Filament load/unload

### 5. **Inventory**
- Aggregated filament inventory by material type
- Per-printer spool status
- Low-stock alerts
- Material type summary

### 6. **Diagnostics**
- System health scoring (0-100)
- Component health breakdown (connectivity, thermal, inventory)
- Active alert system
- Offline/error printer tracking

---

## Real-Time Data Flow

```
┌─────────────────────────────────────────────────┐
│ Bambu Cloud MQTT Broker                         │
│ (us.mqtt.bambulab.com:8883)                     │
└─────────────────┬───────────────────────────────┘
                  │ device/{serial}/report
                  ↓
┌─────────────────────────────────────────────────┐
│ MQTT Telemetry Service                          │
│ - Parse JSON payloads                           │
│ - Extract thermal, job, spool data              │
│ - Maintain printer state                        │
└─────────────────┬───────────────────────────────┘
                  │ Dict[printer_id, PrinterTelemetry]
                  ↓
┌─────────────────────────────────────────────────┐
│ Fleet Aggregation Service                       │
│ - Compute KPIs                                  │
│ - Detect anomalies                              │
│ - Generate health scores                        │
└─────────────────┬───────────────────────────────┘
                  │ FleetAggregates
                  ↓
┌─────────────────────────────────────────────────┐
│ Streamlit Dashboard (UI)                        │
│ - Render metrics, charts, tables                │
│ - Display control interface                     │
│ - Auto-refresh every N seconds                  │
└─────────────────────────────────────────────────┘
```

---

## Performance Considerations

### Scalability (100+ Printers)

1. **Message Rate Limiting**
   - Bambu sends ~1 report per 5 seconds per printer
   - 100 printers = ~20 messages/sec (manageable)

2. **Memory Management**
   - Telemetry queue maxlen=1000 (last 1000 messages)
   - Printer dict: O(n) where n = number of printers
   - Command history: Last 1000 commands only

3. **Update Interval**
   - Default: 2 seconds (adjustable in sidebar)
   - Streamlit reruns on each interval
   - Avoid <1s to prevent UI lag

4. **Optional Optimizations**
   - Use PostgreSQL instead of in-memory storage
   - Implement Redis caching for aggregates
   - Deploy Streamlit Cloud with load balancing
   - Batch database writes (100+ records per commit)

---

## Extending the Dashboard

### Add a Custom Metric

1. **Compute in Fleet Service:**
```python
def compute_custom_metric(self, printers: Dict[str, PrinterTelemetry]) -> dict:
    # Your logic here
    return results
```

2. **Display in Dashboard:**
```python
metric_data = st.session_state.fleet_service.compute_custom_metric(printers)
st.metric("Custom Metric", metric_data['value'])
```

### Add a New Control Command

1. **Implement in Control Service:**
```python
def my_new_command(self, printer_id: str, printer: PrinterTelemetry) -> Tuple[bool, str]:
    # Validation
    # Execute via MQTT
    return success, message
```

2. **Add UI Button:**
```python
if st.button("🎯 My Command", use_container_width=True):
    success, msg = st.session_state.control_service.my_new_command(printer_name, selected_printer)
    if success:
        st.success(msg)
    else:
        st.error(msg)
```

### Subscribe to Custom Telemetry

```python
def my_callback(device_id, payload):
    print(f"Custom data from {device_id}: {payload}")

mqtt_service.register_callback("my_listener", my_callback)
```

---

## Troubleshooting

### MQTT Connection Fails
- Verify email/password are correct
- Check if Bambu account has active printers
- Ensure printers are connected to Bambu Cloud (not just local WiFi)
- Check firewall/proxy settings

### No Printers Detected
- Give it 5-10 seconds after connecting (initial message delivery)
- Check Bambu web console to confirm printers are online
- Verify all printers use the same Bambu account

### Telemetry Data Missing
- Some fields (chamber temp, AMS data) only populate if hardware supports
- Job data only appears during active prints
- Inventory data requires AMS filament system

### Dashboard Slow/Laggy
- Increase update interval (sidebar slider)
- Check CPU usage on the Streamlit process
- Consider deploying on a more powerful machine
- Reduce number of concurrent tabs open

---

## Security Notes

⚠️ **Never commit `.env` to version control**

The `.env` file contains your Bambu account credentials. Treat it as sensitive:
```bash
# Add to .gitignore
echo ".env" >> .gitignore
```

---

## Next Steps

1. **Database Persistence**: Add PostgreSQL for historical data
2. **Alerting**: Integrate with Slack/Discord for critical alerts
3. **Multi-Account**: Support multiple Bambu accounts in parallel
4. **Mobile App**: Extend to React Native or Flutter
5. **Predictive Analytics**: ML-based anomaly detection and ETA prediction
6. **Integration**: Connect to Slicer4RTN, OctoPrint, or other orchestration tools

---

## Support & Debugging

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Check MQTT logs:
```bash
tail -f nemo_fleet.log
```

Monitor network traffic:
```bash
# Monitor MQTT messages in real-time
mosquitto_sub -h us.mqtt.bambulab.com -p 8883 -u your_email -P your_password --cafile mosquitto.pem -t "device/+/report"
```

---

**Version**: 1.0  
**Last Updated**: 2024  
**Maintainer**: NEMO Fleet Management Team
