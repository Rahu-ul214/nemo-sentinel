import os
import logging
import requests
from pathlib import Path
from dotenv import set_key
from core.config import PROJECT_ROOT, BAMBU_TOKEN, BAMBU_REFRESH_TOKEN, BAMBU_ORG_ID

# Using the rotating logger configured in app.py or a similar one here
log = logging.getLogger("sentinel.auth")

class AuthManager:
    """
    Handles Bambu Cloud authentication, token lifecycle, and environment persistence.
    Supports automatic token refresh and corporate organization ID headers.
    """

    REFRESH_URL = "https://api.bambulab.com/v1/user-service/user/refresh"
    ENV_PATH = PROJECT_ROOT / ".env"

    def __init__(self):
        self.access_token = BAMBU_TOKEN
        self.refresh_token = BAMBU_REFRESH_TOKEN
        self.org_id = BAMBU_ORG_ID

    def get_headers(self):
        """Returns standard headers including the current bearer token and org ID."""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "BambuStudio/01.08.00.00",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.org_id:
            headers["X-Organization-ID"] = self.org_id
        return headers

    def refresh_access_token(self) -> bool:
        """
        Attempts to refresh the access token using the refresh token.
        Updates the internal state and the .env file upon success.
        """
        if not self.refresh_token:
            log.error("[AUTH] Refresh failed: No refresh token found in environment.")
            return False

        log.info("[AUTH] Attempting to refresh access token...")

        payload = {"refresh_token": self.refresh_token}
        try:
            response = requests.post(
                self.REFRESH_URL,
                json=payload,
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                new_access_token = data.get("accessToken") or data.get("token")
                new_refresh_token = data.get("refreshToken")

                if not new_access_token:
                    log.error("[AUTH] Refresh response succeeded but no token was provided.")
                    return False

                self.access_token = new_access_token
                if new_refresh_token:
                    self.refresh_token = new_refresh_token

                self._update_env()
                log.info("[AUTH] Access token successfully refreshed and persisted to .env")
                return True

            elif response.status_code == 401:
                log.error("[AUTH] Refresh token has expired or is invalid. Manual re-login required.")
                return False
            else:
                log.error(f"[AUTH] Refresh request failed with status {response.status_code}: {response.text}")
                return False

        except Exception as e:
            log.error(f"[AUTH] Critical error during token refresh: {e}")
            return False

    def _update_env(self):
        """Persists updated tokens back to the .env file."""
        try:
            set_key(str(self.ENV_PATH), "BAMBU_TOKEN", self.access_token)
            if self.refresh_token:
                set_key(str(self.ENV_PATH), "BAMBU_REFRESH_TOKEN", self.refresh_token)
            log.debug("[AUTH] .env file updated successfully.")
        except Exception as e:
            log.error(f"[AUTH] Failed to update .env file: {e}")

    def handle_401(self) -> bool:
        """
        Triggered when an API call returns 401.
        Returns True if token was refreshed and the request can be retried.
        """
        log.warning("[AUTH] 401 Unauthorized detected. Triggering automatic refresh...")
        return self.refresh_access_token()

# Singleton instance for use across the application
auth_manager = AuthManager()
