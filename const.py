DOMAIN = "adaptive-lighting"
PLATFORMS = ["switch"]

# Defaults
DEFAULT_ONLY_WHEN_ON = True
DEFAULT_MANUAL_HOLD_S = 900     # 15 minutes
DEFAULT_NIGHT_START = "22:00"
DEFAULT_NIGHT_END = "06:30"
DEFAULT_SLEEP_K = 2200
DEFAULT_SLEEP_B = 20

# Options keys
CONF_NIGHT_START = "night_start"
CONF_NIGHT_END = "night_end"
CONF_INCLUDE_AREAS = "include_areas"
CONF_EXCLUDE_ENTITIES = "exclude_entities"
CONF_INCLUDE_ENTITIES = "include_entities"

ATTR_ELEVATION = "elevation"
