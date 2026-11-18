"""Number platform for Gecko."""

import logging
from typing import TYPE_CHECKING, Any

from geckolib import MAX_CHANNEL, MIN_CHANNEL
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUMBER
from .entity import GeckoEntity, GeckoEntityBase

if TYPE_CHECKING:
    from .spa_manager import GeckoSpaManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up number platform."""
    spaman: GeckoSpaManager = hass.data[DOMAIN][entry.entry_id]
    numbers: list = []
    if spaman.can_use_facade and spaman.facade is not None:
        if spaman.facade.mrsteam.is_available:
            numbers.append(
                GeckoNumber(spaman, entry, spaman.facade.mrsteam.user_runtime, None)
            )
        if spaman.facade.bainultra.is_available:
            numbers.append(
                GeckoNumber(spaman, entry, spaman.facade.bainultra.bath_runtime, None)
            )
            numbers.append(
                GeckoNumber(spaman, entry, spaman.facade.bainultra.bath_intensity, None)
            )
            numbers.append(
                GeckoNumber(
                    spaman,
                    entry,
                    spaman.facade.bainultra.drying_cycle_delay,
                    EntityCategory.CONFIG,
                )
            )
            numbers.append(
                GeckoNumber(
                    spaman,
                    entry,
                    spaman.facade.bainultra.drying_cycle_hour,
                    EntityCategory.CONFIG,
                )
            )
            numbers.append(
                GeckoNumber(
                    spaman,
                    entry,
                    spaman.facade.bainultra.drying_cycle_minute,
                    EntityCategory.CONFIG,
                )
            )

    if spaman.can_use_facade and spaman.channel_sensor is not None:
        numbers.append(GeckoChannelNumber(spaman, entry))

    async_add_entities(numbers)
    spaman.platform_loaded(NUMBER)


class GeckoNumber(GeckoEntity, NumberEntity):
    """Gecko Date class."""

    @property
    def native_value(self) -> float:
        """Return the native value of the sensor."""
        return self._automation_entity.native_value

    @property
    def native_min_value(self) -> float:
        """Get the min value."""
        return self._automation_entity.native_min_value

    @property
    def native_max_value(self) -> float:
        """Get the max value."""
        return self._automation_entity.native_max_value

    async def async_set_native_value(self, new_value: float) -> None:
        """Set the value of the number entity."""
        await self._automation_entity.async_set_native_value(new_value)

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return self._automation_entity.native_unit_of_measurement

    @property
    def native_step(self) -> float:
        """Retuurn the step size."""
        return self._automation_entity.native_step

    @property
    def mode(self) -> str:
        """Return the preferred entry mode."""
        return self._automation_entity.mode

    @property
    def device_class(self) -> str:
        """Return the device class of the sensor."""
        return ""  # self._automation_entity.device_class


class GeckoChannelNumber(GeckoEntityBase, NumberEntity):
    """
    Radio channel of the in.touch2 module.

    Changing the channel makes the module retune, so the spa may be unreachable
    for a short while afterwards.
    """

    def __init__(self, spaman: "GeckoSpaManager", config_entry: ConfigEntry) -> None:
        """Initialize the radio channel number."""
        super().__init__(
            spaman,
            config_entry,
            f"{spaman.unique_id}-RadioChannelSet",
            "Radio channel",
            spaman.spa_name,
        )
        self._entity_category = EntityCategory.CONFIG
        spaman.channel_sensor.watch(self._on_change)

    def _on_change(self, _sender: Any, _old_value: Any, _new_value: Any) -> None:
        """Notify HA of the change."""
        if self.hass is not None:
            self.async_schedule_update_ha_state(force_refresh=True)

    @property
    def native_value(self) -> float:
        """Return the current channel."""
        return self.spaman.channel_sensor.channel

    @property
    def native_min_value(self) -> float:
        """Get the lowest channel."""
        return MIN_CHANNEL

    @property
    def native_max_value(self) -> float:
        """Get the highest channel."""
        return MAX_CHANNEL

    @property
    def native_step(self) -> float:
        """Get the step size."""
        return 1

    @property
    def mode(self) -> NumberMode:
        """Return the preferred entry mode."""
        return NumberMode.BOX

    @property
    def icon(self) -> str:
        """Get icon."""
        return "mdi:radio-tower"

    async def async_set_native_value(self, value: float) -> None:
        """Change the radio channel."""
        if not await self.spaman.spa.async_set_channel(int(value)):
            msg = "The in.touch2 module did not acknowledge the channel change"
            raise HomeAssistantError(msg)
