from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USERNAME, DOMAIN, UPCOMING_COURSES
from .coordinator import CobaCoordinator


def _truncate(value: str | None, length: int = 255) -> str | None:
    if value is None:
        return None
    value = str(value)
    return value if len(value) <= length else value[: length - 1] + "…"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CobaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            CobaMessagesRecusSensor(coordinator, entry),
            CobaDernierMessageSensor(coordinator, entry),
            CobaDerniereNoteSensor(coordinator, entry),
            CobaProchainsCoursSensor(coordinator, entry),
            CobaDernierSuiviSensor(coordinator, entry),
        ]
    )


class CobaBaseSensor(CoordinatorEntity[CobaCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: CobaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"COBA ({entry.data[CONF_USERNAME]})",
            manufacturer="COBA / ColNET",
            model="Portail étudiant",
            configuration_url=coordinator.client.login_url,
        )

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data or {}


class CobaMessagesRecusSensor(CobaBaseSensor):
    """Number of messages in the inbox."""

    _attr_translation_key = "messages_recus"
    _attr_icon = "mdi:email-multiple"
    _attr_native_unit_of_measurement = "messages"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: CobaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_messages_recus"

    @property
    def native_value(self) -> int | None:
        messages = self._data.get("messages") or {}
        return messages.get("count")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        messages = self._data.get("messages") or {}
        return {
            "non_lus": messages.get("unread"),
            "messages": messages.get("messages"),
            "disponible": messages.get("available"),
            "source": messages.get("source_url"),
        }


class CobaDernierMessageSensor(CobaBaseSensor):
    """Most recent message (subject / sender)."""

    _attr_translation_key = "dernier_message"
    _attr_icon = "mdi:email"

    def __init__(self, coordinator: CobaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_dernier_message"

    @property
    def native_value(self) -> str | None:
        last = (self._data.get("messages") or {}).get("last")
        if not last:
            return None
        parts = [p for p in (last.get("expediteur"), last.get("objet")) if p]
        if not parts and last.get("raw"):
            parts = last["raw"]
        return _truncate(" — ".join(parts)) if parts else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return (self._data.get("messages") or {}).get("last") or {}


class CobaDerniereNoteSensor(CobaBaseSensor):
    """Most recent grade."""

    _attr_translation_key = "derniere_note"
    _attr_icon = "mdi:school"

    def __init__(self, coordinator: CobaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_derniere_note"

    @property
    def native_value(self) -> str | None:
        last = (self._data.get("notes") or {}).get("last")
        if not last:
            return None
        value = last.get("note")
        if value:
            return _truncate(value)
        if last.get("cours"):
            return _truncate(last["cours"])
        if last.get("raw"):
            return _truncate(" ".join(last["raw"]))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return (self._data.get("notes") or {}).get("last") or {}


class CobaProchainsCoursSensor(CobaBaseSensor):
    """Next upcoming courses (the next one is the state, the 5 are attributes)."""

    _attr_translation_key = "prochains_cours"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: CobaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_prochains_cours"

    @property
    def native_value(self) -> str | None:
        upcoming = (self._data.get("cours") or {}).get("next") or []
        if not upcoming:
            return None
        first = upcoming[0]
        parts = [
            p
            for p in (first.get("debut"), first.get("cours"), first.get("local"))
            if p
        ]
        if not parts and first.get("raw"):
            parts = first["raw"]
        return _truncate(" · ".join(parts)) if parts else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cours = self._data.get("cours") or {}
        return {
            "cours": (cours.get("next") or [])[:UPCOMING_COURSES],
            "disponible": cours.get("available"),
            "source": cours.get("source_url"),
        }


class CobaDernierSuiviSensor(CobaBaseSensor):
    """Most recent student follow-up / disciplinary intervention."""

    _attr_translation_key = "dernier_suivi"
    _attr_icon = "mdi:clipboard-text-clock"

    def __init__(self, coordinator: CobaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_dernier_suivi"

    @property
    def native_value(self) -> str | None:
        last = (self._data.get("suivi") or {}).get("last")
        if not last:
            return None
        parts = [
            p for p in (last.get("date"), last.get("type"), last.get("description")) if p
        ]
        if not parts and last.get("raw"):
            parts = last["raw"]
        return _truncate(" — ".join(parts)) if parts else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return (self._data.get("suivi") or {}).get("last") or {}
