"""Voice intents for recipes (default conversation agent)."""

from __future__ import annotations

import probatio

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent

from .services import async_add_recipe, get_recipe, summarize

INTENT_ADD_RECIPE = "BuyMeAPieAddRecipe"
INTENT_GET_RECIPE = "BuyMeAPieGetRecipe"


# Range lists can deliver the number as int, float or str, depending on the
# Home Assistant / hassil version. Coerce instead of checking the type.
_PORTIONS = probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=100))


def _portions(slots: dict) -> int | None:
    return slots.get("portions", {}).get("value")


def _error(intent_obj: intent.Intent, err: HomeAssistantError) -> intent.IntentResponse:
    """Speak the error instead of raising.

    The default agent replaces the text of an IntentHandleError with a generic
    "unexpected error", so the user would never hear e.g. which recipes exist.
    """
    response = intent_obj.create_response()
    response.async_set_error(intent.IntentResponseErrorCode.FAILED_TO_HANDLE, str(err))
    return response


class AddRecipeIntent(intent.IntentHandler):
    """Put the ingredients of a stored recipe on the shopping list."""

    intent_type = INTENT_ADD_RECIPE
    description = "Puts the ingredients of a stored recipe on the shopping list"
    slot_schema = {
        probatio.Required("recipe"): intent.non_empty_string,
        probatio.Optional("portions"): _PORTIONS,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        try:
            result = await async_add_recipe(
                intent_obj.hass, slots["recipe"]["value"], portions=_portions(slots)
            )
        except HomeAssistantError as err:
            return _error(intent_obj, err)
        response = intent_obj.create_response()
        response.async_set_speech(summarize(result))
        return response


class GetRecipeIntent(intent.IntentHandler):
    """Read the ingredients of a stored recipe."""

    intent_type = INTENT_GET_RECIPE
    description = "Tells which ingredients a stored recipe needs"
    slot_schema = {
        probatio.Required("recipe"): intent.non_empty_string,
        probatio.Optional("portions"): _PORTIONS,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        try:
            details = get_recipe(intent_obj.hass, slots["recipe"]["value"], _portions(slots))
        except HomeAssistantError as err:
            return _error(intent_obj, err)
        items = ", ".join(
            f"{i['amount']} {i['item']}".strip() for i in details["ingredients"]
        )
        response = intent_obj.create_response()
        response.async_set_speech(
            f"Für {details['recipe']} ({details['portions']} "
            f"{'Portion' if details['portions'] == 1 else 'Portionen'}) brauchst du: {items}."
        )
        return response


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register the intents (called by the intent integration)."""
    intent.async_register(hass, AddRecipeIntent())
    intent.async_register(hass, GetRecipeIntent())
