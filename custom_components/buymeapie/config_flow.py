"""Config flow for Buy Me a Pie."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import BuyMeAPieApi, BuyMeAPieAuthError, BuyMeAPieError
from .categories import DEFAULT_CATEGORIES
from .const import (
    CATEGORY_NAME_PREFIX,
    CONF_AUTO_CATEGORIZE,
    CONF_CATEGORY_IN_DESCRIPTION,
    CONF_LOGIN,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_COMPLETED,
    DEFAULT_AUTO_CATEGORIZE,
    DEFAULT_CATEGORY_IN_DESCRIPTION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SHOW_COMPLETED,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    NAMED_CATEGORIES,
)
from .coordinator import BuyMeAPieConfigEntry

_LOGGER = logging.getLogger(__name__)

_PIN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LOGIN): TextSelector(),
        vol.Required(CONF_PIN): _PIN_SELECTOR,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PIN): _PIN_SELECTOR})


class BuyMeAPieConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Buy Me a Pie."""

    VERSION = 1

    async def _async_validate(self, login: str, pin: str) -> dict[str, str]:
        """Try to log in; return form errors (empty on success)."""
        api = BuyMeAPieApi(async_get_clientsession(self.hass), login, pin)
        try:
            await api.async_get_account()
        except BuyMeAPieAuthError:
            return {"base": "invalid_auth"}
        except BuyMeAPieError:
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error during login")
            return {"base": "unknown"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for login and PIN."""
        errors: dict[str, str] = {}
        if user_input is not None:
            login = user_input[CONF_LOGIN].strip()
            pin = user_input[CONF_PIN].strip()
            await self.async_set_unique_id(login.casefold())
            self._abort_if_unique_id_configured()
            errors = await self._async_validate(login, pin)
            if not errors:
                return self.async_create_entry(
                    title=login, data={CONF_LOGIN: login, CONF_PIN: pin}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the PIN was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new PIN."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            pin = user_input[CONF_PIN].strip()
            errors = await self._async_validate(entry.data[CONF_LOGIN], pin)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PIN: pin}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"login": entry.data[CONF_LOGIN]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: BuyMeAPieConfigEntry,
    ) -> BuyMeAPieOptionsFlow:
        """Return the options flow."""
        return BuyMeAPieOptionsFlow()


class BuyMeAPieOptionsFlow(OptionsFlowWithReload):
    """Options: polling, display and the names of the colour groups."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._general: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """General options."""
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            self._general = user_input
            return await self.async_step_categories()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SHOW_COMPLETED, default=DEFAULT_SHOW_COMPLETED
                ): bool,
                vol.Required(
                    CONF_AUTO_CATEGORIZE, default=DEFAULT_AUTO_CATEGORIZE
                ): bool,
                vol.Required(
                    CONF_CATEGORY_IN_DESCRIPTION, default=DEFAULT_CATEGORY_IN_DESCRIPTION
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, self.config_entry.options
            ),
        )

    async def async_step_categories(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Names for the colour groups (the app itself has none)."""
        if user_input is not None:
            # Only keep names that differ from the built-in suggestion, so
            # improved defaults reach users who never changed them.
            names = {}
            for group_id in NAMED_CATEGORIES:
                key = f"{CATEGORY_NAME_PREFIX}{group_id}"
                value = (user_input.get(key) or "").strip()
                if value and value != DEFAULT_CATEGORIES[group_id].name:
                    names[key] = value
            return self.async_create_entry(data={**self._general, **names})

        schema = vol.Schema(
            {
                vol.Optional(f"{CATEGORY_NAME_PREFIX}{group_id}"): TextSelector()
                for group_id in NAMED_CATEGORIES
            }
        )
        suggested = {
            f"{CATEGORY_NAME_PREFIX}{group_id}": DEFAULT_CATEGORIES[group_id].name
            for group_id in NAMED_CATEGORIES
        }
        suggested.update(
            {k: v for k, v in self.config_entry.options.items() if k.startswith(CATEGORY_NAME_PREFIX)}
        )
        return self.async_show_form(
            step_id="categories",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
        )
