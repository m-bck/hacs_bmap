"""Constants for the Buy Me a Pie integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "buymeapie"

API_BASE_URL: Final = "https://api.buymeapie.com"

CONF_LOGIN: Final = "login"
CONF_PIN: Final = "pin"

CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_SHOW_COMPLETED: Final = "show_completed"

DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 20
MAX_SCAN_INTERVAL: Final = 3600
DEFAULT_SHOW_COMPLETED: Final = True

REQUEST_TIMEOUT: Final = timedelta(seconds=30)
