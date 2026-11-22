"""Actions for recipes (shared by the action, buttons, intents and LLM tools)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .api import BuyMeAPieError
from .const import (
    ATTR_PORTIONS,
    ATTR_RECIPE,
    ATTR_WITHOUT,
    DOMAIN,
    SERVICE_ADD_RECIPE,
    SERVICE_GET_RECIPE,
)
from .coordinator import BuyMeAPieCoordinator
from .recipes import Recipe

ATTR_TODO_LIST = "todo_list"


def _string_list(value: Any) -> list[str]:
    """Accept a list or a comma separated string."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    return [str(item).strip() for item in cv.ensure_list(value) if str(item).strip()]


ADD_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_RECIPE): cv.string,
        vol.Optional(ATTR_PORTIONS): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional(ATTR_WITHOUT): _string_list,
        vol.Optional(ATTR_TODO_LIST): cv.entity_id,
    }
)
GET_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_RECIPE): cv.string,
        vol.Optional(ATTR_PORTIONS): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)


def loaded_coordinators(hass: HomeAssistant) -> list[BuyMeAPieCoordinator]:
    """Coordinators of all loaded Buy Me a Pie accounts."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def all_recipes(hass: HomeAssistant) -> list[Recipe]:
    """All recipes of all accounts."""
    return [recipe for coordinator in loaded_coordinators(hass) for recipe in coordinator.recipes]


def resolve_todo_list(hass: HomeAssistant, entity_id: str) -> tuple[BuyMeAPieCoordinator, str]:
    """Map a to-do entity of this integration to (coordinator, list id)."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != DOMAIN or entry.config_entry_id is None:
        raise ServiceValidationError(f"{entity_id} ist keine Buy-Me-a-Pie-Liste")
    for coordinator in loaded_coordinators(hass):
        config_entry = coordinator.config_entry
        if config_entry.entry_id == entry.config_entry_id:
            prefix = f"{config_entry.unique_id}_"
            return coordinator, (entry.unique_id or "").removeprefix(prefix)
    raise ServiceValidationError(f"{entity_id} ist nicht geladen")


def find_todo_list_by_name(hass: HomeAssistant, name: str) -> str:
    """Entity id of the Buy Me a Pie list with this name (as spoken)."""
    wanted = name.strip().casefold()
    for entry in er.async_get(hass).entities.values():
        if entry.platform != DOMAIN or entry.domain != "todo":
            continue
        state = hass.states.get(entry.entity_id)
        names = {entry.name, entry.original_name, state.name if state else None}
        if wanted in {n.strip().casefold() for n in names if n}:
            return entry.entity_id
    raise ServiceValidationError(f"„{name}“ ist keine Buy-Me-a-Pie-Liste")


def resolve_recipe(
    hass: HomeAssistant, query: str, coordinator: BuyMeAPieCoordinator | None = None
) -> tuple[BuyMeAPieCoordinator, Recipe]:
    """Find a recipe by name or alias, optionally within one account."""
    candidates = [coordinator] if coordinator else loaded_coordinators(hass)
    for candidate in candidates:
        if (recipe := candidate.find_recipe(query)) is not None:
            return candidate, recipe
    known = ", ".join(r.name for c in candidates for r in c.recipes) or "keine"
    raise ServiceValidationError(f"Rezept „{query}“ nicht gefunden (gespeichert: {known})")


async def async_add_recipe(
    hass: HomeAssistant,
    query: str,
    *,
    portions: int | None = None,
    without: list[str] | None = None,
    todo_list: str | None = None,
) -> dict[str, Any]:
    """Put a recipe on a shopping list and report what happened."""
    coordinator: BuyMeAPieCoordinator | None = None
    list_id: str | None = None
    if todo_list:
        coordinator, list_id = resolve_todo_list(hass, todo_list)
    coordinator, recipe = resolve_recipe(hass, query, coordinator)
    try:
        return await coordinator.async_add_recipe(
            recipe, list_id=list_id, portions=portions, without=without
        )
    except BuyMeAPieError as err:
        raise HomeAssistantError(f"Rezept konnte nicht übernommen werden: {err}") from err


def get_recipe(hass: HomeAssistant, query: str | None, portions: int | None = None) -> dict[str, Any]:
    """Ingredients of one recipe, or the names of all recipes."""
    if not query:
        return {
            "recipes": [
                {"recipe": recipe.name, "aliases": list(recipe.aliases), "portions": recipe.portions}
                for recipe in all_recipes(hass)
            ]
        }
    coordinator, recipe = resolve_recipe(hass, query)
    return coordinator.recipe_details(recipe, portions)


def async_register_services(hass: HomeAssistant) -> None:
    """Register the recipe actions."""

    async def _add(call: ServiceCall) -> ServiceResponse:
        result = await async_add_recipe(
            hass,
            call.data[ATTR_RECIPE],
            portions=call.data.get(ATTR_PORTIONS),
            without=call.data.get(ATTR_WITHOUT),
            todo_list=call.data.get(ATTR_TODO_LIST),
        )
        return result if call.return_response else None

    async def _get(call: ServiceCall) -> ServiceResponse:
        return get_recipe(hass, call.data.get(ATTR_RECIPE), call.data.get(ATTR_PORTIONS))

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_RECIPE, _add, ADD_RECIPE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_RECIPE, _get, GET_RECIPE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def _on_list(name: str) -> str:
    """ "auf der Einkaufsliste", or "auf der Liste „Kuchen“" for other names."""
    return f"auf der {name}" if name.casefold().endswith("liste") else f"auf der Liste „{name}“"


def summarize(result: dict[str, Any]) -> str:
    """German one-sentence summary for voice responses."""
    added = len(result["added"]) + len(result["reactivated"])
    already = len(result["already_on_list"]) + len(result["updated"])
    recipe, on_list = result["recipe"], _on_list(result["list"])
    if added:
        parts = [
            (
                f"{added} {'Zutat' if added == 1 else 'Zutaten'} für {recipe} "
                f"{'steht' if added == 1 else 'stehen'} jetzt {on_list}"
            )
        ]
        if already:
            parts.append(f"{already} {'stand' if already == 1 else 'standen'} schon drauf")
    elif already:
        parts = [f"Alle Zutaten für {recipe} stehen schon {on_list}"]
    else:
        # Everything was left out: "ohne ..." would only repeat the request.
        parts = [f"Für {recipe} musst du nichts einkaufen"]
    if result["skipped"] and (added or already):
        parts.append("ohne " + ", ".join(i["item"] for i in result["skipped"]))
    text = ", ".join(parts) + "."
    if result["unknown_exclusions"]:
        text += " Nicht im Rezept: " + ", ".join(result["unknown_exclusions"]) + "."
    return text
