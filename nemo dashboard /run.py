#!/usr/bin/env python3
"""
NEMO Fleet Dashboard - Quick Start Script
Handles environment setup and launches Streamlit app
"""

import os
import sys
import subprocess
from pathlib import Path

def setup_env():
    """Setup environment and check dependencies"""
    print("🤖 NEMO Fleet Dashboard - Initialization")
    print("=" * 60)
    
    # Check Python version
    if sys.version_info < (3, 9):
        print("❌ Python 3.9+ required")
        sys.exit(1)
    
    print("✅ Python version OK")
    
    # Check .env file
    env_file = Path('.env')
    if not env_file.exists():
        print("\n⚠️  .env file not found. Creating template...")
        template = """# NEMO Fleet Management Dashboard
# Configure your Bambu Cloud credentials below

BAMBU_MQTT_HOST=us.mqtt.bambulab.com
BAMBU_MQTT_PORT=8883
BAMBU_MQTT_USER=your_email@example.com
BAMBU_MQTT_PASS=your_password
"""
        with open('.env', 'w') as f:
            f.write(template)
        print("📝 Created .env template - Please fill in your credentials")
        print("⚠️  Cannot proceed without valid credentials")
        sys.exit(1)
    
    print("✅ .env file found")
    
    # Load environment
    from dotenv import load_dotenv
    load_dotenv()
    
    # Validate credentials
    required_vars = ['BAMBU_MQTT_USER', 'BAMBU_MQTT_PASS']
    missing = [v for v in required_vars if not os.getenv(v)]
    
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("   Edit .env and add your Bambu credentials")
        sys.exit(1)
    
    print("✅ Credentials loaded")
    
    # Check dependencies
    print("\nChecking dependencies...")
    required_packages = ['streamlit', 'paho', 'pandas']
    
    try:
        import streamlit
        import paho.mqtt.client
        import pandas
        print("✅ All dependencies installed")
    except ImportError as e:
        print(f"❌ Missing package: {e}")
        print("\nInstall with:")
        print("  pip install -r requirements.txt")
        sys.exit(1)

def main():
    setup_env()
    
    print("\n" + "=" * 60)
    print("🚀 Launching NEMO Fleet Dashboard...")
    print("=" * 60)
    print("\n📱 Dashboard will open at: http://localhost:8501")
    print("🛑 Press Ctrl+C to stop\n")
    
    # Run Streamlit
    subprocess.run([
        sys.executable, "-m", "streamlit", "run", 
        "dashboard.py",
        "--logger.level=warning"
    ])

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Dashboard stopped")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
