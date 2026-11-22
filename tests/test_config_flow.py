"""Tests for the config flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.buymeapie.const import (
    CONF_AUTO_CATEGORIZE, CONF_CATEGORY_IN_DESCRIPTION, CONF_LOGIN, CONF_PIN,
    CONF_SCAN_INTERVAL, CONF_SHOW_COMPLETED, DOMAIN,
)

from .conftest import API


async def test_user_flow_success(hass: HomeAssistant, mock_api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: " TestUser ", CONF_PIN: "1234"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TestUser"
    assert result["data"] == {CONF_LOGIN: "TestUser", CONF_PIN: "1234"}
    assert result["result"].unique_id == "testuser"
    assert mock_api.mock_calls[0][1].path == "/bauth"


async def test_user_flow_invalid_auth(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/bauth", status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: "x", CONF_PIN: "0000"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/bauth", status=502)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: "x", CONF_PIN: "0000"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_aborts(hass: HomeAssistant, mock_api, config_entry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: "TESTUSER", CONF_PIN: "1234"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, mock_api, config_entry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "9999"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PIN] == "9999"


async def test_options(hass: HomeAssistant, mock_api, config_entry) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 60.0, CONF_SHOW_COMPLETED: False,
         CONF_AUTO_CATEGORIZE: True, CONF_CATEGORY_IN_DESCRIPTION: False},
    )
    assert result["step_id"] == "categories"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"category_6": " Gemüse ", "category_1": "", "category_7": "🧀 Kühlregal & Molkerei"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_SCAN_INTERVAL: 60, CONF_SHOW_COMPLETED: False,
        CONF_AUTO_CATEGORIZE: True, CONF_CATEGORY_IN_DESCRIPTION: False,
        "category_6": "Gemüse",
    }
