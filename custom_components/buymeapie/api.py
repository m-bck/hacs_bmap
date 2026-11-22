"""Async client for the (unofficial) Buy Me a Pie REST API.

The API is the one used by the web app at https://app.buymeapie.com.
Authentication is HTTP Basic Auth with the account login and the 4-digit PIN.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json as jsonlib
import logging
from typing import Any

import aiohttp

from .const import API_BASE_URL, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# 423 Locked means the server is busy with a sync for this account; the web app
# simply retries after one second.
_LOCKED_RETRIES = 3
_LOCKED_DELAY = 1.0


class BuyMeAPieError(Exception):
    """Base error for the Buy Me a Pie API."""


class BuyMeAPieConnectionError(BuyMeAPieError):
    """The API could not be reached or answered with an unexpected error."""


class BuyMeAPieAuthError(BuyMeAPieError):
    """Login or PIN were rejected."""


class BuyMeAPieNotFoundError(BuyMeAPieError):
    """The requested list or item does not exist (any more)."""


@dataclass(slots=True)
class BuyMeAPieItem:
    """An item (product) on a shopping list."""

    id: str
    title: str
    amount: str
    is_purchased: bool
    deleted: bool
    group_id: int
    created_at: float
    updated_at: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BuyMeAPieItem:
        """Create an item from an API response."""
        return cls(
            id=str(data["id"]),
            title=data.get("title") or "",
            amount=data.get("amount") or "",
            is_purchased=bool(data.get("is_purchased", False)),
            deleted=bool(data.get("deleted", False)),
            group_id=int(data.get("group_id") or 0),
            created_at=float(data.get("created_at") or 0),
            updated_at=int(data.get("updated_at") or 0),
        )


@dataclass(slots=True)
class BuyMeAPieList:
    """A shopping list."""

    id: str
    name: str
    items_not_purchased: int
    items_purchased: int
    shared_with: int
    type: str
    created_at: float
    updated_at: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BuyMeAPieList:
        """Create a list from an API response."""
        return cls(
            id=str(data["id"]),
            name=data.get("name") or "",
            items_not_purchased=int(data.get("items_not_purchased") or 0),
            items_purchased=int(data.get("items_purchased") or 0),
            shared_with=len(data.get("emails") or []),
            type=data.get("type") or "",
            created_at=float(data.get("created_at") or 0),
            updated_at=int(data.get("updated_at") or 0),
        )


class BuyMeAPieApi:
    """Minimal async client for the Buy Me a Pie API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        login: str,
        pin: str,
        base_url: str = API_BASE_URL,
    ) -> None:
        """Initialize the client."""
        self._session = session
        token = base64.b64encode(f"{login}:{pin}".encode()).decode("ascii")
        self._headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }
        self._base_url = base_url.rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request and return the decoded JSON body (or None)."""
        url = f"{self._base_url}{path}"
        for attempt in range(_LOCKED_RETRIES + 1):
            try:
                async with self._session.request(
                    method,
                    url,
                    json=json,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(
                        total=REQUEST_TIMEOUT.total_seconds()
                    ),
                ) as resp:
                    if resp.status == 423 and attempt < _LOCKED_RETRIES:
                        _LOGGER.debug("%s %s locked, retrying", method, path)
                        await asyncio.sleep(_LOCKED_DELAY)
                        continue
                    if resp.status in (401, 422):
                        raise BuyMeAPieAuthError(
                            f"Authentication failed ({resp.status})"
                        )
                    if resp.status == 404:
                        raise BuyMeAPieNotFoundError(f"{method} {path} not found")
                    if resp.status >= 400:
                        raise BuyMeAPieConnectionError(
                            f"{method} {path} failed with status {resp.status}"
                        )
                    text = await resp.text()
                    if not text.strip():
                        return None
                    try:
                        return jsonlib.loads(text)
                    except ValueError as err:
                        raise BuyMeAPieConnectionError(
                            f"Invalid JSON from {method} {path}"
                        ) from err
            except (aiohttp.ClientError, TimeoutError) as err:
                raise BuyMeAPieConnectionError(
                    f"Error talking to Buy Me a Pie: {err}"
                ) from err
        raise BuyMeAPieConnectionError(f"{method} {path} stayed locked")

    async def async_get_account(self) -> dict[str, Any]:
        """Validate the credentials and return the account data."""
        data = await self._request("GET", "/bauth")
        if not isinstance(data, dict):
            raise BuyMeAPieConnectionError("Unexpected account response")
        return data

    async def async_get_lists(self) -> list[BuyMeAPieList]:
        """Return all lists of the account."""
        data = await self._request("GET", "/lists")
        return [BuyMeAPieList.from_api(entry) for entry in data or []]

    async def async_get_items(self, list_id: str) -> list[BuyMeAPieItem]:
        """Return all items of a list, including deleted ones (tombstones)."""
        data = await self._request("GET", f"/lists/{list_id}/items")
        return [BuyMeAPieItem.from_api(entry) for entry in data or []]

    async def async_get_changed_items(
        self, list_id: str, since: int
    ) -> list[BuyMeAPieItem]:
        """Return items changed strictly after the given unix timestamp."""
        data = await self._request(
            "GET", f"/lists/{list_id}/changed_items/{int(since)}"
        )
        return [BuyMeAPieItem.from_api(entry) for entry in data or []]

    async def async_add_item(
        self,
        list_id: str,
        title: str,
        amount: str = "",
        is_purchased: bool = False,
    ) -> BuyMeAPieItem | None:
        """Add an item to a list."""
        data = await self._request(
            "POST",
            f"/lists/{list_id}/items",
            json={"title": title, "amount": amount, "is_purchased": is_purchased},
        )
        return BuyMeAPieItem.from_api(data) if isinstance(data, dict) else None

    async def async_update_item(
        self,
        list_id: str,
        item_id: str,
        *,
        title: str | None = None,
        amount: str | None = None,
        is_purchased: bool | None = None,
    ) -> BuyMeAPieItem | None:
        """Change fields of an item. Only the given fields are sent."""
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if amount is not None:
            payload["amount"] = amount
        if is_purchased is not None:
            payload["is_purchased"] = is_purchased
        if not payload:
            return None
        data = await self._request(
            "PUT", f"/lists/{list_id}/items/{item_id}", json=payload
        )
        return BuyMeAPieItem.from_api(data) if isinstance(data, dict) else None

    async def async_delete_item(self, list_id: str, item_id: str) -> None:
        """Delete an item from a list."""
        await self._request("DELETE", f"/lists/{list_id}/items/{item_id}")
