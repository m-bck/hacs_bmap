"""Tests for the API client."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.buymeapie.api import (
    BuyMeAPieApi, BuyMeAPieAuthError, BuyMeAPieConnectionError, BuyMeAPieNotFoundError,
)

from .conftest import API



async def test_locked_is_retried(hass: HomeAssistant, aioclient_mock) -> None:
    calls = {"n": 0}

    async def side_effect(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
        calls["n"] += 1
        if calls["n"] < 3:
            return AiohttpClientMockResponse(method, url, status=423)
        return AiohttpClientMockResponse(method, url, json=[])

    aioclient_mock.get(f"{API}/lists", side_effect=side_effect)
    api = BuyMeAPieApi(async_get_clientsession(hass), "u", "1234")
    with patch("custom_components.buymeapie.api._LOCKED_DELAY", 0):
        assert await api.async_get_lists() == []
    assert calls["n"] == 3


@pytest.mark.parametrize(
    ("status", "exc"),
    [(401, BuyMeAPieAuthError), (422, BuyMeAPieAuthError),
     (404, BuyMeAPieNotFoundError), (500, BuyMeAPieConnectionError)],
)
async def test_error_mapping(hass: HomeAssistant, aioclient_mock, status, exc) -> None:
    aioclient_mock.get(f"{API}/lists", status=status)
    api = BuyMeAPieApi(async_get_clientsession(hass), "u", "1234")
    with pytest.raises(exc):
        await api.async_get_lists()


async def test_umlaut_login_encodes(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/bauth", json={"login": "jörg"})
    api = BuyMeAPieApi(async_get_clientsession(hass), "jörg", "1234")
    assert (await api.async_get_account())["login"] == "jörg"
