"""Voice intents for recipes (default conversation agent)."""

from __future__ import annotations

import probatio

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent

from .services import async_add_recipe, get_recipe, summarize

INTENT_ADD_RECIPE = "BuyMeAPieAddRecipe"
INTENT_GET_RECIPE = "BuyMeAPieGetRecipe"


def _portions(slots: dict) -> int | None:
    value = slots.get("portions", {}).get("value")
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class AddRecipeIntent(intent.IntentHandler):
    """Put the ingredients of a stored recipe on the shopping list."""

    intent_type = INTENT_ADD_RECIPE
    description = "Puts the ingredients of a stored recipe on the shopping list"
    slot_schema = {
        probatio.Required("recipe"): intent.non_empty_string,
        probatio.Optional("portions"): probatio.Any(int, str),
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        try:
            result = await async_add_recipe(
                intent_obj.hass, slots["recipe"]["value"], portions=_portions(slots)
            )
        except HomeAssistantError as err:
            raise intent.IntentHandleError(str(err)) from err
        response = intent_obj.create_response()
        response.async_set_speech(summarize(result))
        return response


class GetRecipeIntent(intent.IntentHandler):
    """Read the ingredients of a stored recipe."""

    intent_type = INTENT_GET_RECIPE
    description = "Tells which ingredients a stored recipe needs"
    slot_schema = {
        probatio.Required("recipe"): intent.non_empty_string,
        probatio.Optional("portions"): probatio.Any(int, str),
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        try:
            details = get_recipe(intent_obj.hass, slots["recipe"]["value"], _portions(slots))
        except HomeAssistantError as err:
            raise intent.IntentHandleError(str(err)) from err
        items = ", ".join(
            f"{i['amount']} {i['item']}".strip() for i in details["ingredients"]
        )
        response = intent_obj.create_response()
        response.async_set_speech(
            f"Für {details['recipe']} ({details['portions']} Portionen) brauchst du: {items}."
        )
        return response


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register the intents (called by the intent integration)."""
    intent.async_register(hass, AddRecipeIntent())
    intent.async_register(hass, GetRecipeIntent())
