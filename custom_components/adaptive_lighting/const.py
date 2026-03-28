from typing import Final

DOMAIN: Final = "adaptive_lighting"
PLATFORMS: Final[list[str]] = ["switch"]

# Defaults
DEFAULT_NIGHT_START: Final = "22:00"
DEFAULT_NIGHT_END: Final = "06:30"

# Options keys
CONF_NIGHT_START: Final = "wind_down_target"
CONF_NIGHT_END: Final = "wake_up"
CONF_EXCLUDE_ENTITIES: Final = "exclude_entities"
