"""Tests for the to-do platform and coordinator."""

from __future__ import annotations

import re

from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.buymeapie.const import CONF_SHOW_COMPLETED

from .conftest import API, ITEMS, LISTS

ENTITY = "todo.einkaufsliste"
CHANGED = re.compile(rf"{re.escape(API)}/lists/L1/changed_items/\d+$")


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


async def test_setup_and_items(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "1"  # one open item; deleted tombstone ignored
    assert state.attributes["shared_with"] == 2
    assert state.attributes["purchased_items"] == 1
    items = await _items(hass)
    assert [(i["summary"], i["status"], i.get("description")) for i in items] == [
        ("Milch", "needs_action", "2"),
        ("Brot", "completed", None),
    ]


async def test_hide_completed(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry, {CONF_SHOW_COMPLETED: False})
    assert [i["summary"] for i in await _items(hass)] == ["Milch"]


async def test_add_new_item(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.post(f"{API}/lists/L1/items", json={
        "id": "i9", "title": "Eier", "amount": "6", "is_purchased": False,
        "deleted": False, "group_id": 7, "created_at": 1700000500.0, "updated_at": 1700000500,
    })
    await hass.services.async_call(
        TODO_DOMAIN, "add_item", {"item": "Eier", "description": "6"},
        target={"entity_id": ENTITY}, blocking=True,
    )
    post = [c for c in mock_api.mock_calls if c[0] == "POST"][0]
    assert post[2] == {"title": "Eier", "amount": "6", "is_purchased": False}
    assert hass.states.get(ENTITY).state == "2"


async def test_add_existing_purchased_item_reactivates(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.put(f"{API}/lists/L1/items/i2", json={**ITEMS[1], "is_purchased": False, "updated_at": 1700000600})
    await hass.services.async_call(
        TODO_DOMAIN, "add_item", {"item": "brot"},
        target={"entity_id": ENTITY}, blocking=True,
    )
    calls = [c for c in mock_api.mock_calls if c[0] in ("POST", "PUT")]
    assert len(calls) == 1 and calls[0][0] == "PUT"
    assert calls[0][2] == {"is_purchased": False}
    assert hass.states.get(ENTITY).state == "2"


async def test_complete_item(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.put(f"{API}/lists/L1/items/i1", json={**ITEMS[0], "is_purchased": True, "updated_at": 1700000700})
    await hass.services.async_call(
        TODO_DOMAIN, "update_item", {"item": "Milch", "status": "completed"},
        target={"entity_id": ENTITY}, blocking=True,
    )
    put = [c for c in mock_api.mock_calls if c[0] == "PUT"][0]
    assert put[2] == {"is_purchased": True}
    assert hass.states.get(ENTITY).state == "0"


async def test_rename_and_amount(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.put(f"{API}/lists/L1/items/i1", json={**ITEMS[0], "title": "Hafermilch", "amount": "3"})
    await hass.services.async_call(
        TODO_DOMAIN, "update_item",
        {"item": "Milch", "rename": "Hafermilch", "description": "3"},
        target={"entity_id": ENTITY}, blocking=True,
    )
    put = [c for c in mock_api.mock_calls if c[0] == "PUT"][0]
    assert put[2] == {"title": "Hafermilch", "amount": "3"}


async def test_delete_item(hass: HomeAssistant, mock_api, config_entry) -> None:
    await _setup(hass, config_entry)
    _reset(mock_api)
    mock_api.delete(f"{API}/lists/L1/items/i1", status=204)
    await hass.services.async_call(
        TODO_DOMAIN, "remove_item", {"item": "Milch"},
        target={"entity_id": ENTITY}, blocking=True,
    )
    assert any(c[0] == "DELETE" for c in mock_api.mock_calls)
    assert hass.states.get(ENTITY).state == "0"


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
    # since = highest seen updated_at (tombstone i3: 1700000300) - 1
    get_paths = [str(c[1]) for c in mock_api.mock_calls if c[0] == "GET"]
    assert f"{API}/lists/L1/changed_items/1700000299" in get_paths
    assert f"{API}/lists/L1/items" not in get_paths
    assert [i["summary"] for i in await _items(hass)] == ["Käse", "Brot"]
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


async def test_rename_list_updates_device(hass: HomeAssistant, mock_api, config_entry) -> None:
    from homeassistant.helpers import device_registry as dr

    await _setup(hass, config_entry)
    mock_api.clear_requests()
    mock_api.get(f"{API}/lists", json=[{**LISTS[0], "name": "Wocheneinkauf"}])
    mock_api.get(CHANGED, json=[])
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert [d.name for d in devices] == ["Wocheneinkauf"]
    assert hass.states.get(ENTITY) is not None
