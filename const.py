DOMAIN = "adaptive-lighting"
PLATFORMS = ["switch"]

# Defaults
DEFAULT_INTERVAL = 30           # seconds
DEFAULT_TRANSITION = 2          # seconds
DEFAULT_MIN_K = 2200
DEFAULT_MAX_K = 6500
DEFAULT_MIN_B = 10              # %
DEFAULT_MAX_B = 90              # %
DEFAULT_ONLY_WHEN_ON = True
DEFAULT_MANUAL_HOLD_S = 900     # 15 minutes
DEFAULT_NIGHT_START = "22:00"
DEFAULT_NIGHT_END = "06:30"
DEFAULT_SLEEP_K = 2200
DEFAULT_SLEEP_B = 20

# Options keys
CONF_INTERVAL = "interval"
CONF_TRANSITION = "transition"
CONF_MIN_K = "min_k"
CONF_MAX_K = "max_k"
CONF_MIN_B = "min_b"
CONF_MAX_B = "max_b"
CONF_ONLY_WHEN_ON = "only_when_on"
CONF_MANUAL_HOLD_S = "manual_hold_s"
CONF_NIGHT_START = "night_start"
CONF_NIGHT_END = "night_end"
CONF_SLEEP_K = "sleep_kelvin"
CONF_SLEEP_B = "sleep_brightness"
CONF_INCLUDE_AREAS = "include_areas"
CONF_EXCLUDE_ENTITIES = "exclude_entities"
CONF_INCLUDE_ENTITIES = "include_entities"
CONF_AUTO_DISCOVER = "auto_discover"

ATTR_ELEVATION = "elevation"
