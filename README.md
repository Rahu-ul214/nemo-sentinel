# NodeForge Sentinel

Industrial-grade 3D printer fleet management suite.

## Deployment to Streamlit Cloud
- **Main Entry Point**: `dashboard.py`
- **Python Version**: 3.11
- **Requirements**: See `requirements.txt`

## Architecture
- `main.py`: Backend orchestrator and state engine.
- `api_server.py`: FastAPI server providing the data bridge to the UI.
- `dashboard.py`: Streamlit frontend.
- `core/`: Configuration and state management.
- `services/`: Hardware and telemetry logic.
