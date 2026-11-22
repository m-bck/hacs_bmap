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

CONF_AUTO_CATEGORIZE: Final = "auto_categorize"
CONF_CATEGORY_IN_DESCRIPTION: Final = "category_in_description"
DEFAULT_AUTO_CATEGORIZE: Final = True
DEFAULT_CATEGORY_IN_DESCRIPTION: Final = True

# Options key for the display name of colour group N, e.g. "category_6".
CATEGORY_NAME_PREFIX: Final = "category_"
NAMED_CATEGORIES: Final = (7, 6, 5, 4, 3, 2, 1, 0)

SERVICE_SET_CATEGORY: Final = "set_category"
SERVICE_SUGGEST_CATEGORY: Final = "suggest_category"
ATTR_ITEM: Final = "item"
ATTR_CATEGORY: Final = "category"
