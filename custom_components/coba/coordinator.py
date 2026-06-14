from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CobaAuthError, CobaClient, CobaConnectionError
from .const import (
    CONF_DEBUG,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CobaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches and parses the COBA / ColNET portal on a schedule."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        minutes = entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
        )
        # A dedicated session keeps the portal's auth cookies isolated from the
        # rest of Home Assistant.
        session = async_create_clientsession(hass)
        self.client = CobaClient(
            session,
            url=entry.data[CONF_URL],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            debug=entry.options.get(CONF_DEBUG, False),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_data()
        except CobaAuthError as err:
            raise ConfigEntryAuthFailed("Identifiants COBA invalides") from err
        except CobaConnectionError as err:
            raise UpdateFailed(f"Impossible de joindre le portail COBA: {err}") from err
