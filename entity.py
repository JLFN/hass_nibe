"""Base entites for nibe."""

import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, List

from homeassistant.components.group import ATTR_ADD_ENTITIES, ATTR_OBJECT_ID
from homeassistant.components.group import DOMAIN as DOMAIN_GROUP
from homeassistant.components.group import SERVICE_SET
from homeassistant.helpers.entity import Entity

from .const import DOMAIN as DOMAIN_NIBE
from .const import (SCAN_INTERVAL, SIGNAL_PARAMETERS_UPDATED,
                    SIGNAL_STATUSES_UPDATED)

_LOGGER = logging.getLogger(__name__)

UNIT_ICON = {
    'A': 'mdi:power-plug',
    'Hz': 'mdi:update',
    'h': 'mdi:clock',
}


class NibeEntity(Entity):
    """Base class for all nibe sytem entities."""

    def __init__(self, uplink, system_id, groups, parameters=None):
        """Initialize base class."""
        super().__init__()
        self._uplink = uplink
        self._system_id = system_id
        self._groups = groups
        self._device_info = None
        self._parameters = OrderedDict()
        if parameters:
            self._parameters.update(parameters)

    def get_parameters(self, parameter_ids: List[str]):
        """Register a parameter for retrieval."""
        for parameter_id in parameter_ids:
            if parameter_id not in self._parameters:
                self._parameters[parameter_id] = None

    def get_bool(self, parameter_id):
        """Get bool parameter."""
        data = self._parameters[parameter_id]
        if data is None or data['value'] is None:
            return False
        else:
            return bool(data['value'])

    def get_float(self, parameter_id, default=None):
        """Get float parameter."""
        data = self._parameters[parameter_id]
        if data is None or data['value'] is None:
            return default
        else:
            return float(data['value'])

    def get_value(self, parameter_id, default=None):
        """Get value in display format."""
        data = self._parameters[parameter_id]
        if data is None or data['value'] is None:
            return default
        else:
            return data['value']

    def get_raw(self, parameter_id, default=None):
        """Get value in display format."""
        data = self._parameters[parameter_id]
        if data is None or data['rawValue'] is None:
            return default
        else:
            return data['rawValue']

    def get_scale(self, parameter_id):
        """Calculate scale of parameter."""
        data = self._parameters[parameter_id]
        if data is None or data['value'] is None:
            return 1.0
        else:
            return float(data['rawValue']) / float(data['value'])

    @property
    def device_info(self):
        """Return device identifier."""
        return {
            'identifiers': {(DOMAIN_NIBE, self._system_id)},
        }

    async def async_parameters_updated(self,
                                       data: Dict[str, Dict[str, Any]]):
        """Handle updated parameter."""
        changed = False
        for key, value in data.items():
            if key in self._parameters:
                value2 = dict(value)
                value2['timeout'] = (datetime.now() +
                                     timedelta(seconds=(SCAN_INTERVAL * 2)))
                _LOGGER.debug("Data changed for %s %s",
                              self.entity_id, key)
                changed = True
                self._parameters[key] = value2

        if changed:
            self.async_schedule_update_ha_state()

    async def async_statuses_updated(self, data):
        """Handle update of status."""
        pass

    async def async_added_to_hass(self):
        """Once registed add this entity to member groups."""
        self.hass.helpers.dispatcher.async_dispatcher_connect(
            SIGNAL_PARAMETERS_UPDATED, self.async_parameters_updated)

        self.hass.helpers.dispatcher.async_dispatcher_connect(
            SIGNAL_STATUSES_UPDATED, self.async_statuses_updated)

        for group in self._groups:
            _LOGGER.debug("Adding entity {} to group {}".format(
                self.entity_id,
                group))
            self.hass.async_add_job(
                self.hass.services.async_call(
                    DOMAIN_GROUP, SERVICE_SET, {
                        ATTR_OBJECT_ID: group,
                        ATTR_ADD_ENTITIES: [self.entity_id]
                    }
                )
            )

    async def async_update(self):
        """Update of entity."""
        _LOGGER.debug("Update %s", self.entity_id)

        def timedout(data):
            if data:
                timeout = data.get('timeout')
                if timeout and datetime.now() < timeout:
                    _LOGGER.debug("Skipping update for %s %s",
                                  self.entity_id, data['parameterId'])
                    return False
            return True

        async def get(parameter_id):
            self._parameters[parameter_id] = await self._uplink.get_parameter(
                self._system_id,
                parameter_id)

        await asyncio.gather(
            *[
                get(parameter_id)
                for parameter_id, data in self._parameters.items()
                if timedout(data)
            ],
        )


class NibeParameterEntity(NibeEntity):
    """Base class with common attributes for parameter entities."""

    def __init__(self,
                 uplink,
                 system_id,
                 parameter_id,
                 data=None,
                 groups=[],
                 entity_id_format=None
                 ):
        """Initialize base class for parameters."""
        super().__init__(uplink,
                         system_id,
                         groups,
                         parameters={parameter_id: data})
        self._parameter_id = parameter_id
        self._name = None
        self._unit = None
        self._icon = None
        self._value = None
        if data:
            self.parse_data()

        if entity_id_format:
            self.entity_id = entity_id_format.format(
                '{}_{}_{}'.format(
                    DOMAIN_NIBE,
                    system_id,
                    str(parameter_id)
                )
            )

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique identifier for a this parameter."""
        return "{}_{}".format(self._system_id, self._parameter_id)

    @property
    def should_poll(self):
        """Indicate that we need to poll data."""
        return True

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        data = self._parameters[self._parameter_id]
        if data:
            return {
                'designation': data['designation'],
                'parameter_id': data['parameterId'],
                'display_value': data['displayValue'],
                'raw_value': data['rawValue'],
                'display_unit': data['unit'],
            }
        else:
            return {}

    @property
    def available(self):
        """Return True if entity is available."""
        if self._value is None:
            return False
        else:
            return True

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def icon(self):
        """Return a calculated icon for this data if known."""
        return self._icon

    def parse_data(self):
        """Parse data to update internal variables."""
        data = self._parameters[self._parameter_id]
        if data:
            if self._name is None:
                self._name = data['title']
            self._icon = UNIT_ICON.get(data['unit'], None)
            self._unit = data['unit']
            self._value = data['value']
        else:
            self._value = None

    async def async_update(self):
        """Fetch new state data for the sensor."""
        await super().async_update()
        self.parse_data()
