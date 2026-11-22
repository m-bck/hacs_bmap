"""Tests for recipes: subentry flow, action, button, intents and LLM tools."""

from __future__ import annotations

import re

import probatio
import pytest

from homeassistant.config_entries import ConfigSubentryData, SOURCE_USER
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.helpers.llm import LLM_API_ASSIST, LLMContext, ToolInput
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.buymeapie import llm as bmap_llm
from custom_components.buymeapie.const import CONF_LOGIN, CONF_PIN, CONF_RECIPE_LIST, DOMAIN
from custom_components.buymeapie.services import summarize

from .conftest import API, ITEMS, LISTS

CHANGED = re.compile(rf"{re.escape(API)}/lists/L\d/changed_items/\d+$")
ITEM_PUT = re.compile(rf"{re.escape(API)}/lists/L\d/items/.+$")
UNIQUE_PUT = re.compile(rf"{re.escape(API)}/unique_items/.+$")

LASAGNE = ConfigSubentryData(
    data={
        "name": "Lasagne",
        "aliases": "Nudelauflauf",
        "portions": 4,
        "ingredients": "500 g Hackfleisch\n2 Dosen stückige Tomaten\n250 ml Milch\nBrot\nLasagneplatten",
    },
    subentry_type="recipe",
    title="Lasagne",
    unique_id=None,
)


@pytest.fixture
def recipe_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, unique_id="testuser", title="testuser",
        data={CONF_LOGIN: "testuser", CONF_PIN: "1234"}, subentries_data=[LASAGNE],
    )


async def _setup(hass, entry, mock_api, options=None):
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock_api.clear_requests()
    mock_api.get(f"{API}/lists", json=LISTS)
    mock_api.get(CHANGED, json=[])
    mock_api.put(UNIQUE_PUT, json={})


def _mock_writes(mock_api):
    counter = {"n": 0}

    async def post(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import (
            AiohttpClientMockResponse,
        )
        counter["n"] += 1
        return AiohttpClientMockResponse(method, url, json={
            "id": f"new{counter['n']}", "title": data["title"], "amount": data["amount"],
            "is_purchased": False, "deleted": False, "group_id": 0,
            "created_at": 1700001000.0, "updated_at": 1700001000 + counter["n"],
        })

    mock_api.post(re.compile(rf"{re.escape(API)}/lists/L1/items$"), side_effect=post)
    mock_api.put(ITEM_PUT, json={**ITEMS[1], "is_purchased": False, "amount": "", "updated_at": 1700001500})


def _calls(mock_api, method):
    return [(str(c[1]), c[2]) for c in mock_api.mock_calls if c[0] == method]


# --------------------------------------------------------------- subentry flow

async def test_create_and_edit_recipe(hass: HomeAssistant, mock_api, config_entry) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, "recipe"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Chili", "portions": 2, "ingredients": "# nur Kommentar"}
    )
    assert result["errors"] == {"ingredients": "no_ingredients"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": " Chili ", "portions": 2.0, "ingredients": "500 g Rinderhack\n1 Dose Kidneybohnen"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    (subentry,) = config_entry.subentries.values()
    assert subentry.title == "Chili"
    assert subentry.data["portions"] == 2
    # the entry was reloaded and the button exists
    assert hass.states.get("button.chili_add_to_shopping_list") is not None

    # a second recipe with the same name is refused
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, "recipe"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "chili", "portions": 2, "ingredients": "Bohnen"}
    )
    assert result["errors"] == {"name": "name_exists"}

    # edit
    result = await config_entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Chili", "portions": 4, "ingredients": "1 kg Rinderhack"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.subentries[subentry.subentry_id].data["ingredients"] == "1 kg Rinderhack"


# --------------------------------------------------------------- action

async def test_add_recipe_merges(hass: HomeAssistant, mock_api, recipe_entry) -> None:
    await _setup(hass, recipe_entry, mock_api)
    _mock_writes(mock_api)
    result = await hass.services.async_call(
        DOMAIN, "add_recipe", {"recipe": "lasagne", "portions": 6, "without": "Tomaten, Zimt"},
        blocking=True, return_response=True,
    )
    assert result["recipe"] == "Lasagne"
    assert result["list"] == "Einkaufsliste"
    assert result["portions"] == 6
    assert result["added"] == [
        {"item": "Hackfleisch", "amount": "750 g"}, {"item": "Lasagneplatten", "amount": ""},
    ]
    # Milch is already open on the list (amount "2") -> not added again, amount kept
    assert result["already_on_list"] == [{"item": "Milch", "amount": "375 ml"}]
    # Brot was purchased -> un-checked instead of added twice
    assert result["reactivated"] == [{"item": "Brot", "amount": ""}]
    assert result["skipped"] == [{"item": "stückige Tomaten", "amount": "3 Dosen"}]
    assert result["unknown_exclusions"] == ["Zimt"]

    posts = [data["title"] for _, data in _calls(mock_api, "POST")]
    assert posts == ["Hackfleisch", "Lasagneplatten"]
    puts = _calls(mock_api, "PUT")
    assert (f"{API}/lists/L1/items/i2", {"is_purchased": False}) in puts
    # new titles are categorised automatically
    assert (f"{API}/unique_items/Hackfleisch", {"group_id": 5, "permanent": False, "use_count": 1}) in puts
    assert not any("/items/i1" in url for url, _ in puts)  # Milch untouched

    # running it again changes nothing on the list
    mock_api.clear_requests()
    mock_api.get(f"{API}/lists", json=LISTS)
    mock_api.get(CHANGED, json=[])
    again = await hass.services.async_call(
        DOMAIN, "add_recipe", {"recipe": "Lasagne", "without": ["Tomaten"]},
        blocking=True, return_response=True,
    )
    assert again["added"] == [] and again["reactivated"] == []
    assert _calls(mock_api, "POST") == []


async def test_add_recipe_to_configured_list(hass: HomeAssistant, mock_api, recipe_entry) -> None:
    lists = [*LISTS, {**LISTS[0], "id": "L2", "name": "Wocheneinkauf"}]
    mock_api.clear_requests()
    mock_api.get(f"{API}/bauth", json={"login": "testuser"})
    mock_api.get(f"{API}/lists", json=lists)
    mock_api.get(f"{API}/lists/L1/items", json=ITEMS)
    mock_api.get(f"{API}/lists/L2/items", json=[])
    from .conftest import UNIQUES
    mock_api.get(f"{API}/unique_items", json=UNIQUES)
    recipe_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(recipe_entry, options={CONF_RECIPE_LIST: "L2"})
    assert await hass.config_entries.async_setup(recipe_entry.entry_id)
    await hass.async_block_till_done()
    mock_api.clear_requests()
    mock_api.get(f"{API}/lists", json=lists)
    mock_api.get(CHANGED, json=[])
    mock_api.put(UNIQUE_PUT, json={})
    mock_api.post(re.compile(rf"{re.escape(API)}/lists/L2/items$"), json={
        "id": "x", "title": "Brot", "amount": "", "is_purchased": False, "deleted": False,
        "group_id": 0, "created_at": 1.0, "updated_at": 1})
    result = await hass.services.async_call(
        DOMAIN, "add_recipe", {"recipe": "Lasagne"}, blocking=True, return_response=True,
    )
    assert result["list"] == "Wocheneinkauf"
    assert all("/lists/L2/" in url for url, _ in _calls(mock_api, "POST"))


async def test_add_recipe_unknown(hass: HomeAssistant, mock_api, recipe_entry) -> None:
    await _setup(hass, recipe_entry, mock_api)
    with pytest.raises(ServiceValidationError, match="Lasagne"):
        await hass.services.async_call(DOMAIN, "add_recipe", {"recipe": "Pizza"}, blocking=True)


async def test_get_recipe(hass: HomeAssistant, mock_api, recipe_entry) -> None:
    await _setup(hass, recipe_entry, mock_api)
    result = await hass.services.async_call(
        DOMAIN, "get_recipe", {"recipe": "Nudelauflauf", "portions": 2},
        blocking=True, return_response=True,
    )
    assert result["recipe"] == "Lasagne"
    assert result["ingredients"][0] == {"item": "Hackfleisch", "amount": "250 g"}
    overview = await hass.services.async_call(
        DOMAIN, "get_recipe", {}, blocking=True, return_response=True,
    )
    assert overview == {"recipes": [{"recipe": "Lasagne", "aliases": ["Nudelauflauf"], "portions": 4}]}


# --------------------------------------------------------------- button / intents / llm

async def test_button(hass: HomeAssistant, mock_api, recipe_entry) -> None:
    await _setup(hass, recipe_entry, mock_api)
    _mock_writes(mock_api)
    state = hass.states.get("button.lasagne_add_to_shopping_list")
    assert state.attributes["portions"] == 4
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.lasagne_add_to_shopping_list"}, blocking=True
    )
    posts = [data["title"] for _, data in _calls(mock_api, "POST")]
    assert posts == ["Hackfleisch", "stückige Tomaten", "Lasagneplatten"]


async def test_intents(hass: HomeAssistant, mock_api, recipe_entry) -> None:
    assert await async_setup_component(hass, "intent", {})
    await _setup(hass, recipe_entry, mock_api)
    _mock_writes(mock_api)
    response = await intent.async_handle(
        hass, "test", "BuyMeAPieGetRecipe", {"recipe": {"value": "Lasagne"}}
    )
    assert response.speech["plain"]["speech"].startswith(
        "Für Lasagne (4 Portionen) brauchst du: 500 g Hackfleisch, 2 Dosen stückige Tomaten"
    )
    response = await intent.async_handle(
        hass, "test", "BuyMeAPieAddRecipe", {"recipe": {"value": "lasagne"}, "portions": {"value": "8"}}
    )
    assert response.speech["plain"]["speech"] == (
        "4 Zutaten für Lasagne stehen jetzt auf der Einkaufsliste, 1 stand schon drauf."
    )
    # Range lists may deliver the number as float.
    response = await intent.async_handle(
        hass, "test", "BuyMeAPieGetRecipe", {"recipe": {"value": "Lasagne"}, "portions": {"value": 2.0}}
    )
    assert response.speech["plain"]["speech"].startswith("Für Lasagne (2 Portionen)")
    response = await intent.async_handle(
        hass, "test", "BuyMeAPieGetRecipe", {"recipe": {"value": "Lasagne"}, "portions": {"value": 1}}
    )
    assert response.speech["plain"]["speech"].startswith("Für Lasagne (1 Portion) brauchst du")
    # Unknown recipe: spoken error that names the stored recipes, no exception.
    for intent_type in ("BuyMeAPieAddRecipe", "BuyMeAPieGetRecipe"):
        response = await intent.async_handle(hass, "test", intent_type, {"recipe": {"value": "Pizza"}})
        assert response.response_type == intent.IntentResponseType.ERROR
        assert "Pizza" in response.speech["plain"]["speech"]
        assert "Lasagne" in response.speech["plain"]["speech"]


async def test_llm_tools(hass: HomeAssistant, mock_api, recipe_entry) -> None:
    await _setup(hass, recipe_entry, mock_api)
    _mock_writes(mock_api)
    ctx = LLMContext(platform="test", context=Context(), language="de",
                     assistant="conversation", device_id=None)
    assert bmap_llm.async_get_tools(hass, ctx, "other_api") is None
    tools = bmap_llm.async_get_tools(hass, ctx, LLM_API_ASSIST)
    assert "Lasagne" in tools.prompt
    add, get = tools.tools
    assert add.name == "buymeapie__add_recipe" and get.annotations.read_only

    read = await get.async_call(hass, ToolInput("buymeapie__get_recipe", {"recipe": "Lasagne"}), ctx)
    assert read.data["ingredients"][1] == {"item": "stückige Tomaten", "amount": "2 Dosen"}

    # "Lasagne, aber Tomaten hab ich noch"
    done = await add.async_call(
        hass, ToolInput("buymeapie__add_recipe", {"recipe": "Lasagne", "without": ["Tomaten"]}), ctx
    )
    assert not done.error
    assert [i["item"] for i in done.data["skipped"]] == ["stückige Tomaten"]
    # unknown recipes are rejected by the parameter schema (the LLM sees the choices)
    with pytest.raises(probatio.Invalid):
        await add.async_call(hass, ToolInput("buymeapie__add_recipe", {"recipe": "Pizza"}), ctx)


async def test_no_llm_tools_without_recipes(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry, mock_api)
    ctx = LLMContext(platform="test", context=None, language="de",
                     assistant="conversation", device_id=None)
    assert bmap_llm.async_get_tools(hass, ctx, LLM_API_ASSIST) is None


def _result(added=0, already=0, skipped=(), unknown=(), name="Einkaufsliste") -> dict:
    return {
        "recipe": "Lasagne",
        "list": name,
        "added": [{"item": f"A{i}", "amount": ""} for i in range(added)],
        "reactivated": [],
        "updated": [],
        "already_on_list": [{"item": f"B{i}", "amount": ""} for i in range(already)],
        "skipped": [{"item": item, "amount": ""} for item in skipped],
        "unknown_exclusions": list(unknown),
    }


@pytest.mark.parametrize(
    ("result", "speech"),
    [
        (_result(1, 6), "1 Zutat für Lasagne steht jetzt auf der Einkaufsliste, 6 standen schon drauf."),
        (_result(3, 1), "3 Zutaten für Lasagne stehen jetzt auf der Einkaufsliste, 1 stand schon drauf."),
        (_result(2, name="Kuchen"), "2 Zutaten für Lasagne stehen jetzt auf der Liste „Kuchen“."),
        (_result(0, 5), "Alle Zutaten für Lasagne stehen schon auf der Einkaufsliste."),
        (_result(0, 0, ["Tomaten"]), "Für Lasagne musst du nichts einkaufen."),
        (
            _result(2, 0, ["stückige Tomaten"], ["Zimt"]),
            (
                "2 Zutaten für Lasagne stehen jetzt auf der Einkaufsliste, ohne stückige Tomaten."
                " Nicht im Rezept: Zimt."
            ),
        ),
    ],
)
def test_summarize(result, speech) -> None:
    assert summarize(result) == speech
