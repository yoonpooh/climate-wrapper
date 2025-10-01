"""Climate Wrapper 설정 흐름"""
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_UPDATE_INTERVAL,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_HEATING_ENTITY,
    CONF_COOLING_ENTITY,
    CONF_COMMAND_COOLDOWN,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_COMMAND_COOLDOWN,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    DOMAIN,
    NAME,
)

_LOGGER = logging.getLogger(__name__)


class ClimateWrapperConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Climate Wrapper 설정 흐름 핸들러"""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """사용자 입력 단계 처리"""
        errors = {}

        if user_input is not None:
            try:
                # 최소 하나의 기기(난방 또는 냉방)는 필수
                if not user_input.get(CONF_HEATING_ENTITY) and not user_input.get(CONF_COOLING_ENTITY):
                    errors["base"] = "no_devices"
                else:
                    # 중복 확인
                    await self.async_set_unique_id(user_input[CONF_NAME])
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=user_input.get(CONF_NAME, NAME),
                        data=user_input,
                    )

            except Exception:
                _LOGGER.exception("설정 중 예상치 못한 오류 발생")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Optional(CONF_NAME, default=NAME): str,
                vol.Optional(CONF_HEATING_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_COOLING_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_TEMPERATURE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_HUMIDITY_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
                ),
                vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): vol.All(
                    vol.Coerce(float), vol.Range(min=5.0, max=25.0)
                ),
                vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): vol.All(
                    vol.Coerce(float), vol.Range(min=20.0, max=40.0)
                ),
                vol.Optional(CONF_COMMAND_COOLDOWN, default=DEFAULT_COMMAND_COOLDOWN): vol.All(
                    vol.Coerce(int), vol.Range(min=30, max=600)
                ),
                vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=300)
                ),
            }),
            errors=errors,
        )
