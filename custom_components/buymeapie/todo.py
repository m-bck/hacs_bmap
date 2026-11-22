"""To-do platform for Buy Me a Pie: one to-do list entity per shopping list."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_platform
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BuyMeAPieError, BuyMeAPieItem, BuyMeAPieNotFoundError
from .categories import (
    APP_ORDER,
    category_color,
    category_name,
    order_index,
    resolve_category,
)
from .const import (
    ATTR_CATEGORY,
    ATTR_ITEM,
    CATEGORY_NAME_PREFIX,
    CONF_AUTO_CATEGORIZE,
    CONF_CATEGORY_IN_DESCRIPTION,
    CONF_SHOW_COMPLETED,
    DEFAULT_AUTO_CATEGORIZE,
    DEFAULT_CATEGORY_IN_DESCRIPTION,
    DEFAULT_SHOW_COMPLETED,
    DOMAIN,
    SERVICE_SET_CATEGORY,
    SERVICE_SUGGEST_CATEGORY,
)
from .coordinator import BuyMeAPieConfigEntry, BuyMeAPieCoordinator, ListState

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_SEPARATOR = " · "


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BuyMeAPieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the to-do entities and add new lists as they appear."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_lists() -> None:
        new = [list_id for list_id in coordinator.data if list_id not in known]
        if not new:
            return
        known.update(new)
        async_add_entities(BuyMeAPieTodoList(coordinator, list_id) for list_id in new)

    _add_new_lists()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_lists))

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_CATEGORY,
        {
            vol.Required(ATTR_ITEM): cv.string,
            vol.Required(ATTR_CATEGORY): vol.Any(vol.Coerce(int), cv.string),
        },
        "async_set_category",
    )
    platform.async_register_entity_service(
        SERVICE_SUGGEST_CATEGORY,
        {vol.Required(ATTR_ITEM): cv.string},
        "async_suggest_category",
        supports_response=SupportsResponse.ONLY,
    )


def category_overrides(entry: BuyMeAPieConfigEntry) -> dict[int, str]:
    """User defined category names from the options."""
    overrides: dict[int, str] = {}
    for key, value in entry.options.items():
        if key.startswith(CATEGORY_NAME_PREFIX) and isinstance(value, str) and value.strip():
            try:
                overrides[int(key.removeprefix(CATEGORY_NAME_PREFIX))] = value.strip()
            except ValueError:
                continue
    return overrides


class BuyMeAPieTodoList(CoordinatorEntity[BuyMeAPieCoordinator], TodoListEntity):
    """A Buy Me a Pie shopping list."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "shopping_list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, coordinator: BuyMeAPieCoordinator, list_id: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._list_id = list_id
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{list_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.unique_id}_{list_id}")},
            name=coordinator.data[list_id].info.name,
            manufacturer="Buy Me a Pie",
            model="Einkaufsliste",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://app.buymeapie.com/",
        )

    # ------------------------------------------------------------------ helpers

    @property
    def _state(self) -> ListState | None:
        return self.coordinator.data.get(self._list_id)

    def _option(self, key: str, default: Any) -> Any:
        return self.coordinator.config_entry.options.get(key, default)

    def _label(self, group_id: int) -> str:
        return category_name(group_id, category_overrides(self.coordinator.config_entry))

    def _all_labels(self) -> list[str]:
        overrides = category_overrides(self.coordinator.config_entry)
        return sorted(
            {category_name(group_id, overrides) for group_id in APP_ORDER},
            key=len,
            reverse=True,
        )

    def _description(self, item: BuyMeAPieItem) -> str | None:
        if not self._option(CONF_CATEGORY_IN_DESCRIPTION, DEFAULT_CATEGORY_IN_DESCRIPTION):
            return item.amount or None
        label = self._label(self.coordinator.group_of(item))
        return f"{item.amount}{_SEPARATOR}{label}" if item.amount else label

    def _amount_from_description(self, description: str | None) -> str:
        """Strip the category label we add to the description."""
        text = (description or "").strip()
        if not self._option(CONF_CATEGORY_IN_DESCRIPTION, DEFAULT_CATEGORY_IN_DESCRIPTION):
            return text
        for label in self._all_labels():
            if text == label:
                return ""
            if text.endswith(_SEPARATOR + label):
                return text[: -len(_SEPARATOR + label)].strip()
        return text

    def _to_todo_item(self, item: BuyMeAPieItem) -> TodoItem:
        return TodoItem(
            uid=item.id,
            summary=item.title,
            description=self._description(item),
            status=(
                TodoItemStatus.COMPLETED if item.is_purchased else TodoItemStatus.NEEDS_ACTION
            ),
        )

    def _find(self, value: str) -> BuyMeAPieItem | None:
        """Find an item of this list by id or (case-insensitive) title."""
        state = self._state
        if state is None:
            return None
        if value in state.items:
            return state.items[value]
        wanted = value.strip().casefold()
        matches = [item for item in state.items.values() if item.title.strip().casefold() == wanted]
        # Prefer the open entry if the title exists twice.
        matches.sort(key=lambda item: item.is_purchased)
        return matches[0] if matches else None

    # ------------------------------------------------------------- entity API

    @callback
    def _handle_coordinator_update(self) -> None:
        """Keep the device name in sync when a list is renamed in the app."""
        state = self._state
        if state is not None and self.device_entry is not None:
            if self.device_entry.name != state.info.name:
                dr.async_get(self.hass).async_update_device(
                    self.device_entry.id, name=state.info.name
                )
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """The entity is unavailable once the list was deleted."""
        return super().available and self._state is not None

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Open items grouped by category (app order), then purchased ones."""
        state = self._state
        if state is None:
            return None
        group_of = self.coordinator.group_of
        items = list(state.items.values())
        open_items = sorted(
            (item for item in items if not item.is_purchased),
            key=lambda item: (order_index(group_of(item)), item.title.casefold()),
        )
        result = [self._to_todo_item(item) for item in open_items]
        if self._option(CONF_SHOW_COMPLETED, DEFAULT_SHOW_COMPLETED):
            done = sorted(
                (item for item in items if item.is_purchased),
                key=lambda item: item.updated_at,
                reverse=True,
            )
            result.extend(self._to_todo_item(item) for item in done)
        return result

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """List metadata and the open items per category."""
        state = self._state
        if state is None:
            return None
        group_of = self.coordinator.group_of
        by_group: dict[int, list[str]] = {}
        for item in state.items.values():
            if not item.is_purchased:
                by_group.setdefault(group_of(item), []).append(item.title)
        categories = [
            {
                "id": group_id,
                "name": self._label(group_id),
                "color": category_color(group_id),
                "items": sorted(by_group[group_id], key=str.casefold),
            }
            for group_id in sorted(by_group, key=order_index)
        ]
        return {
            "list_id": self._list_id,
            "purchased_items": sum(1 for item in state.items.values() if item.is_purchased),
            "shared_with": state.info.shared_with,
            "categories": categories,
        }

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item.

        Like the app: an existing entry with the same name is re-activated;
        a new entry is added and its title recorded in the history with its
        category (known one, automatic suggestion, or none).
        """
        title = (item.summary or "").strip()
        if not title:
            raise ServiceValidationError("Ein Artikel braucht einen Namen")
        amount = self._amount_from_description(item.description) if item.description else None
        purchased = item.status == TodoItemStatus.COMPLETED
        coordinator = self.coordinator
        api = coordinator.api
        existing = self._find(title)
        try:
            if existing is not None:
                result = await api.async_update_item(
                    self._list_id,
                    existing.id,
                    amount=amount if amount is not None and amount != existing.amount else None,
                    is_purchased=purchased if purchased != existing.is_purchased else None,
                )
                coordinator.async_apply_item(self._list_id, result)
            else:
                result = await api.async_add_item(self._list_id, title, amount or "", purchased)
                coordinator.async_apply_item(self._list_id, result)
                await self._async_record_new_title(result.title if result else title)
        except BuyMeAPieError as err:
            raise HomeAssistantError(f"Artikel konnte nicht angelegt werden: {err}") from err
        await coordinator.async_request_refresh()

    async def _async_record_new_title(self, title: str) -> None:
        coordinator = self.coordinator
        unique = coordinator.uniques.get(title)
        if unique is not None:
            group_id = unique.group_id
        elif self._option(CONF_AUTO_CATEGORIZE, DEFAULT_AUTO_CATEGORIZE):
            suggestion = coordinator.suggest(title)
            group_id = suggestion.group_id
            _LOGGER.debug(
                "Categorised %s as %s (%s: %s)",
                title, group_id, suggestion.source, suggestion.reason,
            )
        else:
            group_id = 0
        try:
            await coordinator.async_set_category(title, group_id, count_use=True)
        except BuyMeAPieError as err:
            # The item itself was added; only the category is missing.
            _LOGGER.warning("Could not store category for %s: %s", title, err)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Rename an item, change its amount or (un)check it."""
        state = self._state
        current = state.items.get(item.uid or "") if state else None
        if current is None:
            raise ServiceValidationError(f"Artikel {item.uid} nicht gefunden")
        title = (item.summary or "").strip() or current.title
        amount = self._amount_from_description(item.description)
        purchased = item.status == TodoItemStatus.COMPLETED
        try:
            result = await self.coordinator.api.async_update_item(
                self._list_id,
                current.id,
                title=title if title != current.title else None,
                amount=amount if amount != current.amount else None,
                is_purchased=purchased if purchased != current.is_purchased else None,
            )
        except BuyMeAPieError as err:
            raise HomeAssistantError(f"Artikel konnte nicht geändert werden: {err}") from err
        self.coordinator.async_apply_item(self._list_id, result)
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items."""
        api = self.coordinator.api
        deleted: list[str] = []
        try:
            for uid in uids:
                try:
                    await api.async_delete_item(self._list_id, uid)
                except BuyMeAPieNotFoundError:
                    pass
                deleted.append(uid)
        except BuyMeAPieError as err:
            raise HomeAssistantError(f"Artikel konnte nicht gelöscht werden: {err}") from err
        finally:
            self.coordinator.async_remove_items(self._list_id, deleted)
        await self.coordinator.async_request_refresh()

    # ---------------------------------------------------------------- actions

    async def async_set_category(self, item: str, category: str | int) -> None:
        """Set the category of an item (applies to the title account wide)."""
        overrides = category_overrides(self.coordinator.config_entry)
        group_id = resolve_category(category, overrides)
        if group_id is None:
            raise ServiceValidationError(f"Unbekannte Kategorie: {category}")
        found = self._find(item)
        title = found.title if found is not None else item.strip()
        if not title:
            raise ServiceValidationError("Kein Artikel angegeben")
        try:
            await self.coordinator.async_set_category(title, group_id)
        except BuyMeAPieError as err:
            raise HomeAssistantError(f"Kategorie konnte nicht gesetzt werden: {err}") from err

    async def async_suggest_category(self, item: str) -> ServiceResponse:
        """Return the category the integration would use for a title."""
        found = self._find(item)
        title = found.title if found is not None else item.strip()
        if found is not None:
            group_id = self.coordinator.group_of(found)
            source, reason = "list", None
        else:
            suggestion = self.coordinator.suggest(title)
            group_id, source, reason = suggestion.group_id, suggestion.source, suggestion.reason
        return {
            "item": title,
            "category_id": group_id,
            "category": self._label(group_id),
            "color": category_color(group_id),
            "source": source,
            "reason": reason,
        }
