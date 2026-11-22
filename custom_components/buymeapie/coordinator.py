"""Data update coordinator for Buy Me a Pie."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    BuyMeAPieApi,
    BuyMeAPieAuthError,
    BuyMeAPieError,
    BuyMeAPieItem,
    BuyMeAPieList,
    BuyMeAPieNotFoundError,
    BuyMeAPieUniqueItem,
)
from .categories import CategoryClassifier, Suggestion
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# The history (~250 KB for an old account) changes rarely; the web app reloads
# it every 20 s, we do it far less often and patch it locally after own writes.
UNIQUE_REFRESH = timedelta(minutes=15)

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
        self.uniques: dict[str, BuyMeAPieUniqueItem] = {}
        self._uniques_loaded: datetime | None = None
        self._classifier: CategoryClassifier | None = None

    async def _async_update_data(self) -> dict[str, ListState]:
        """Fetch the latest data."""
        try:
            lists = await self.api.async_get_lists()
            current_ids = {entry.id for entry in lists}
            for list_id in list(self._lists):
                if list_id not in current_ids:
                    del self._lists[list_id]
            await asyncio.gather(*(self._async_refresh_list(entry) for entry in lists))
            await self._async_refresh_uniques()
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

    async def _async_refresh_uniques(self, force: bool = False) -> None:
        """Reload the item history (categories) if it is stale."""
        now = dt_util.utcnow()
        if (
            not force
            and self._uniques_loaded is not None
            and now - self._uniques_loaded < UNIQUE_REFRESH
        ):
            return
        uniques = await self.api.async_get_unique_items()
        self.uniques = {u.title: u for u in uniques if not u.deleted}
        self._uniques_loaded = now
        self._classifier = None

    @property
    def classifier(self) -> CategoryClassifier:
        """Classifier built from the current history."""
        if self._classifier is None:
            self._classifier = CategoryClassifier(
                (u.title, u.group_id, u.use_count) for u in self.uniques.values()
            )
        return self._classifier

    def group_of(self, item: BuyMeAPieItem) -> int:
        """Effective category of an item, like the app: history first."""
        unique = self.uniques.get(item.title)
        if unique is not None:
            return unique.group_id
        return item.group_id

    def suggest(self, title: str) -> Suggestion:
        """Suggest a category for a title."""
        return self.classifier.suggest(title.strip())

    async def async_set_category(
        self, title: str, group_id: int, *, count_use: bool = False
    ) -> None:
        """Store the category of a title in the history (like the app)."""
        unique = self.uniques.get(title)
        use_count = unique.use_count if unique else 0
        if count_use:
            use_count += 1
        await self.api.async_set_unique_item(
            title,
            group_id=group_id,
            use_count=use_count,
            permanent=unique.permanent if unique else False,
        )
        now = dt_util.utcnow().timestamp()
        self.uniques[title] = BuyMeAPieUniqueItem(
            title=title,
            group_id=group_id,
            use_count=use_count,
            permanent=unique.permanent if unique else False,
            deleted=False,
            last_use=now if count_use else (unique.last_use if unique else now),
            updated_at=int(now),
        )
        self._classifier = None
        self.async_set_updated_data(dict(self._lists))

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
