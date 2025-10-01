"""Climate Wrapper 통합 구성요소의 상수 정의"""

DOMAIN = "climate_wrapper"
NAME = "Climate Wrapper"
VERSION = "1.0.0"

# 설정 키
CONF_UPDATE_INTERVAL = "update_interval"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_HEATING_ENTITY = "heating_entity"
CONF_COOLING_ENTITY = "cooling_entity"
CONF_COMMAND_COOLDOWN = "command_cooldown"

# 기본값
DEFAULT_UPDATE_INTERVAL = 30
DEFAULT_COMMAND_COOLDOWN = 120

# 제어 모드
MODE_IDLE = "idle"
MODE_HEATING = "heating"
MODE_COOLING = "cooling"

# 플랫폼 목록
PLATFORMS = ["climate"]
