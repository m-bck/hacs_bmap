"""The Buy Me a Pie integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import BuyMeAPieApi
from .const import CONF_LOGIN, CONF_PIN, DOMAIN
from .coordinator import BuyMeAPieConfigEntry, BuyMeAPieCoordinator
from .services import async_register_services

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the recipe actions (independent of the accounts).

    Intents live in intent.py and LLM tools in llm.py; Home Assistant loads
    those platforms itself.
    """
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BuyMeAPieConfigEntry) -> bool:
    """Set up Buy Me a Pie from a config entry."""
    api = BuyMeAPieApi(
        async_get_clientsession(hass),
        entry.data[CONF_LOGIN],
        entry.data[CONF_PIN],
    )
    coordinator = BuyMeAPieCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Options and recipes (subentries) changed -> reload.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: BuyMeAPieConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BuyMeAPieConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
