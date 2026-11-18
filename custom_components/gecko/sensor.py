"""Sensor platform for Gecko."""

import dataclasses
import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any

import voluptuous as vol
from geckolib import (
    GeckoAutomationBase,
    GeckoConstants,
    GeckoErrorSensor,
    GeckoReminderType,
    GeckoScheduleDay,
    GeckoWatercareScheduleType,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SENSOR
from .entity import GeckoEntity, GeckoEntityBase
from .spa_manager import GeckoSpaManager

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD_SCHEDULE = "add_schedule"
SERVICE_MODIFY_SCHEDULE = "modify_schedule"
SERVICE_DELETE_SCHEDULE = "delete_schedule"

SCHEDULE_TYPES = ["economy", "filtration"]
SCHEDULE_DAYS = [
    "everyday",
    "weekday",
    "weekend",
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
]
SCHEDULE_SINGLE_DAYS = SCHEDULE_DAYS[3:]

ADD_SCHEDULE_SCHEMA = {
    vol.Required("type"): vol.In(SCHEDULE_TYPES),
    vol.Required("days"): vol.In(SCHEDULE_DAYS),
    vol.Optional("to_day"): vol.In(SCHEDULE_SINGLE_DAYS),
    vol.Required("start"): cv.time,
    vol.Required("stop"): cv.time,
}
MODIFY_SCHEDULE_SCHEMA = {
    vol.Required("number"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Optional("days"): vol.In(SCHEDULE_DAYS),
    vol.Optional("to_day"): vol.In(SCHEDULE_SINGLE_DAYS),
    vol.Optional("start"): cv.time,
    vol.Optional("stop"): cv.time,
}
DELETE_SCHEDULE_SCHEMA = {
    vol.Required("number"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor platform."""
    spaman: GeckoSpaManager = hass.data[DOMAIN][entry.entry_id]
    sensors: list = []
    if spaman.status_sensor is not None:
        sensors.append(
            GeckoSensor(spaman, entry, spaman.status_sensor, EntityCategory.DIAGNOSTIC)
        )
    if spaman.show_ping_sensor and spaman.ping_sensor is not None:
        sensors.append(
            GeckoSensor(spaman, entry, spaman.ping_sensor, EntityCategory.DIAGNOSTIC)
        )
    if spaman.last_data_sensor is not None:
        sensors.append(
            GeckoSensor(
                spaman, entry, spaman.last_data_sensor, EntityCategory.DIAGNOSTIC
            )
        )
    if spaman.radio_sensor is not None:
        sensors.append(
            GeckoSensor(spaman, entry, spaman.radio_sensor, EntityCategory.DIAGNOSTIC)
        )
    if spaman.channel_sensor is not None:
        sensors.append(
            GeckoSensor(spaman, entry, spaman.channel_sensor, EntityCategory.DIAGNOSTIC)
        )
    if spaman.can_use_facade and spaman.facade is not None:
        if spaman.facade.water_heater.is_available:
            sensors.append(
                GeckoCurrentTemperatureSensor(
                    spaman,
                    entry,
                    spaman.facade.water_heater.current_temperature_sensor,
                    spaman.facade.water_heater,
                )
            )
            sensors.append(
                GeckoSensor(
                    spaman, entry, spaman.facade.water_heater.target_temperature_sensor
                )
            )
            sensors.append(
                GeckoSensor(
                    spaman,
                    entry,
                    spaman.facade.water_heater.real_target_temperature_sensor,
                )
            )
        sensors.extend(
            GeckoSensor(spaman, entry, sensor) for sensor in spaman.facade.sensors
        )
        if spaman.facade.reminders_manager.is_available:
            sensors.extend(
                GeckoReminderSensor(spaman, entry, reminder.reminder_type)
                for reminder in spaman.facade.reminders_manager.reminders
            )
        if spaman.facade.water_care.is_available:
            sensors.extend(
                GeckoWatercareSchedulesSensor(spaman, entry, mode)
                for mode in range(len(GeckoConstants.WATERCARE_MODE_STRING))
            )
        sensors.append(GeckoErrorTextSensor(spaman, entry, spaman.facade.error_sensor))
        if spaman.facade.mrsteam.is_available:
            sensors.append(
                GeckoSensor(spaman, entry, spaman.facade.mrsteam.remaining_runtime)
            )
    async_add_entities(sensors)
    spaman.platform_loaded(SENSOR)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ADD_SCHEDULE,
        cv.make_entity_service_schema(ADD_SCHEDULE_SCHEMA),
        "async_add_schedule",
    )
    platform.async_register_entity_service(
        SERVICE_MODIFY_SCHEDULE,
        cv.make_entity_service_schema(MODIFY_SCHEDULE_SCHEMA),
        "async_modify_schedule",
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_SCHEDULE,
        cv.make_entity_service_schema(DELETE_SCHEDULE_SCHEMA),
        "async_delete_schedule",
    )


class GeckoSensor(GeckoEntity, SensorEntity):
    """Gecko Sensor class."""

    @property
    def native_value(self) -> Any:
        """Return the native value of the sensor."""
        return self._automation_entity.state

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return self._automation_entity.unit_of_measurement

    @property
    def device_class(self) -> str:
        """Return the device class of the sensor."""
        return self._automation_entity.device_class


class GeckoReminderSensor(GeckoEntityBase, SensorEntity):
    """Gecko reminder sensor class."""

    def __init__(
        self,
        spaman: GeckoSpaManager,
        config_entry: ConfigEntry,
        reminder_type: GeckoReminderType,
    ) -> None:
        """Initialize the reminder sensor."""
        super().__init__(
            spaman,
            config_entry,
            f"{spaman.unique_id}-{GeckoReminderType.to_string(reminder_type)}",
            f"{GeckoReminderSensor.type_to_name(reminder_type)} due",
            spaman.spa_name,
        )
        self._reminder_type = reminder_type
        self.spaman.facade.reminders_manager.watch(self._on_change)

    @property
    def native_value(self) -> datetime | None:
        """Get the sensor native value."""
        if self.spaman.facade is None:
            return None
        reminder = self.spaman.facade.reminders_manager.get_reminder(
            self._reminder_type
        )
        if reminder is None:
            return None
        today = datetime.now(tz=UTC).date()
        midnight = datetime(today.year, today.month, today.day, 0, 0, 0, 0, UTC)
        return midnight + timedelta(reminder.days)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Get native unit of measurement."""
        return None

    @property
    def device_class(self) -> str:
        """Get device class."""
        return "timestamp"

    @property
    def icon(self) -> str:
        """Get icon."""
        return "mdi:reminder"

    @staticmethod
    def type_to_name(thetype: GeckoReminderType) -> str:  # noqa: PLR0911
        """Convert type to name."""
        # This should go via strings.json at some point
        if thetype == GeckoReminderType.RINSE_FILTER:
            return "Rinse filter"
        if thetype == GeckoReminderType.CLEAN_FILTER:
            return "Clean filter"
        if thetype == GeckoReminderType.CHANGE_WATER:
            return "Change water"
        if thetype == GeckoReminderType.CHECK_SPA:
            return "Check Spa"
        if thetype == GeckoReminderType.CHANGE_OZONATOR:
            return "Change Ozonator"
        if thetype == GeckoReminderType.CHANGE_VISION_CARTRIDGE:
            return "Change Vision cartridge"
        return "Unknown"

    def _on_change(self, _sender: Any, _old_value: Any, _new_value: Any) -> None:
        """Notify HA of the change."""
        if self.hass is not None:
            self.async_schedule_update_ha_state(force_refresh=True)


class GeckoWatercareSchedulesSensor(GeckoEntityBase, SensorEntity):
    """
    The schedules of one watercare mode.

    The state is the number of schedules, and the attributes list them. The
    services add, modify and delete schedules for the mode of the targeted sensor.
    """

    DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

    def __init__(
        self,
        spaman: GeckoSpaManager,
        config_entry: ConfigEntry,
        mode: int,
    ) -> None:
        """Initialize the watercare schedules sensor."""
        self._mode = mode
        self._mode_name = GeckoConstants.WATERCARE_MODE_STRING[mode]
        super().__init__(
            spaman,
            config_entry,
            f"{spaman.unique_id}-WatercareSchedules-{mode}",
            f"Watercare schedules {self._mode_name}",
            spaman.spa_name,
        )
        self.spaman.facade.water_care.watch(self._on_change)

    @property
    def _water_care(self) -> Any:
        return self.spaman.facade.water_care

    def _describe_days(self, start_day: int, stop_day: int) -> str:
        first = self.DAY_NAMES[start_day]
        last = self.DAY_NAMES[stop_day]
        return first if first == last else f"{first}-{last}"

    @property
    def native_value(self) -> int:
        """Get the number of schedules."""
        return len(self._water_care.schedules_for_mode(self._mode))

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Get native unit of measurement."""
        return None

    @property
    def icon(self) -> str:
        """Get icon."""
        return "mdi:calendar-clock"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List the schedules."""
        return {
            "mode": self._mode_name,
            "active": self._water_care.mode == self._mode,
            "schedules": [
                {
                    "number": schedule.number,
                    "type": schedule.schedule_type.name.lower(),
                    "days": self._describe_days(schedule.start_day, schedule.stop_day),
                    "start": schedule.start_time,
                    "stop": schedule.stop_time,
                }
                for schedule in self._water_care.schedules_for_mode(self._mode)
            ],
        }

    @staticmethod
    def _days(days: str, to_day: str | None) -> tuple[int, int | None]:
        start_day = GeckoScheduleDay[days.upper()]
        if to_day is None:
            return (start_day, None)
        if start_day > GeckoScheduleDay.SATURDAY:
            msg = f"A range of days cannot start from '{days}'"
            raise ServiceValidationError(msg)
        return (start_day, GeckoScheduleDay[to_day.upper()])

    @staticmethod
    def _check_acknowledged(*, acknowledged: bool, what: str) -> None:
        if not acknowledged:
            msg = f"The spa did not acknowledge the request to {what} the schedule"
            raise HomeAssistantError(msg)

    async def async_add_schedule(
        self,
        type: str,  # noqa: A002
        days: str,
        start: time,
        stop: time,
        to_day: str | None = None,
    ) -> None:
        """Add a schedule to this watercare mode."""
        start_day, stop_day = self._days(days, to_day)
        try:
            acknowledged = await self._water_care.async_add_schedule(
                self._mode,
                GeckoWatercareScheduleType[type.upper()],
                start_day,
                start.hour,
                start.minute,
                stop.hour,
                stop.minute,
                stop_day=stop_day,
            )
        except ValueError as ex:
            raise ServiceValidationError(str(ex)) from ex
        self._check_acknowledged(acknowledged=acknowledged, what="add")

    def _find(self, number: int) -> Any:
        for schedule in self._water_care.schedules_for_mode(self._mode):
            if schedule.number == number:
                return schedule
        msg = f"{self._mode_name} has no schedule number {number}"
        raise ServiceValidationError(msg)

    async def async_modify_schedule(
        self,
        number: int,
        days: str | None = None,
        start: time | None = None,
        stop: time | None = None,
        to_day: str | None = None,
    ) -> None:
        """Change a schedule of this watercare mode, leaving unspecified parts."""
        schedule = self._find(number)
        changes: dict[str, Any] = {}
        if days is not None or to_day is not None:
            if days is None:
                msg = "'days' is needed to change the days of a schedule"
                raise ServiceValidationError(msg)
            start_day, stop_day = self._days(days, to_day)
            if stop_day is None:
                start_day, stop_day = GeckoScheduleDay.day_range(start_day)
            changes.update(start_day=start_day, stop_day=stop_day)
        if start is not None:
            changes.update(start_hour=start.hour, start_minute=start.minute)
        if stop is not None:
            changes.update(stop_hour=stop.hour, stop_minute=stop.minute)
        try:
            modified = dataclasses.replace(schedule, **changes)
        except ValueError as ex:
            raise ServiceValidationError(str(ex)) from ex
        self._check_acknowledged(
            acknowledged=await self._water_care.async_modify_schedule(modified),
            what="change",
        )

    async def async_delete_schedule(self, number: int) -> None:
        """Delete a schedule of this watercare mode."""
        schedule = self._find(number)
        self._check_acknowledged(
            acknowledged=await self._water_care.async_delete_schedule(schedule),
            what="delete",
        )

    def _on_change(self, _sender: Any, _old_value: Any, _new_value: Any) -> None:
        """Notify HA of the change."""
        if self.hass is not None:
            self.async_schedule_update_ha_state(force_refresh=True)


class GeckoErrorTextSensor(GeckoEntityBase, SensorEntity):
    """Gecko text error sensor class."""

    def __init__(
        self,
        spaman: GeckoSpaManager,
        config_entry: ConfigEntry,
        error_sensor: GeckoErrorSensor,
    ) -> None:
        """Initialize the error text sensor."""
        super().__init__(
            spaman,
            config_entry,
            f"{spaman.unique_id}-ERR",
            "Error(s)",
            spaman.spa_name,
        )
        self._error_sensor = error_sensor
        self._error_sensor.watch(self._on_change)
        self._entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Get native value."""
        if self.spaman.facade is None:
            return None
        return self._error_sensor.state

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Get unit of measurement."""
        return None

    @property
    def icon(self) -> str:
        """Get icon."""
        return "mdi:alert"

    def _on_change(self, _sender: Any, _old_value: Any, _new_value: Any) -> None:
        """Notify HA of the change."""
        if self.hass is not None:
            self.async_schedule_update_ha_state(force_refresh=True)


class GeckoCurrentTemperatureSensor(GeckoSensor):
    """Current temperature sensor."""

    def __init__(
        self,
        spaman: GeckoSpaManager,
        config_entry: ConfigEntry,
        automation_entity: GeckoAutomationBase,
        valid_entity: GeckoAutomationBase,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the current temp sensor."""
        super().__init__(spaman, config_entry, automation_entity, entity_category)
        self.valid_entity = valid_entity
        self.valid_entity.watch(self._on_change)

    def _on_change(self, _sender: Any, _old_value: Any, _new_value: Any) -> None:
        self._attr_available = self.valid_entity.is_available
        return super()._on_change(_sender, _old_value, _new_value)
