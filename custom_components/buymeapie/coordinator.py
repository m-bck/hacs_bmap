"""Data update coordinator for Buy Me a Pie."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BuyMeAPieApi,
    BuyMeAPieAuthError,
    BuyMeAPieError,
    BuyMeAPieItem,
    BuyMeAPieList,
    BuyMeAPieNotFoundError,
)
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

type BuyMeAPieConfigEntry = ConfigEntry[BuyMeAPieCoordinator]


@dataclass(slots=True)
class ListState:
    """Current state of one shopping list."""

    info: BuyMeAPieList
    items: dict[str, BuyMeAPieItem] = field(default_factory=dict)
    # Highest updated_at seen; used for delta requests.
    last_change: int = 0

    def apply(self, item: BuyMeAPieItem) -> None:
        """Merge an item (new, changed or deleted) into the state."""
        if item.deleted:
            self.items.pop(item.id, None)
        else:
            self.items[item.id] = item
        self.last_change = max(self.last_change, item.updated_at)


class BuyMeAPieCoordinator(DataUpdateCoordinator[dict[str, ListState]]):
    """Polls lists and item changes from Buy Me a Pie.

    The first refresh of a list loads all items (the server also returns
    deleted items as tombstones, which can be several hundred KB for an old
    list). Afterwards only items changed since the last seen timestamp are
    fetched via /lists/{id}/changed_items/{ts}.
    """

    config_entry: BuyMeAPieConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BuyMeAPieConfigEntry,
        api: BuyMeAPieApi,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.api = api
        self._lists: dict[str, ListState] = {}

    async def _async_update_data(self) -> dict[str, ListState]:
        """Fetch the latest data."""
        try:
            lists = await self.api.async_get_lists()
            current_ids = {entry.id for entry in lists}
            for list_id in list(self._lists):
                if list_id not in current_ids:
                    del self._lists[list_id]
            await asyncio.gather(*(self._async_refresh_list(entry) for entry in lists))
        except BuyMeAPieAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BuyMeAPieError as err:
            raise UpdateFailed(str(err)) from err
        return dict(self._lists)

    async def _async_refresh_list(self, info: BuyMeAPieList) -> None:
        """Refresh the items of one list (full load or delta)."""
        state = self._lists.get(info.id)
        if state is None:
            try:
                items = await self.api.async_get_items(info.id)
            except BuyMeAPieNotFoundError:
                # List vanished between the two requests.
                return
            state = ListState(info=info)
            for item in items:
                state.apply(item)
            self._lists[info.id] = state
            return

        state.info = info
        # updated_at only has second resolution and the endpoint returns
        # changes strictly after the timestamp, so look one second back to not
        # miss a change made in the same second as the last one we saw.
        since = max(state.last_change - 1, 0)
        try:
            changed = await self.api.async_get_changed_items(info.id, since)
        except BuyMeAPieNotFoundError:
            self._lists.pop(info.id, None)
            return
        for item in changed:
            state.apply(item)

    def async_apply_item(self, list_id: str, item: BuyMeAPieItem | None) -> None:
        """Apply the result of a write request immediately."""
        state = self._lists.get(list_id)
        if state is None or item is None:
            return
        state.apply(item)
        self.async_set_updated_data(dict(self._lists))

    def async_remove_items(self, list_id: str, item_ids: list[str]) -> None:
        """Drop deleted items from the local state immediately."""
        state = self._lists.get(list_id)
        if state is None:
            return
        for item_id in item_ids:
            state.items.pop(item_id, None)
        self.async_set_updated_data(dict(self._lists))
