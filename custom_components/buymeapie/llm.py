"""LLM tools: put recipes on the shopping list and read their ingredients."""

from __future__ import annotations

from typing import override

import probatio

from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.llm import (
    LLM_API_ASSIST,
    LLMContext,
    Tool,
    ToolAnnotations,
    ToolInput,
    ToolResult,
)

from .const import DOMAIN
from .services import all_recipes, async_add_recipe, get_recipe


def _recipe_names(hass: HomeAssistant) -> list[str]:
    names: list[str] = []
    for recipe in all_recipes(hass):
        names.extend(recipe.names())
    return names


class AddRecipeTool(Tool):
    """Put a stored recipe on the shopping list."""

    name = f"{DOMAIN}__add_recipe"
    title = "Add recipe to shopping list"
    description = (
        "Put the ingredients of a stored recipe on the Buy Me a Pie shopping list. "
        "Items already on the list are not added twice. Pass ingredients the user "
        "already has at home in 'without' (e.g. 'Lasagne, but I still have "
        "tomatoes' -> without: ['Tomaten']), using the ingredient names returned by "
        f"{DOMAIN}__get_recipe. 'portions' scales the amounts."
    )
    annotations = ToolAnnotations(destructive=False, idempotent=True, open_world=True)
    integration = DOMAIN

    def __init__(self, names: list[str]) -> None:
        """Init the tool."""
        self.parameters = probatio.Schema(
            {
                probatio.Required("recipe", description="Name of the recipe"): probatio.In(names),
                probatio.Optional(
                    "portions", description="Number of portions to shop for"
                ): probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=100)),
                probatio.Optional(
                    "without", description="Ingredients that must not be added"
                ): [str],
            }
        )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: LLMContext
    ) -> ToolResult:
        """Add the recipe."""
        args = self.parameters(tool_input.tool_args)
        try:
            result = await async_add_recipe(
                hass, args["recipe"], portions=args.get("portions"), without=args.get("without")
            )
        except HomeAssistantError as err:
            return ToolResult(data={"error": str(err)}, error=True)
        return ToolResult(data=result)


class GetRecipeTool(Tool):
    """Read the ingredients of a stored recipe."""

    name = f"{DOMAIN}__get_recipe"
    title = "Get recipe ingredients"
    description = (
        "Return the ingredients and amounts of a stored recipe, optionally scaled to a "
        "number of portions. Use it to answer questions like 'What do I need for "
        "lasagne?'. Without a recipe it lists all stored recipes."
    )
    annotations = ToolAnnotations(
        read_only=True, destructive=False, idempotent=True, open_world=False
    )
    integration = DOMAIN

    def __init__(self, names: list[str]) -> None:
        """Init the tool."""
        self.parameters = probatio.Schema(
            {
                probatio.Optional("recipe", description="Name of the recipe"): probatio.In(names),
                probatio.Optional(
                    "portions", description="Number of portions"
                ): probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=100)),
            }
        )

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: LLMContext
    ) -> ToolResult:
        """Return the ingredients."""
        args = self.parameters(tool_input.tool_args)
        try:
            return ToolResult(data=get_recipe(hass, args.get("recipe"), args.get("portions")))
        except HomeAssistantError as err:
            return ToolResult(data={"error": str(err)}, error=True)


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> LLMTools | None:
    """Offer the recipe tools when recipes are stored."""
    if api_id != LLM_API_ASSIST:
        return None
    names = _recipe_names(hass)
    if not names:
        return None
    recipes = ", ".join(recipe.name for recipe in all_recipes(hass))
    return LLMTools(
        tools=[AddRecipeTool(names), GetRecipeTool(names)],
        prompt=(
            f"Stored recipes (Buy Me a Pie): {recipes}. To shop for one of them use "
            f"{DOMAIN}__add_recipe instead of adding items one by one."
        ),
    )
