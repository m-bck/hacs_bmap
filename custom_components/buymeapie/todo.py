"""To-do platform for Buy Me a Pie: one to-do list entity per shopping list."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BuyMeAPieError, BuyMeAPieItem, BuyMeAPieNotFoundError
from .const import CONF_SHOW_COMPLETED, DEFAULT_SHOW_COMPLETED, DOMAIN
from .coordinator import BuyMeAPieConfigEntry, BuyMeAPieCoordinator, ListState

PARALLEL_UPDATES = 0


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


def _to_todo_item(item: BuyMeAPieItem) -> TodoItem:
    return TodoItem(
        uid=item.id,
        summary=item.title,
        description=item.amount or None,
        status=(
            TodoItemStatus.COMPLETED if item.is_purchased else TodoItemStatus.NEEDS_ACTION
        ),
    )


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
    def _state(self) -> ListState | None:
        return self.coordinator.data.get(self._list_id)

    @property
    def available(self) -> bool:
        """The entity is unavailable once the list was deleted."""
        return super().available and self._state is not None

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Return the items of the list: open first, then purchased."""
        state = self._state
        if state is None:
            return None
        items = list(state.items.values())
        open_items = sorted(
            (item for item in items if not item.is_purchased),
            key=lambda item: item.created_at,
        )
        result = [_to_todo_item(item) for item in open_items]
        if self.coordinator.config_entry.options.get(
            CONF_SHOW_COMPLETED, DEFAULT_SHOW_COMPLETED
        ):
            done = sorted(
                (item for item in items if item.is_purchased),
                key=lambda item: item.updated_at,
                reverse=True,
            )
            result.extend(_to_todo_item(item) for item in done)
        return result

    @property
    def extra_state_attributes(self) -> dict[str, int | str] | None:
        """Expose some list metadata."""
        state = self._state
        if state is None:
            return None
        purchased = sum(1 for item in state.items.values() if item.is_purchased)
        return {
            "list_id": self._list_id,
            "purchased_items": purchased,
            "shared_with": state.info.shared_with,
        }

    def _find_by_title(self, title: str) -> BuyMeAPieItem | None:
        state = self._state
        if state is None:
            return None
        wanted = title.strip().casefold()
        for item in state.items.values():
            if item.title.strip().casefold() == wanted:
                return item
        return None

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item. An existing item with the same name is re-activated."""
        title = (item.summary or "").strip()
        if not title:
            raise HomeAssistantError("Ein Artikel braucht einen Namen")
        amount = item.description
        purchased = item.status == TodoItemStatus.COMPLETED
        api = self.coordinator.api
        try:
            existing = self._find_by_title(title)
            if existing is not None:
                result = await api.async_update_item(
                    self._list_id,
                    existing.id,
                    amount=amount if amount is not None and amount != existing.amount else None,
                    is_purchased=purchased if purchased != existing.is_purchased else None,
                )
            else:
                result = await api.async_add_item(
                    self._list_id, title, amount or "", purchased
                )
        except BuyMeAPieError as err:
            raise HomeAssistantError(f"Artikel konnte nicht angelegt werden: {err}") from err
        self.coordinator.async_apply_item(self._list_id, result)
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Rename an item, change its amount or (un)check it."""
        state = self._state
        current = state.items.get(item.uid or "") if state else None
        if current is None:
            raise HomeAssistantError(f"Artikel {item.uid} nicht gefunden")
        title = (item.summary or "").strip() or current.title
        amount = item.description or ""
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
