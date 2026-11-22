"""Tests for the to-do platform and coordinator."""

from __future__ import annotations

import re

import pytest

from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

from custom_components.buymeapie.const import (
    CONF_AUTO_CATEGORIZE, CONF_CATEGORY_IN_DESCRIPTION, CONF_SHOW_COMPLETED, DOMAIN,
)

from .conftest import API, ITEMS, LISTS

ENTITY = "todo.einkaufsliste"
CHANGED = re.compile(rf"{re.escape(API)}/lists/L1/changed_items/\d+$")
UNIQUE_PUT = re.compile(rf"{re.escape(API)}/unique_items/.+$")
KUEHL = "🧀 Kühlregal & Molkerei"
OBST = "🥦 Obst & Gemüse"
VORRAT = "🥫 Vorrat, Brot & Getränke"


async def _setup(hass, entry, options=None):
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _items(hass):
    resp = await hass.services.async_call(
        TODO_DOMAIN, "get_items", {}, target={"entity_id": ENTITY},
        blocking=True, return_response=True,
    )
    return resp[ENTITY]["items"]


def _reset(aioclient_mock, changed=None):
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/lists", json=LISTS)
    aioclient_mock.get(CHANGED, json=changed or [])
    aioclient_mock.put(UNIQUE_PUT, json={})


def _calls(aioclient_mock, method):
    return [(str(c[1]), c[2]) for c in aioclient_mock.mock_calls if c[0] == method]


async def _add(hass, item, description=None):
    data = {"item": item}
    if description is not None:
        data["description"] = description
    await hass.services.async_call(
        TODO_DOMAIN, "add_item", data, target={"entity_id": ENTITY}, blocking=True
    )


# ----------------------------------------------------------------- reading

async def test_setup_and_items(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    state = hass.states.get(ENTITY)
    assert state.state == "2"  # deleted tombstone ignored
    assert state.attributes["shared_with"] == 2
    assert state.attributes["purchased_items"] == 1
    # Category from the history (Milch = 7) wins over the item's own group (3);
    # open items are ordered like in the app (7 before 6).
    assert [(i["summary"], i["status"], i.get("description")) for i in await _items(hass)] == [
        ("Milch", "needs_action", f"2 · {KUEHL}"),
        ("Bananen", "needs_action", OBST),
        ("Brot", "completed", VORRAT),
    ]
    assert state.attributes["categories"] == [
        {"id": 7, "name": KUEHL, "color": "#26B0C7", "items": ["Milch"]},
        {"id": 6, "name": OBST, "color": "#75B35A", "items": ["Bananen"]},
    ]


async def test_display_options(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry, {
        CONF_SHOW_COMPLETED: False, CONF_CATEGORY_IN_DESCRIPTION: False, "category_6": "Gemüse",
    })
    assert [(i["summary"], i.get("description")) for i in await _items(hass)] == [
        ("Milch", "2"), ("Bananen", None),
    ]
    assert hass.states.get(ENTITY).attributes["categories"][1]["name"] == "Gemüse"


async def test_delta_refresh(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api, changed=[
        {**ITEMS[0], "deleted": True, "updated_at": 1700000800},
        {"id": "i5", "title": "Käse", "amount": "", "is_purchased": False,
         "deleted": False, "group_id": 2, "created_at": 1700000801.0, "updated_at": 1700000801},
    ])
    coordinator = config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    paths = [p for p, _ in _calls(mock_api, "GET")]
    assert f"{API}/lists/L1/changed_items/1700000299" in paths
    assert f"{API}/lists/L1/items" not in paths
    assert f"{API}/unique_items" not in paths  # history is cached
    assert [i["summary"] for i in await _items(hass)] == ["Bananen", "Käse", "Brot"]
    assert coordinator.data["L1"].last_change == 1700000801


async def test_new_list_appears(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    mock_api.clear_requests()
    mock_api.get(f"{API}/lists", json=[*LISTS, {**LISTS[0], "id": "L2", "name": "Baumarkt"}])
    mock_api.get(CHANGED, json=[])
    mock_api.get(f"{API}/lists/L2/items", json=[])
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("todo.baumarkt") is not None


async def test_rename_list_updates_device(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    mock_api.clear_requests()
    mock_api.get(f"{API}/lists", json=[{**LISTS[0], "name": "Wocheneinkauf"}])
    mock_api.get(CHANGED, json=[])
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert [d.name for d in devices] == ["Wocheneinkauf"]


# ----------------------------------------------------------------- writing

async def test_add_new_item_is_categorised(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.post(f"{API}/lists/L1/items", json={
        "id": "i9", "title": "Eier", "amount": "6", "is_purchased": False,
        "deleted": False, "group_id": 0, "created_at": 1700000500.0, "updated_at": 1700000500,
    })
    await _add(hass, "Eier", "6")
    assert _calls(mock_api, "POST")[0][1] == {"title": "Eier", "amount": "6", "is_purchased": False}
    assert _calls(mock_api, "PUT") == [
        (f"{API}/unique_items/Eier", {"group_id": 7, "permanent": False, "use_count": 1})
    ]
    items = await _items(hass)
    assert ("Eier", f"6 · {KUEHL}") in [(i["summary"], i.get("description")) for i in items]
    assert hass.states.get(ENTITY).state == "3"


async def test_add_item_known_in_history(hass: HomeAssistant, mock_api, config_entry) -> None:
    """A title from the history keeps its category and counts one more use."""
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.post(f"{API}/lists/L1/items", json={
        "id": "i9", "title": "Quinoa bunt", "amount": "", "is_purchased": False,
        "deleted": False, "group_id": 0, "created_at": 1700000500.0, "updated_at": 1700000500,
    })
    await _add(hass, "Quinoa bunt")
    assert _calls(mock_api, "PUT") == [
        (f"{API}/unique_items/Quinoa%20bunt", {"group_id": 4, "permanent": False, "use_count": 4})
    ]


async def test_add_item_without_auto_categorize(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry, {CONF_AUTO_CATEGORIZE: False})
    _reset(mock_api)
    mock_api.post(f"{API}/lists/L1/items", json={
        "id": "i9", "title": "Crème fraîche & Co", "amount": "", "is_purchased": False,
        "deleted": False, "group_id": 0, "created_at": 1700000500.0, "updated_at": 1700000500,
    })
    await _add(hass, "Crème fraîche & Co")
    assert _calls(mock_api, "PUT") == [
        (f"{API}/unique_items/Cr%C3%A8me%20fra%C3%AEche%20%26%20Co",
         {"group_id": 0, "permanent": False, "use_count": 1})
    ]


async def test_add_existing_purchased_item_reactivates(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.put(f"{API}/lists/L1/items/i2", json={**ITEMS[1], "is_purchased": False, "updated_at": 1700000600})
    await _add(hass, "brot")
    assert _calls(mock_api, "POST") == []
    assert _calls(mock_api, "PUT") == [(f"{API}/lists/L1/items/i2", {"is_purchased": False})]
    assert hass.states.get(ENTITY).state == "3"


async def test_complete_item_ignores_category_label(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.put(f"{API}/lists/L1/items/i1", json={**ITEMS[0], "is_purchased": True, "updated_at": 1700000700})
    await hass.services.async_call(
        TODO_DOMAIN, "update_item", {"item": "Milch", "status": "completed"},
        target={"entity_id": ENTITY}, blocking=True,
    )
    # The description "2 · 🧀 Kühlregal & Molkerei" must not be written back as amount.
    assert _calls(mock_api, "PUT") == [(f"{API}/lists/L1/items/i1", {"is_purchased": True})]
    assert hass.states.get(ENTITY).state == "1"


@pytest.mark.parametrize("description", ["3", f"3 · {KUEHL}"])
async def test_rename_and_amount(hass: HomeAssistant, mock_api, config_entry, description) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.put(f"{API}/lists/L1/items/i1", json={**ITEMS[0], "title": "Hafermilch", "amount": "3"})
    await hass.services.async_call(
        TODO_DOMAIN, "update_item",
        {"item": "Milch", "rename": "Hafermilch", "description": description},
        target={"entity_id": ENTITY}, blocking=True,
    )
    assert _calls(mock_api, "PUT") == [
        (f"{API}/lists/L1/items/i1", {"title": "Hafermilch", "amount": "3"})
    ]


async def test_delete_item(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.delete(f"{API}/lists/L1/items/i1", status=204)
    await hass.services.async_call(
        TODO_DOMAIN, "remove_item", {"item": "Milch"},
        target={"entity_id": ENTITY}, blocking=True,
    )
    assert _calls(mock_api, "DELETE")
    assert hass.states.get(ENTITY).state == "1"


# ----------------------------------------------------------------- actions

async def test_set_category(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    await hass.services.async_call(
        DOMAIN, "set_category", {"item": "bananen", "category": "Tiefkühl"},
        target={"entity_id": ENTITY}, blocking=True,
    )
    assert _calls(mock_api, "PUT") == [
        (f"{API}/unique_items/Bananen", {"group_id": 1, "permanent": False, "use_count": 0})
    ]
    descriptions = {i["summary"]: i.get("description") for i in await _items(hass)}
    assert descriptions["Bananen"] == "🧊 Tiefkühl"


async def test_set_category_unknown(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_category", {"item": "Bananen", "category": "Gibtsnicht"},
            target={"entity_id": ENTITY}, blocking=True,
        )


async def test_suggest_category(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)

    async def suggest(item):
        resp = await hass.services.async_call(
            DOMAIN, "suggest_category", {"item": item},
            target={"entity_id": ENTITY}, blocking=True, return_response=True,
        )
        return resp[ENTITY]

    assert await suggest("Hafermilch") == {
        "item": "Hafermilch", "category_id": 7, "category": KUEHL,
        "color": "#26B0C7", "source": "keyword", "reason": "milch",
    }
    assert (await suggest("Quinoa"))["source"] == "similar"
    assert (await suggest("milch"))["source"] == "list"


# ----------------------------------------------------------------- errors

async def test_auth_failure_starts_reauth(hass: HomeAssistant, aioclient_mock, config_entry) -> None:
    aioclient_mock.get(f"{API}/lists", status=401)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_server_error_retries_setup(hass: HomeAssistant, aioclient_mock, config_entry) -> None:
    aioclient_mock.get(f"{API}/lists", status=500)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
