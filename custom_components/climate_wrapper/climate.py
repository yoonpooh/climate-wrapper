"""Climate Wrapper climate platform."""
from __future__ import annotations

import logging
import math
from datetime import timedelta
from typing import Any, Callable, Optional

from homeassistant.components.climate import (
    ATTR_HVAC_ACTION,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_call_later
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_COOLING_ENTITY,
    CONF_HEATING_ENTITY,
    CONF_COMMAND_COOLDOWN,
    CONF_HUMIDITY_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_COMMAND_COOLDOWN,
    DOMAIN,
    MODE_COOLING,
    MODE_HEATING,
    MODE_IDLE,
)

_LOGGER = logging.getLogger(__name__)


SENSOR_UNAVAILABLE: tuple[str | None, ...] = (
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
    None,
)

DEFAULT_TARGET: float = 22.0
DEFAULT_TARGET_LOW: float = 20.0
DEFAULT_TARGET_HIGH: float = 25.0
DEFAULT_MIN_TEMP: float = 16.0
DEFAULT_MAX_TEMP: float = 30.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Climate Wrapper 엔티티 설정"""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([ClimateWrapperEntity(coordinator, entry, hass)])


def _as_float(value: Any) -> Optional[float]:
    """값을 float로 변환"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hvac_mode_from_state(state: State | None) -> Optional[HVACMode]:
    """상태에서 HVAC 모드 추출"""
    if not state:
        return None
    try:
        return HVACMode(state.state)
    except ValueError:
        return None


class ClimateWrapperEntity(CoordinatorEntity, RestoreEntity, ClimateEntity):
    """난방기와 냉방기를 통합 제어하는 온도조절기"""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator, config_entry: ConfigEntry, hass: HomeAssistant) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._hass = hass

        self._attr_name = config_entry.data.get("name", "Climate Wrapper")
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}"

        # 온습도 상태
        self._attr_current_temperature: Optional[float] = None
        self._attr_current_humidity: Optional[float] = None

        # 목표 온도
        self._heat_target: float = DEFAULT_TARGET_LOW
        self._cool_target: float = DEFAULT_TARGET_HIGH
        self._attr_target_temperature: float = DEFAULT_TARGET
        self._attr_target_temperature_low: float = DEFAULT_TARGET_LOW
        self._attr_target_temperature_high: float = DEFAULT_TARGET_HIGH

        # HVAC 상태
        self._attr_hvac_mode: HVACMode = HVACMode.OFF
        self._attr_hvac_action: HVACAction = HVACAction.OFF

        # 온도 범위
        self._min_temp: float = DEFAULT_MIN_TEMP
        self._max_temp: float = DEFAULT_MAX_TEMP
        self._attr_target_temperature_step = 0.5
        self._attr_precision = 0.5

        # 설정 값
        self._heating_entity: Optional[str] = config_entry.data.get(CONF_HEATING_ENTITY)
        self._cooling_entity: Optional[str] = config_entry.data.get(CONF_COOLING_ENTITY)
        self._temperature_sensor: Optional[str] = config_entry.data.get(CONF_TEMPERATURE_SENSOR)
        self._humidity_sensor: Optional[str] = config_entry.data.get(CONF_HUMIDITY_SENSOR)
        self._command_cooldown = timedelta(
            seconds=config_entry.data.get(CONF_COMMAND_COOLDOWN, DEFAULT_COMMAND_COOLDOWN)
        )

        # 사용 가능한 HVAC 모드 동적 설정
        modes = [HVACMode.OFF]
        if self._heating_entity:
            modes.append(HVACMode.HEAT)
            self._last_active_mode: HVACMode = HVACMode.HEAT
        if self._cooling_entity:
            modes.append(HVACMode.COOL)
            if not self._heating_entity:
                self._last_active_mode: HVACMode = HVACMode.COOL
        self._attr_hvac_modes = modes

        # 내부 상태
        self._running_mode: str = MODE_IDLE
        self._listeners: list[Callable[[], None]] = []
        self._controlling_devices = False
        self._pending_targets: dict[str, float] = {}
        self._device_temperatures: dict[str, float] = {}
        self._last_hvac_command: dict[str, tuple[HVACMode, Any]] = {}
        self._last_temp_command: dict[str, tuple[float, Any]] = {}
        self._pending_modes: dict[str, HVACMode] = {}
        self._hvac_retry_handles: dict[str, Callable[[], None]] = {}
        self._temp_retry_handles: dict[str, Callable[[], None]] = {}

    async def async_added_to_hass(self) -> None:
        """리스너 등록 및 내부 상태 초기화"""
        await super().async_added_to_hass()

        await self._restore_from_last_state()

        # 센서 변경 리스너 등록
        sensor_entities = []
        if self._temperature_sensor:
            sensor_entities.append(self._temperature_sensor)
        if self._humidity_sensor:
            sensor_entities.append(self._humidity_sensor)

        if sensor_entities:
            self._listeners.append(
                async_track_state_change_event(
                    self._hass, sensor_entities, self._handle_sensor_change
                )
            )

        # 기기 변경 리스너 등록
        device_entities = []
        if self._heating_entity:
            device_entities.append(self._heating_entity)
        if self._cooling_entity:
            device_entities.append(self._cooling_entity)

        if device_entities:
            self._listeners.append(
                async_track_state_change_event(
                    self._hass,
                    device_entities,
                    self._handle_device_change,
                )
            )

        await self._update_measurements()
        await self._adopt_device_state(initial=True)
        await self._ensure_consistency("startup", force_apply=True)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """리스너 취소"""
        for unsubscribe in self._listeners:
            unsubscribe()
        self._listeners.clear()
        for cancel in list(self._hvac_retry_handles.values()):
            cancel()
        self._hvac_retry_handles.clear()
        for cancel in list(self._temp_retry_handles.values()):
            cancel()
        self._temp_retry_handles.clear()
        await super().async_will_remove_from_hass()

    async def _handle_sensor_change(self, event) -> None:
        """센서 변경 처리"""
        await self._update_measurements()
        await self._ensure_consistency("sensor_update")
        self.async_write_ha_state()

    async def _handle_device_change(self, event) -> None:
        """기기 변경 처리"""
        if self._controlling_devices:
            return

        entity_id = event.data.get("entity_id")
        new_state: State | None = event.data.get("new_state")

        valid_entities = []
        if self._heating_entity:
            valid_entities.append(self._heating_entity)
        if self._cooling_entity:
            valid_entities.append(self._cooling_entity)

        if entity_id not in valid_entities or not new_state:
            return

        self._adopt_target_from_device(entity_id, new_state)
        await self._adopt_device_state()
        await self._ensure_consistency("device_change")
        self.async_write_ha_state()

    async def _update_measurements(self) -> None:
        """온습도 측정값 업데이트"""
        if self._temperature_sensor:
            temp_state = self._hass.states.get(self._temperature_sensor)
            if temp_state and temp_state.state not in SENSOR_UNAVAILABLE:
                temp = _as_float(temp_state.state)
                if temp is not None:
                    self._attr_current_temperature = temp
        else:
            # 온도 센서가 없으면 기기의 current_temperature 사용
            temps = []

            if self._heating_entity:
                heating_state = self._hass.states.get(self._heating_entity)
                if heating_state:
                    heating_temp = _as_float(heating_state.attributes.get("current_temperature"))
                    if heating_temp is not None:
                        temps.append(heating_temp)

            if self._cooling_entity:
                cooling_state = self._hass.states.get(self._cooling_entity)
                if cooling_state:
                    cooling_temp = _as_float(cooling_state.attributes.get("current_temperature"))
                    if cooling_temp is not None:
                        temps.append(cooling_temp)

            if temps:
                self._attr_current_temperature = sum(temps) / len(temps)

        if self._humidity_sensor:
            humidity_state = self._hass.states.get(self._humidity_sensor)
            if humidity_state and humidity_state.state not in SENSOR_UNAVAILABLE:
                humidity = _as_float(humidity_state.state)
                if humidity is not None:
                    self._attr_current_humidity = humidity

    def _clamp_temperature(self, value: float) -> float:
        """온도를 범위 내로 제한"""
        return max(self._min_temp, min(self._max_temp, value))

    def _apply_target_limits(self) -> None:
        """목표 온도 제한 적용"""
        self._heat_target = self._clamp_temperature(self._heat_target)
        self._cool_target = self._clamp_temperature(self._cool_target)

        if self._heat_target > self._cool_target:
            if self._attr_hvac_mode == HVACMode.COOL:
                self._heat_target = self._cool_target
            elif self._attr_hvac_mode == HVACMode.HEAT:
                self._cool_target = self._heat_target
            elif self._last_active_mode == HVACMode.COOL:
                self._heat_target = self._cool_target
            else:
                self._cool_target = self._heat_target

        self._attr_target_temperature_low = self._heat_target
        self._attr_target_temperature_high = self._cool_target

        if self._attr_hvac_mode == HVACMode.HEAT:
            self._attr_target_temperature = self._heat_target
        elif self._attr_hvac_mode == HVACMode.COOL:
            self._attr_target_temperature = self._cool_target
        else:
            self._attr_target_temperature = self._clamp_temperature(self._attr_target_temperature)

    def _cancel_hvac_retry(self, entity_id: str) -> None:
        """HVAC 재시도 취소"""
        if cancel := self._hvac_retry_handles.pop(entity_id, None):
            cancel()

    def _schedule_hvac_retry(self, entity_id: str, hvac_mode: HVACMode) -> None:
        """HVAC 재시도 예약"""
        self._cancel_hvac_retry(entity_id)

        async def _retry(now) -> None:
            self._hvac_retry_handles.pop(entity_id, None)
            pending_mode = self._pending_modes.get(entity_id)
            if pending_mode != hvac_mode:
                return
            await self._ensure_hvac_mode(entity_id, hvac_mode)

        self._pending_modes[entity_id] = hvac_mode
        delay = max(5.0, min(self._command_cooldown.total_seconds(), 30.0))
        self._hvac_retry_handles[entity_id] = async_call_later(
            self._hass,
            delay,
            _retry,
        )

    def _cancel_temperature_retry(self, entity_id: str) -> None:
        """온도 재시도 취소"""
        if cancel := self._temp_retry_handles.pop(entity_id, None):
            cancel()

    def _schedule_temperature_retry(self, entity_id: str) -> None:
        """온도 재시도 예약"""
        self._cancel_temperature_retry(entity_id)

        async def _retry(now) -> None:
            self._temp_retry_handles.pop(entity_id, None)
            pending = self._pending_targets.get(entity_id)
            if pending is None:
                return
            await self._ensure_temperature(entity_id, pending)

        delay = max(5.0, min(self._command_cooldown.total_seconds(), 30.0))
        self._temp_retry_handles[entity_id] = async_call_later(
            self._hass,
            delay,
            _retry,
        )

    def _is_temporary_command_error(self, err: Exception) -> bool:
        """일시적 명령 오류인지 확인"""
        translation_key = getattr(err, "translation_key", None)
        if translation_key in {
            "command_not_supported_in_state",
            "fail_device_control",
            "unknown_error",
            "device_timeout",
        }:
            return True

        message = getattr(err, "message", None)
        if not isinstance(message, str):
            message = str(err)
        message = message.lower()
        if "command not supported" in message and "power" in message:
            return True
        if "fail device control" in message:
            return True
        if "device timeout" in message or "timeout" in message:
            return True
        return False

    def _is_power_off_error(self, err: Exception) -> bool:
        """전원 꺼짐 오류인지 확인"""
        message = getattr(err, "message", None)
        if not isinstance(message, str):
            message = str(err)
        message = message.lower()
        return "power off" in message

    async def _try_turn_on(self, entity_id: str) -> bool:
        """기기 켜기 시도"""
        state = self._hass.states.get(entity_id)
        if state is None or state.state in SENSOR_UNAVAILABLE:
            _LOGGER.debug("%s 기기를 켤 수 없음; 엔티티를 사용할 수 없음", entity_id)
            return False

        supported = state.attributes.get("supported_features", 0)
        if not supported & ClimateEntityFeature.TURN_ON:
            _LOGGER.debug("%s는 climate.turn_on을 지원하지 않음", entity_id)
            return False

        try:
            await self._hass.services.async_call(
                "climate",
                "turn_on",
                {"entity_id": entity_id},
                blocking=True,
            )
            return True
        except HomeAssistantError as err:
            if self._is_temporary_command_error(err):
                _LOGGER.debug("%s 전원 켜기 지연 (%s)", entity_id, err)
            else:
                _LOGGER.warning("%s 전원 켜기 실패 (%s)", entity_id, err)
            return False

    async def _try_turn_off(self, entity_id: str) -> bool:
        """기기 끄기 시도"""
        state = self._hass.states.get(entity_id)
        if state is None or state.state in SENSOR_UNAVAILABLE:
            _LOGGER.debug("%s 기기를 끌 수 없음; 엔티티를 사용할 수 없음", entity_id)
            return False

        supported = state.attributes.get("supported_features", 0)
        if not supported & ClimateEntityFeature.TURN_OFF:
            _LOGGER.debug("%s는 climate.turn_off를 지원하지 않음", entity_id)
            return False

        try:
            await self._hass.services.async_call(
                "climate",
                "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )
            return True
        except HomeAssistantError as err:
            if self._is_power_off_error(err):
                _LOGGER.debug("%s 이미 전원 꺼짐", entity_id)
            elif self._is_temporary_command_error(err):
                _LOGGER.debug("%s 전원 끄기 지연 (%s)", entity_id, err)
            else:
                _LOGGER.warning("%s 전원 끄기 실패 (%s)", entity_id, err)
            return False

    def _should_defer_device_temperature(self, entity_id: str, value: float) -> bool:
        """기기 온도를 지연해야 하는지 확인"""
        pending = self._pending_targets.get(entity_id)
        if pending is None:
            return False

        if math.isclose(value, pending, abs_tol=0.3):
            self._pending_targets.pop(entity_id, None)
            return False

        last_command = self._last_temp_command.get(entity_id)
        if last_command and dt_util.utcnow() - last_command[1] < self._command_cooldown:
            _LOGGER.debug(
                "%s 온도 %.1f 무시 중, %.1f 대기 중",
                entity_id,
                value,
                pending,
            )
            return True

        self._pending_targets.pop(entity_id, None)
        return False

    def _update_temperature_limits(self, heating_state: State | None, cooling_state: State | None) -> None:
        """온도 범위 업데이트"""
        # 항상 고정된 온도 범위 사용 (16-30도)
        self._min_temp = DEFAULT_MIN_TEMP
        self._max_temp = DEFAULT_MAX_TEMP
        self._apply_target_limits()

    async def _restore_from_last_state(self) -> None:
        """마지막 상태 복원"""
        last_state = await self.async_get_last_state()
        if not last_state:
            return

        action_obj: Optional[HVACAction] = None
        action = last_state.attributes.get(ATTR_HVAC_ACTION)
        if isinstance(action, str):
            try:
                action_obj = HVACAction(action)
            except ValueError:
                action_obj = None
        if action_obj:
            self._attr_hvac_action = action_obj
        else:
            self._attr_hvac_action = HVACAction.OFF

        restored_mode = _hvac_mode_from_state(last_state)
        temp = _as_float(last_state.attributes.get(ATTR_TEMPERATURE))
        low = _as_float(last_state.attributes.get(ATTR_TARGET_TEMP_LOW))
        high = _as_float(last_state.attributes.get(ATTR_TARGET_TEMP_HIGH))

        if restored_mode == HVACMode.AUTO:
            if self._attr_hvac_action == HVACAction.COOLING:
                restored_mode = HVACMode.COOL
            elif self._attr_hvac_action == HVACAction.HEATING:
                restored_mode = HVACMode.HEAT
            else:
                restored_mode = HVACMode.HEAT

        if restored_mode in (HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF):
            self._attr_hvac_mode = restored_mode
        else:
            restored_mode = self._attr_hvac_mode

        if restored_mode == HVACMode.HEAT:
            if temp is not None:
                self._heat_target = self._clamp_temperature(temp)
            elif low is not None:
                self._heat_target = self._clamp_temperature(low)
            if high is not None:
                self._cool_target = self._clamp_temperature(high)
            self._attr_target_temperature_low = self._heat_target
            self._attr_target_temperature_high = max(self._heat_target, self._cool_target)
            self._attr_target_temperature = self._heat_target
            self._running_mode = MODE_HEATING
            self._last_active_mode = HVACMode.HEAT
        elif restored_mode == HVACMode.COOL:
            if temp is not None:
                self._cool_target = self._clamp_temperature(temp)
            elif high is not None:
                self._cool_target = self._clamp_temperature(high)
            if low is not None:
                self._heat_target = self._clamp_temperature(low)
            self._attr_target_temperature_high = self._cool_target
            self._attr_target_temperature_low = min(self._cool_target, self._heat_target)
            self._attr_target_temperature = self._cool_target
            self._running_mode = MODE_COOLING
            self._last_active_mode = HVACMode.COOL
        else:
            if low is not None:
                self._heat_target = self._clamp_temperature(low)
            if high is not None:
                self._cool_target = self._clamp_temperature(high)
            if temp is not None:
                self._attr_target_temperature = self._clamp_temperature(temp)
            else:
                fallback = (
                    self._heat_target if self._last_active_mode == HVACMode.HEAT else self._cool_target
                )
                self._attr_target_temperature = self._clamp_temperature(fallback)
            self._attr_target_temperature_low = self._heat_target
            self._attr_target_temperature_high = self._cool_target
            self._running_mode = MODE_IDLE

        self._apply_target_limits()

    def _adopt_target_from_device(self, entity_id: str, state: State) -> None:
        """기기에서 목표 온도 가져오기"""
        hvac_mode = _hvac_mode_from_state(state)
        if hvac_mode == HVACMode.OFF:
            return

        temperature = _as_float(state.attributes.get("temperature"))
        if temperature is None:
            return

        value = self._clamp_temperature(temperature)
        previous = self._device_temperatures.get(entity_id)
        pending = self._pending_targets.get(entity_id)

        if pending is not None:
            if math.isclose(value, pending, abs_tol=0.15):
                value = pending
                self._pending_targets.pop(entity_id, None)
            elif previous is not None and math.isclose(value, previous, abs_tol=0.05):
                return
            else:
                self._pending_targets.pop(entity_id, None)

        self._device_temperatures[entity_id] = value

        if self._heating_entity and entity_id == self._heating_entity:
            self._heat_target = value
            self._attr_target_temperature_low = value
            if self._attr_hvac_mode == HVACMode.HEAT:
                self._attr_target_temperature = value
        elif self._cooling_entity and entity_id == self._cooling_entity:
            self._cool_target = value
            self._attr_target_temperature_high = value
            if self._attr_hvac_mode == HVACMode.COOL:
                self._attr_target_temperature = value

        self._apply_target_limits()

    async def _adopt_device_state(self, initial: bool = False) -> None:
        """기기 상태 채택"""
        heating_state = self._hass.states.get(self._heating_entity) if self._heating_entity else None
        cooling_state = self._hass.states.get(self._cooling_entity) if self._cooling_entity else None

        heating_mode = _hvac_mode_from_state(heating_state) if heating_state else None
        cooling_mode = _hvac_mode_from_state(cooling_state) if cooling_state else None

        heating_on = heating_mode == HVACMode.HEAT if heating_mode else False
        cooling_on = cooling_mode == HVACMode.COOL if cooling_mode else False

        self._update_temperature_limits(heating_state, cooling_state)

        if self._attr_hvac_mode == HVACMode.OFF:
            adopt_allowed = True
            if not initial:
                now = dt_util.utcnow()
                for entity_id in [e for e in [self._heating_entity, self._cooling_entity] if e]:
                    last = self._last_hvac_command.get(entity_id)
                    if last and last[0] == HVACMode.OFF and now - last[1] < self._command_cooldown:
                        adopt_allowed = False
                        break

            if (heating_on or cooling_on) and adopt_allowed:
                if heating_on and not cooling_on:
                    self._attr_hvac_mode = HVACMode.HEAT
                    self._running_mode = MODE_HEATING
                    self._last_active_mode = HVACMode.HEAT
                    _LOGGER.debug("난방기가 활성화되어 수동 HEAT 모드 채택")
                elif cooling_on and not heating_on:
                    self._attr_hvac_mode = HVACMode.COOL
                    self._running_mode = MODE_COOLING
                    self._last_active_mode = HVACMode.COOL
                    _LOGGER.debug("냉방기가 활성화되어 수동 COOL 모드 채택")
                elif heating_on and cooling_on:
                    chosen_mode = (
                        self._last_active_mode
                        if self._last_active_mode in (HVACMode.HEAT, HVACMode.COOL)
                        else HVACMode.COOL
                    )
                    self._attr_hvac_mode = chosen_mode
                    self._running_mode = (
                        MODE_HEATING if chosen_mode == HVACMode.HEAT else MODE_COOLING
                    )
                    self._last_active_mode = chosen_mode
                    _LOGGER.debug("두 기기가 모두 활성화되어 수동 %s 모드 채택", chosen_mode)
            else:
                if heating_on or cooling_on:
                    active_devices = []
                    if self._heating_entity and heating_on:
                        active_devices.append(self._heating_entity)
                    if self._cooling_entity and cooling_on:
                        active_devices.append(self._cooling_entity)

                    if active_devices:
                        _LOGGER.debug(
                            "HVAC 꺼진 상태에서 %s 기기가 여전히 활성화됨; 대기 중인 명령 대기 중",
                            " & ".join(active_devices),
                        )
                self._running_mode = MODE_IDLE
        elif self._attr_hvac_mode == HVACMode.HEAT:
            if cooling_on and not heating_on:
                self._attr_hvac_mode = HVACMode.COOL
                self._running_mode = MODE_COOLING
                self._last_active_mode = HVACMode.COOL
            elif not heating_on and not cooling_on:
                self._attr_hvac_mode = HVACMode.OFF
                self._running_mode = MODE_IDLE
            else:
                self._running_mode = MODE_HEATING
                self._last_active_mode = HVACMode.HEAT
        elif self._attr_hvac_mode == HVACMode.COOL:
            if heating_on and not cooling_on:
                self._attr_hvac_mode = HVACMode.HEAT
                self._running_mode = MODE_HEATING
                self._last_active_mode = HVACMode.HEAT
            elif not heating_on and not cooling_on:
                self._attr_hvac_mode = HVACMode.OFF
                self._running_mode = MODE_IDLE
            else:
                self._running_mode = MODE_COOLING
                self._last_active_mode = HVACMode.COOL
        else:
            self._attr_hvac_mode = HVACMode.OFF
            self._running_mode = MODE_IDLE

        # 시작 시 기기에서 온도 채택
        if heating_state and heating_mode != HVACMode.OFF:
            heating_temp = _as_float(heating_state.attributes.get("temperature"))
            if heating_temp is not None and not self._should_defer_device_temperature(
                self._heating_entity, heating_temp
            ):
                self._heat_target = heating_temp
                self._attr_target_temperature_low = heating_temp
                if self._attr_hvac_mode == HVACMode.HEAT:
                    self._attr_target_temperature = heating_temp
                self._device_temperatures[self._heating_entity] = self._heat_target
                self._last_temp_command.pop(self._heating_entity, None)

        if cooling_state and cooling_mode != HVACMode.OFF:
            cooling_temp = _as_float(cooling_state.attributes.get("temperature"))
            if cooling_temp is not None and not self._should_defer_device_temperature(
                self._cooling_entity, cooling_temp
            ):
                self._cool_target = cooling_temp
                self._attr_target_temperature_high = cooling_temp
                if self._attr_hvac_mode == HVACMode.COOL:
                    self._attr_target_temperature = cooling_temp
                self._device_temperatures[self._cooling_entity] = self._cool_target
                self._last_temp_command.pop(self._cooling_entity, None)

        self._apply_target_limits()
        self._update_hvac_action()

    def _decide_running_mode(self) -> str:
        """실행 모드 결정"""
        if self._attr_hvac_mode == HVACMode.OFF:
            return MODE_IDLE
        if self._attr_hvac_mode == HVACMode.HEAT:
            return MODE_HEATING
        if self._attr_hvac_mode == HVACMode.COOL:
            return MODE_COOLING

        return MODE_COOLING if self._last_active_mode == HVACMode.COOL else MODE_HEATING

    def _devices_match_mode(self, mode: str) -> bool:
        """기기가 모드와 일치하는지 확인"""
        heating_state = self._hass.states.get(self._heating_entity) if self._heating_entity else None
        cooling_state = self._hass.states.get(self._cooling_entity) if self._cooling_entity else None

        heating_mode = _hvac_mode_from_state(heating_state) if heating_state else None
        cooling_mode = _hvac_mode_from_state(cooling_state) if cooling_state else None

        if mode == MODE_HEATING:
            heating_ok = (not self._heating_entity) or (heating_mode == HVACMode.HEAT)
            cooling_off = (not self._cooling_entity) or (cooling_mode != HVACMode.COOL)
            return heating_ok and cooling_off
        if mode == MODE_COOLING:
            cooling_ok = (not self._cooling_entity) or (cooling_mode == HVACMode.COOL)
            heating_off = (not self._heating_entity) or (heating_mode != HVACMode.HEAT)
            return cooling_ok and heating_off
        # MODE_IDLE
        heating_off = (not self._heating_entity) or (heating_mode != HVACMode.HEAT)
        cooling_off = (not self._cooling_entity) or (cooling_mode != HVACMode.COOL)
        return heating_off and cooling_off

    async def _ensure_consistency(self, reason: str, force_apply: bool = False) -> None:
        """일관성 보장"""
        desired_mode = self._decide_running_mode()
        if desired_mode == MODE_IDLE:
            self._running_mode = MODE_IDLE
            await self._turn_off_all(reason)
            self._apply_target_limits()
            self._update_hvac_action()
            return

        if force_apply or desired_mode != self._running_mode or not self._devices_match_mode(desired_mode):
            _LOGGER.debug("%s → %s 모드로 전환", reason, desired_mode)
            if desired_mode == MODE_HEATING:
                await self._activate_heating()
            else:
                await self._activate_cooling()
            self._running_mode = desired_mode
        else:
            await self._sync_active_device_temperature()

        self._apply_target_limits()
        self._update_hvac_action()

    async def _activate_heating(self) -> None:
        """난방 활성화"""
        if not self._heating_entity:
            _LOGGER.warning("난방 활성화 불가: 난방기가 설정되지 않음")
            return

        target = self._clamp_temperature(self._heat_target)
        self._heat_target = target
        self._attr_target_temperature_low = target
        self._attr_target_temperature = target
        self._last_active_mode = HVACMode.HEAT
        _LOGGER.info("난방 활성화 (목표=%s)", target)
        await self._apply_device_states(
            heating_hvac=HVACMode.HEAT,
            cooling_hvac=HVACMode.OFF,
            heating_temp=target,
            cooling_temp=None,
        )

    async def _activate_cooling(self) -> None:
        """냉방 활성화"""
        if not self._cooling_entity:
            _LOGGER.warning("냉방 활성화 불가: 냉방기가 설정되지 않음")
            return

        target = self._clamp_temperature(self._cool_target)
        self._cool_target = target
        self._attr_target_temperature_high = target
        self._attr_target_temperature = target
        self._last_active_mode = HVACMode.COOL
        _LOGGER.info("냉방 활성화 (목표=%s)", target)
        await self._apply_device_states(
            heating_hvac=HVACMode.OFF,
            cooling_hvac=HVACMode.COOL,
            heating_temp=None,
            cooling_temp=target,
        )

    async def _turn_off_all(self, reason: str) -> None:
        """모든 기기 끄기"""
        _LOGGER.info("모든 기기 끄기 (%s)", reason)
        await self._apply_device_states(
            heating_hvac=HVACMode.OFF,
            cooling_hvac=HVACMode.OFF,
            heating_temp=None,
            cooling_temp=None,
        )

    async def _sync_active_device_temperature(self) -> None:
        """활성 기기 온도 동기화"""
        if self._running_mode == MODE_HEATING and self._heating_entity:
            target = self._clamp_temperature(self._heat_target)
            self._attr_target_temperature_low = target
            self._heat_target = target
            self._attr_target_temperature = target
            await self._ensure_temperature(self._heating_entity, target)
        elif self._running_mode == MODE_COOLING and self._cooling_entity:
            target = self._clamp_temperature(self._cool_target)
            self._attr_target_temperature_high = target
            self._cool_target = target
            self._attr_target_temperature = target
            await self._ensure_temperature(self._cooling_entity, target)

    async def _apply_device_states(
        self,
        *,
        heating_hvac: HVACMode,
        cooling_hvac: HVACMode,
        heating_temp: Optional[float],
        cooling_temp: Optional[float],
    ) -> None:
        """기기 상태 적용"""
        self._controlling_devices = True
        try:
            if self._heating_entity:
                if heating_hvac == HVACMode.OFF:
                    await self._try_turn_off(self._heating_entity)
                heating_ready = await self._ensure_hvac_mode(self._heating_entity, heating_hvac)

                if heating_temp is not None:
                    await self._ensure_temperature(
                        self._heating_entity,
                        heating_temp,
                        expect_power_on=heating_hvac != HVACMode.OFF and heating_ready,
                    )

            if self._cooling_entity:
                if cooling_hvac == HVACMode.OFF:
                    await self._try_turn_off(self._cooling_entity)
                cooling_ready = await self._ensure_hvac_mode(self._cooling_entity, cooling_hvac)

                if cooling_temp is not None:
                    await self._ensure_temperature(
                        self._cooling_entity,
                        cooling_temp,
                        expect_power_on=cooling_hvac != HVACMode.OFF and cooling_ready,
                    )
        finally:
            self._controlling_devices = False

    async def _ensure_hvac_mode(self, entity_id: str, hvac_mode: HVACMode) -> bool:
        """HVAC 모드 보장"""
        state = self._hass.states.get(entity_id)
        if state is None or state.state in SENSOR_UNAVAILABLE:
            _LOGGER.debug(
                "%s 엔티티를 사용할 수 없어 hvac_mode를 %s로 설정할 수 없음; 재시도 예약됨",
                entity_id,
                hvac_mode,
            )
            self._pending_modes[entity_id] = hvac_mode
            self._schedule_hvac_retry(entity_id, hvac_mode)
            return False

        if state is not None and state.state == hvac_mode:
            self._pending_modes.pop(entity_id, None)
            self._cancel_hvac_retry(entity_id)
            self._last_hvac_command.pop(entity_id, None)
            return True

        now = dt_util.utcnow()
        if (
            last := self._last_hvac_command.get(entity_id)
        ) and last[0] == hvac_mode and now - last[1] < self._command_cooldown:
            _LOGGER.debug(
                "%s hvac_mode 명령 건너뛰기 (쿨다운 %s초)",
                entity_id,
                int(self._command_cooldown.total_seconds()),
            )
            return False

        try:
            await self._hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": hvac_mode},
                blocking=True,
            )
        except HomeAssistantError as err:
            if hvac_mode == HVACMode.OFF and self._is_power_off_error(err):
                self._pending_modes.pop(entity_id, None)
                self._cancel_hvac_retry(entity_id)
                self._last_hvac_command.pop(entity_id, None)
                _LOGGER.debug("%s 이미 꺼진 상태", entity_id)
                return True
            if self._is_power_off_error(err) and hvac_mode != HVACMode.OFF:
                _LOGGER.debug(
                    "%s를 %s로 전환하기 전에 전원 켜기", entity_id, hvac_mode
                )
                if await self._try_turn_on(entity_id):
                    self._pending_modes[entity_id] = hvac_mode
                    self._schedule_hvac_retry(entity_id, hvac_mode)
                    self._last_hvac_command[entity_id] = (hvac_mode, now)
                else:
                    _LOGGER.warning(
                        "%s 전원 켜기 불가; hvac_mode %s 명령 건너뛰기",
                        entity_id,
                        hvac_mode,
                    )
                    self._pending_modes.pop(entity_id, None)
                    self._cancel_hvac_retry(entity_id)
                return False
            if self._is_temporary_command_error(err):
                _LOGGER.warning(
                    "%s hvac_mode를 %s로 설정 실패 (%s); 쿨다운 후 재시도",
                    entity_id,
                    hvac_mode,
                    err,
                )
                self._pending_modes[entity_id] = hvac_mode
                self._schedule_hvac_retry(entity_id, hvac_mode)
                self._last_hvac_command[entity_id] = (hvac_mode, now)
                return False
            self._pending_modes.pop(entity_id, None)
            self._cancel_hvac_retry(entity_id)
            raise

        self._last_hvac_command[entity_id] = (hvac_mode, now)
        self._pending_modes.pop(entity_id, None)
        self._cancel_hvac_retry(entity_id)
        return True

    async def _ensure_temperature(
        self,
        entity_id: str,
        temperature: float,
        *,
        expect_power_on: bool = True,
    ) -> None:
        """온도 보장"""
        state = self._hass.states.get(entity_id)
        if state is None or state.state in SENSOR_UNAVAILABLE:
            _LOGGER.debug(
                "%s 엔티티를 사용할 수 없어 온도를 %.1f로 설정할 수 없음; 재시도 예약됨",
                entity_id,
                temperature,
            )
            self._pending_targets[entity_id] = temperature
            self._schedule_temperature_retry(entity_id)
            return

        hvac_state = _hvac_mode_from_state(state)
        if expect_power_on and hvac_state == HVACMode.OFF:
            _LOGGER.debug("온도 설정 전에 %s 전원 켜기", entity_id)
            self._pending_targets[entity_id] = temperature
            await self._try_turn_on(entity_id)
            self._schedule_temperature_retry(entity_id)
            return

        current = _as_float(state.attributes.get("temperature")) if state else None
        if current is not None and math.isclose(current, temperature, abs_tol=0.05):
            self._pending_targets.pop(entity_id, None)
            self._device_temperatures[entity_id] = current
            self._last_temp_command.pop(entity_id, None)
            self._cancel_temperature_retry(entity_id)
            return

        now = dt_util.utcnow()
        if last := self._last_temp_command.get(entity_id):
            within_cooldown = now - last[1] < self._command_cooldown
            same_target = math.isclose(last[0], temperature, abs_tol=0.05)
            needs_retry = current is None or abs(current - temperature) > 0.5
            if same_target and within_cooldown and not needs_retry:
                _LOGGER.debug(
                    "%s 온도 명령 건너뛰기 (쿨다운 %s초)",
                    entity_id,
                    int(self._command_cooldown.total_seconds()),
                )
                self._pending_targets.setdefault(entity_id, temperature)
                return

        self._pending_targets[entity_id] = temperature
        try:
            await self._hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": entity_id, "temperature": temperature},
                blocking=True,
            )
        except HomeAssistantError as err:
            if self._is_power_off_error(err) and expect_power_on:
                _LOGGER.debug("전원 켜기 후 %s 온도 명령 재시도", entity_id)
                await self._try_turn_on(entity_id)
                self._last_temp_command[entity_id] = (temperature, now)
                self._schedule_temperature_retry(entity_id)
                return
            if self._is_temporary_command_error(err):
                _LOGGER.warning(
                    "%s 온도를 %.1f로 설정 실패 (%s); 쿨다운 후 재시도",
                    entity_id,
                    temperature,
                    err,
                )
                self._last_temp_command[entity_id] = (temperature, now)
                self._schedule_temperature_retry(entity_id)
                return
            self._pending_targets.pop(entity_id, None)
            self._cancel_temperature_retry(entity_id)
            raise

        self._last_temp_command[entity_id] = (temperature, now)
        self._cancel_temperature_retry(entity_id)

    def _update_hvac_action(self) -> None:
        """HVAC 동작 업데이트"""
        if self._attr_hvac_mode == HVACMode.OFF or self._running_mode == MODE_IDLE:
            self._attr_hvac_action = HVACAction.OFF
            return

        # 실제 기기 상태를 확인하여 동작 결정
        if self._running_mode == MODE_HEATING and self._heating_entity:
            heating_state = self._hass.states.get(self._heating_entity)
            if heating_state and heating_state.state == HVACMode.HEAT:
                # 난방기가 켜져있고 현재 온도와 목표 온도 비교
                if self._attr_current_temperature is not None:
                    if self._attr_current_temperature < self._heat_target - 0.1:
                        self._attr_hvac_action = HVACAction.HEATING
                    else:
                        self._attr_hvac_action = HVACAction.IDLE
                else:
                    self._attr_hvac_action = HVACAction.HEATING
            else:
                self._attr_hvac_action = HVACAction.IDLE
        elif self._running_mode == MODE_COOLING and self._cooling_entity:
            cooling_state = self._hass.states.get(self._cooling_entity)
            if cooling_state and cooling_state.state == HVACMode.COOL:
                # 냉방기가 켜져있고 현재 온도와 목표 온도 비교
                if self._attr_current_temperature is not None:
                    if self._attr_current_temperature > self._cool_target + 0.1:
                        self._attr_hvac_action = HVACAction.COOLING
                    else:
                        self._attr_hvac_action = HVACAction.IDLE
                else:
                    self._attr_hvac_action = HVACAction.COOLING
            else:
                self._attr_hvac_action = HVACAction.IDLE
        else:
            self._attr_hvac_action = HVACAction.IDLE

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """온도 설정"""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        target_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        target_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)

        if self._attr_hvac_mode == HVACMode.HEAT:
            if temperature is not None:
                self._heat_target = self._clamp_temperature(float(temperature))
            elif target_low is not None:
                self._heat_target = self._clamp_temperature(float(target_low))
            if target_high is not None:
                self._cool_target = self._clamp_temperature(float(target_high))
            if self._cool_target < self._heat_target:
                self._cool_target = self._heat_target
            self._attr_target_temperature_low = self._heat_target
            self._attr_target_temperature_high = self._cool_target
            self._attr_target_temperature = self._heat_target
            self._last_active_mode = HVACMode.HEAT
        elif self._attr_hvac_mode == HVACMode.COOL:
            if temperature is not None:
                self._cool_target = self._clamp_temperature(float(temperature))
            elif target_high is not None:
                self._cool_target = self._clamp_temperature(float(target_high))
            if target_low is not None:
                self._heat_target = self._clamp_temperature(float(target_low))
            if self._heat_target > self._cool_target:
                self._heat_target = self._cool_target
            self._attr_target_temperature_high = self._cool_target
            self._attr_target_temperature_low = self._heat_target
            self._attr_target_temperature = self._cool_target
            self._last_active_mode = HVACMode.COOL
        else:
            new_heat = self._heat_target
            new_cool = self._cool_target

            if target_low is not None:
                new_heat = self._clamp_temperature(float(target_low))
            if target_high is not None:
                new_cool = self._clamp_temperature(float(target_high))

            if temperature is not None and target_low is None and target_high is None:
                mid = self._clamp_temperature(float(temperature))
                new_heat = mid
                new_cool = mid

            if new_heat > new_cool:
                new_heat, new_cool = new_cool, new_heat

            self._heat_target = new_heat
            self._cool_target = new_cool
            self._attr_target_temperature_low = new_heat
            self._attr_target_temperature_high = new_cool
            self._attr_target_temperature = (
                self._cool_target if self._last_active_mode == HVACMode.COOL else self._heat_target
            )

        self._apply_target_limits()
        await self._ensure_consistency("set_temperature", force_apply=True)
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """HVAC 모드 설정"""
        if hvac_mode not in (HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL):
            _LOGGER.debug("지원하지 않는 hvac_mode %s; OFF로 기본 설정", hvac_mode)
            hvac_mode = HVACMode.OFF

        if hvac_mode == self._attr_hvac_mode:
            await self._ensure_consistency("hvac_mode_reassert", force_apply=True)
            self.async_write_ha_state()
            return

        previous_target = self._attr_target_temperature
        previous_running_mode = self._running_mode
        self._attr_hvac_mode = hvac_mode

        if hvac_mode == HVACMode.OFF:
            self._running_mode = MODE_IDLE
            if previous_running_mode == MODE_COOLING:
                self._attr_target_temperature = self._cool_target
            elif previous_running_mode == MODE_HEATING:
                self._attr_target_temperature = self._heat_target
            else:
                fallback = previous_target if previous_target is not None else (
                    self._cool_target if self._last_active_mode == HVACMode.COOL else self._heat_target
                )
                self._attr_target_temperature = self._clamp_temperature(fallback)
        elif hvac_mode == HVACMode.HEAT:
            self._running_mode = MODE_HEATING
            self._attr_target_temperature = self._heat_target
            self._last_active_mode = HVACMode.HEAT
        else:
            self._running_mode = MODE_COOLING
            self._attr_target_temperature = self._cool_target
            self._last_active_mode = HVACMode.COOL

        self._attr_target_temperature_low = self._heat_target
        self._attr_target_temperature_high = self._cool_target

        self._apply_target_limits()
        await self._ensure_consistency("hvac_mode_change", force_apply=True)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """켜기"""
        preferred_mode = self._last_active_mode
        if preferred_mode not in (HVACMode.HEAT, HVACMode.COOL):
            if self._heating_entity:
                preferred_mode = HVACMode.HEAT
            elif self._cooling_entity:
                preferred_mode = HVACMode.COOL
            else:
                preferred_mode = HVACMode.HEAT
        await self.async_set_hvac_mode(preferred_mode)

    async def async_turn_off(self) -> None:
        """끄기"""
        await self.async_set_hvac_mode(HVACMode.OFF)

    @property
    def min_temp(self) -> float:
        """최소 온도"""
        return self._min_temp

    @property
    def max_temp(self) -> float:
        """최대 온도"""
        return self._max_temp

    @property
    def device_info(self) -> dict[str, Any]:
        """기기 정보"""
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": self._attr_name,
            "manufacturer": "Climate Wrapper",
            "model": "Unified Thermostat",
            "sw_version": "1.0.0",
        }
