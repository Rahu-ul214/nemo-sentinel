# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
**NodeForge Sentinel v8.1** is an autonomous self-healing monitoring system for 3D print farms. It uses a camera stream and the NVIDIA Llama-3.2-Vision API to detect print failures (e.g., spaghetti, detached objects, nozzle blobs) and can autonomously trigger hardware recovery (bed sweeping) via MQTT and HTTP.

## Common Commands
- **Run Sentinel Service:** `python main.py`
- **Test Vision Pipeline:** `python Test_eyes.py`
- **Install Dependencies:** `pip install opencv-python requests paho-mqtt`

## Strict Architectural Constraints
- **Networking:** NEVER convert the existing synchronous `paho-mqtt` network logic into `asyncio` loops.
- **Concurrency:** All multi-threaded state management must explicitly respect and preserve the `STATUS.lock` criteria to avoid memory race conditions.
- **Decoupling:** Hardware routines (e.g., ESP32 HTTP calls) must remain decoupled from core network telemetry.

## Architecture & Structure
The system operates as a multi-threaded state machine:

### Core Components (`main.py`)
- **State Machine:** Manages transitions between `IDLE` $\rightarrow$ `MONITORING` $\rightarrow$ `STARING_OBSERVATION` (Phase 2 verification) $\rightarrow$ `RECOVERY_SWEEPING` $\rightarrow$ `EMERGENCY_LOCKDOWN`.
- **Vision Pipeline:** 
  - Captures frames via RTSPS.
  - Pre-processes images (CLAHE, denoising).
  - Performs a two-phase verification to eliminate false positives (Baseline $\rightarrow$ Delay $\rightarrow$ Validation).
  - Uses NVIDIA API for cognitive analysis of the print bed.
- **Hardware Interface:**
  - **MQTT:** Controls the printer (Stop, Pause, Resume) and receives telemetry (layer, progress, G-code state).
  - **HTTP (ESP32):** Controls auxiliary hardware (Door open/close, Bed sweep).
- **Persistence:**
  - Logs: `sentinel_logs/sentinel.log` (text) and `sentinel_logs/sentinel.json` (structured).
  - Audits: Saves suspect/verified frames to `sentinel_logs/audit/`.
  - Metrics: Tracks failure events in `sentinel_logs/failure_events.csv`.

### Key Files
- `main.py`: The primary production engine containing the state machine, hardware bindings, and vision watchdog.
- `Test_eyes.py`: A diagnostic script to verify camera connectivity and API response.
- `sentinel_logs/`: Directory for all operational logs and visual audit trails.
