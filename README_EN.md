# Climate Wrapper

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

A Home Assistant custom component that integrates heating and cooling devices into one smart thermostat.

English | [한국어](README.md)

## Features

- 🔥 **Unified Control**: Manage boiler, air conditioner, and more in one thermostat
- 🎯 **Flexible Configuration**: Configure heating only, cooling only, or both
- 🌡️ **External Sensor Support**: Use separate temperature/humidity sensors (optional)
- 🔄 **Auto State Sync**: Automatically synchronize with device states
- 🕐 **Command Cooldown**: Prevent unnecessary command repetition
- 🎮 **Manual Control Detection**: Auto mode switching when devices are manually controlled
- 🔁 **Retry Logic**: Automatic retry on temporary errors

## Installation

### Via HACS (Recommended)

1. HACS > Integrations > Top right menu > Custom repositories
2. Repository: `https://github.com/yoonpooh/climate-wrapper`
3. Category: `Integration`
4. Search for "Climate Wrapper" and install
5. Restart Home Assistant

### Manual Installation

1. Download this repository
2. Copy `custom_components/climate_wrapper` folder to your Home Assistant's `custom_components` directory
3. Restart Home Assistant

## Configuration

### UI Configuration

1. Home Assistant > Settings > Devices & Services
2. Click "Add Integration"
3. Search for "Climate Wrapper"
4. Follow the setup wizard

### Configuration Options

| Option | Required | Description | Default |
|--------|----------|-------------|---------|
| Name | Yes | Integration name | Climate Wrapper |
| Heating Entity | No | Heating device (climate domain) | - |
| Cooling Entity | No | Cooling device (climate domain) | - |
| Temperature Sensor | No | External temperature sensor | - |
| Humidity Sensor | No | External humidity sensor | - |
| Command Cooldown | Yes | Command repeat prevention time (seconds) | 120 |
| Update Interval | Yes | State update interval (seconds) | 30 |

**Note**: At least one of heating or cooling entity is required.

## Usage Examples

### Example 1: Boiler + Air Conditioner

- **Heating Entity**: Smart boiler thermostat
- **Cooling Entity**: Smart air conditioner
- **Temperature Sensor**: Living room temperature sensor

→ Automatically control boiler or AC based on living room temperature

### Example 2: Air Conditioner Only

- **Cooling Entity**: Smart air conditioner
- **Temperature Sensor**: None (use AC's built-in sensor)

→ Use as cooling-only thermostat

### Example 3: Electric Heater Only

- **Heating Entity**: Smart electric heater
- **Temperature Sensor**: Room temperature sensor

→ Use as heating-only thermostat

## How It Works

### HVAC Modes

- **OFF**: All devices off
- **HEAT**: Heating mode (heating ON, cooling OFF)
- **COOL**: Cooling mode (cooling ON, heating OFF)

### Temperature Sensor

- If external temperature sensor is configured: Use that sensor's temperature
- If no external sensor: Use device's `current_temperature` attribute
- If both heating and cooling devices exist: Use average of both temperatures

### Command Cooldown

Prevents sending the same command repeatedly within cooldown period:
- HVAC mode changes
- Temperature setting changes

Automatically retries on temporary errors.

### Manual Control Detection

When devices are manually turned on while integration is OFF:
- Automatically switches to corresponding mode (HEAT or COOL)
- Adopts device's target temperature automatically

## Troubleshooting

### Device won't turn on

1. Check if device supports `climate.turn_on` service
2. Check logs for error messages
3. Wait for cooldown period and try again

### Temperature not syncing

1. Check if device supports `set_temperature` service
2. Try reducing cooldown time (minimum 30 seconds)
3. Verify device is online

### Mode switching is slow

- This is normal due to command cooldown
- You can reduce cooldown time, but it may stress the device

## Contributing

Issues and pull requests are always welcome!

## License

MIT License

## Credits

This project is improved based on [homeassistant-auto-climate](https://github.com/yoonpooh/homeassistant-auto-climate).

---

[releases-shield]: https://img.shields.io/github/release/yoonpooh/climate-wrapper.svg?style=for-the-badge
[releases]: https://github.com/yoonpooh/climate-wrapper/releases
[license-shield]: https://img.shields.io/github/license/yoonpooh/climate-wrapper.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
