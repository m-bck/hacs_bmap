"""One button per recipe: put its ingredients on the shopping list."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import BuyMeAPieError
from .const import DOMAIN
from .coordinator import BuyMeAPieConfigEntry, BuyMeAPieCoordinator
from .recipes import SUBENTRY_TYPE_RECIPE, Recipe

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BuyMeAPieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a button for every recipe subentry."""
    coordinator = entry.runtime_data
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_RECIPE:
            continue
        recipe = Recipe.from_data(subentry_id, subentry.data)
        async_add_entities(
            [RecipeButton(coordinator, recipe)], config_subentry_id=subentry_id
        )


class RecipeButton(ButtonEntity):
    """Puts a recipe on the configured shopping list."""

    _attr_has_entity_name = True
    _attr_translation_key = "add_recipe"

    def __init__(self, coordinator: BuyMeAPieCoordinator, recipe: Recipe) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._recipe = recipe
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_recipe_{recipe.id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.config_entry.unique_id}_recipe_{recipe.id}")},
            name=recipe.name,
            manufacturer="Buy Me a Pie",
            model="Rezept",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._attr_extra_state_attributes = {
            "portions": recipe.portions,
            "ingredients": [i.as_dict() for i in recipe.ingredients],
        }

    async def async_press(self) -> None:
        """Put the ingredients on the list."""
        try:
            result = await self._coordinator.async_add_recipe(self._recipe)
        except BuyMeAPieError as err:
            raise HomeAssistantError(f"Rezept konnte nicht übernommen werden: {err}") from err
        _LOGGER.debug("Recipe %s added: %s", self._recipe.name, result)
