from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USERNAME, DOMAIN
from .coordinator import CobaCoordinator


def _get(data: dict[str, Any], section: str, *path: str) -> Any:
    value: Any = data.get(section)
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


@dataclass(frozen=True, kw_only=True)
class CobaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSORS: tuple[CobaSensorDescription, ...] = (
    CobaSensorDescription(
        key="moyenne_eleve",
        translation_key="moyenne_eleve",
        icon="mdi:school",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _get(d, "notes", "moyenne_eleve"),
        attrs_fn=lambda d: {"cours": _get(d, "notes", "cours")},
    ),
    CobaSensorDescription(
        key="moyenne_classe",
        translation_key="moyenne_classe",
        icon="mdi:account-group",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _get(d, "notes", "moyenne_classe"),
        attrs_fn=lambda d: {"cours": _get(d, "notes", "cours")},
    ),
    CobaSensorDescription(
        key="dernier_message",
        translation_key="dernier_message",
        icon="mdi:email",
        value_fn=lambda d: (_get(d, "messages", "dernier", "sujet") or "")[:255]
        or None,
        attrs_fn=lambda d: {
            "expediteur": _get(d, "messages", "dernier", "expediteur"),
            "apercu": _get(d, "messages", "dernier", "apercu"),
            "dossier": _get(d, "messages", "dossier"),
            "messages": _get(d, "messages", "messages"),
        },
    ),
    CobaSensorDescription(
        key="date_dernier_message",
        translation_key="date_dernier_message",
        icon="mdi:calendar-clock",
        value_fn=lambda d: _get(d, "messages", "dernier", "date"),
    ),
    CobaSensorDescription(
        key="messages_non_lus",
        translation_key="messages_non_lus",
        icon="mdi:email-alert",
        native_unit_of_measurement="messages",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _get(d, "messages", "non_lus"),
        attrs_fn=lambda d: {"total_visibles": _get(d, "messages", "total")},
    ),
    CobaSensorDescription(
        key="jour_horaire",
        translation_key="jour_horaire",
        icon="mdi:calendar-today",
        value_fn=lambda d: d.get("jour"),
        attrs_fn=lambda d: {
            "libelle": f"Jour {d['jour']}" if d.get("jour") is not None else None
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CobaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CobaSensor(coordinator, entry, desc) for desc in SENSORS)


class CobaSensor(CoordinatorEntity[CobaCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: CobaSensorDescription

    def __init__(
        self,
        coordinator: CobaCoordinator,
        entry: ConfigEntry,
        description: CobaSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"COBA ({entry.data[CONF_USERNAME]})",
            manufacturer="COBA",
            model="Portail scolaire (pedNet)",
            configuration_url=coordinator.client.login_url,
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data or {})
