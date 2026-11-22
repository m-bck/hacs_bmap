"""Fixtures for Buy Me a Pie tests."""

from __future__ import annotations

import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.buymeapie.const import CONF_LOGIN, CONF_PIN, DOMAIN

API = "https://api.buymeapie.com"

LISTS = [
    {
        "id": "L1",
        "name": "Einkaufsliste",
        "items_not_purchased": 1,
        "items_purchased": 1,
        "emails": ["a@example.com", "b@example.com"],
        "type": "",
        "created_at": 1700000000.1,
        "updated_at": 1700000000,
    }
]

ITEMS = [
    {"id": "i1", "title": "Milch", "amount": "2", "is_purchased": False,
     "deleted": False, "group_id": 3, "created_at": 1700000100.0, "updated_at": 1700000100},
    {"id": "i2", "title": "Brot", "amount": "", "is_purchased": True,
     "deleted": False, "group_id": 4, "created_at": 1700000050.0, "updated_at": 1700000200},
    {"id": "i3", "title": "Rosinen", "amount": "", "is_purchased": False,
     "deleted": True, "group_id": 4, "created_at": 1700000010.0, "updated_at": 1700000300},
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    yield


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A configured account."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="testuser",
        title="testuser",
        data={CONF_LOGIN: "testuser", CONF_PIN: "1234"},
    )


@pytest.fixture
def mock_api(aioclient_mock):
    """Default read-only API responses."""
    aioclient_mock.get(f"{API}/bauth", json={"login": "testuser"})
    aioclient_mock.get(f"{API}/lists", json=LISTS)
    aioclient_mock.get(f"{API}/lists/L1/items", json=ITEMS)
    aioclient_mock.get(f"{API}/lists/L1/changed_items/1700000299", json=[])
    return aioclient_mock
