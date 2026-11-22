"""The Buy Me a Pie integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BuyMeAPieApi
from .const import CONF_LOGIN, CONF_PIN
from .coordinator import BuyMeAPieConfigEntry, BuyMeAPieCoordinator

PLATFORMS: list[Platform] = [Platform.TODO]


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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BuyMeAPieConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
