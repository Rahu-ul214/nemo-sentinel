"""
bambu_login.py — FlowState Robotics EU Cloud Authentication
===========================================================
Authenticates against Bambu Lab's European API and writes a .env file
with the bearer token, UID, and EU MQTT host.

Diagnostic Features
--------------------
* Verbose HTTP logging (request + response headers, status, body)
* Explicit error classification (401 / 403 / timeout / unexpected)
* Supports both the NEW email-code 2FA flow and the LEGACY OTP flow
"""

import getpass
import http.client as http_client
import json
import logging
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"

# ---------------------------------------------------------------------------
# Endpoints — primary API host with EU region in the payload
# (eu.api.bambulab.com has no DNS A records, so we use api.bambulab.com)
# ---------------------------------------------------------------------------
LOGIN_URL = "https://api.bambulab.com/v1/user-service/user/login"
SEND_CODE_URL = "https://api.bambulab.com/v1/user-service/user/sendemail/code"
MQTT_HOST = "eu.mqtt.bambulab.com"

# ---------------------------------------------------------------------------
# Headers — must match a modern browser / BambuStudio client fingerprint
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://bambulab.com",
    "Referer": "https://bambulab.com/",
}

REQUEST_TIMEOUT = 15  # seconds

# ---------------------------------------------------------------------------
# Logging — captures the full HTTP conversation for diagnostics
# ---------------------------------------------------------------------------
log = logging.getLogger("bambu_login")


def _enable_verbose_http():
    """Turn on wire-level HTTP logging so every header + body is visible."""
    http_client.HTTPConnection.debuglevel = 1
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    )
    requests_log = logging.getLogger("urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_response(tag: str, resp: requests.Response):
    """Pretty-print a response for diagnostic purposes."""
    print(f"\n{'─' * 60}")
    print(f"  [{tag}]  HTTP {resp.status_code}  {resp.reason}")
    print(f"  URL: {resp.url}")
    print(f"{'─' * 60}")
    try:
        body = resp.json()
        print(json.dumps(body, indent=2))
    except ValueError:
        print(resp.text[:2000])
    print("─" * 60 + "\n")


def _request_email_code(email: str) -> bool:
    """Ask Bambu's server to send a verification code to *email*."""
    payload = {"email": email, "type": "codeLogin"}
    log.info("Requesting email verification code for %s …", email)
    resp = requests.post(
        SEND_CODE_URL, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    _log_response("SEND EMAIL CODE", resp)
    return resp.status_code == 200


# ---------------------------------------------------------------------------
# Main login flow
# ---------------------------------------------------------------------------

def bambu_cloud_login():
    _enable_verbose_http()

    print("\n" + "=" * 60)
    print("  ☁️   FLOWSTATE ROBOTICS — EU CLOUD AUTHENTICATION")
    print("=" * 60)
    print(f"  Endpoint : {LOGIN_URL}")
    print(f"  MQTT Host: {MQTT_HOST}")
    print("=" * 60 + "\n")

    email = input("Enter Bambu Account Email: ")
    password = getpass.getpass("Enter Bambu Account Password: ")

    payload = {"account": email, "password": password, "region": "EU"}

    # ── Step 1: initial login attempt ────────────────────────────
    try:
        log.info("POST %s", LOGIN_URL)
        resp = requests.post(
            LOGIN_URL, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT
        )
    except requests.exceptions.Timeout:
        print("❌  Network timeout — could not reach eu.api.bambulab.com")
        return None
    except requests.exceptions.ConnectionError as exc:
        print(f"❌  Connection error: {exc}")
        return None

    _log_response("INITIAL LOGIN", resp)
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

    # ── Step 2: handle 2FA flows ─────────────────────────────────
    # --- NEW flow: server asks for an email verification code ----
    if data.get("loginType") == "verifyCode":
        print("🔐  Server requires an email verification code.")
        if not _request_email_code(email):
            print("❌  Failed to trigger verification email.")
            return None
        code = input("Enter the code sent to your email: ").strip()
        payload = {"account": email, "code": code}
        resp = requests.post(
            LOGIN_URL, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT
        )
        _log_response("VERIFY CODE LOGIN", resp)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

    # --- LEGACY flow: 401 / code 230 → classic OTP ---------------
    elif resp.status_code == 401 or data.get("code") == 230:
        print("🔐  2FA required (legacy OTP flow).")
        otp = input("Enter your 2FA / OTP code: ").strip()
        payload["verification_code"] = otp
        resp = requests.post(
            LOGIN_URL, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT
        )
        _log_response("LEGACY OTP LOGIN", resp)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

    # ── Step 3: evaluate result ──────────────────────────────────
    token = data.get("token") or data.get("accessToken")
    uid = data.get("uid")

    if resp.status_code == 403:
        print("❌  403 Forbidden — headers may still be rejected or IP is blocked.")
        return None
    if resp.status_code == 401:
        print("❌  401 Unauthorized — bad credentials or expired code.")
        return None

    if token:
        print("✅  Authentication successful!")
        return {"token": token, "uid": uid, "email": email}

    msg = data.get("message") or data.get("msg") or data.get("error") or "(no message)"
    print(f"❌  Login Failed: {msg}")
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    creds = bambu_cloud_login()
    if creds:
        token = creds["token"].replace('"', '\\"')
        uid = creds["uid"] or "UNKNOWN"
        with open(ENV_PATH, "w") as f:
            f.write(f'BAMBU_TOKEN="{token}"\n')
            f.write(f'BAMBU_UID="{uid}"\n')
            f.write(f'BAMBU_CLOUD_HOST="{MQTT_HOST}"\n')
        print(f"\n✅  .env updated at {ENV_PATH}.")
        print("⚠️   DO NOT COMMIT THIS FILE.")
    else:
        print("\n⛔  No credentials saved — see diagnostic output above.")
        sys.exit(1)
