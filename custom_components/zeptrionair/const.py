"""Constants for the Feller zeptrionAir integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "zeptrionair"
MANUFACTURER: Final = "Feller"

# Options (stored per channel in entry.options["channels"]["<n>"])
CONF_CHANNELS: Final = "channels"
CONF_POSITION_TRACKING: Final = "position_tracking"
CONF_TRAVEL_TIME_UP: Final = "travel_time_up"
CONF_TRAVEL_TIME_DOWN: Final = "travel_time_down"
CONF_DIM_TIME: Final = "dim_time"
CONF_STEP_DURATION: Final = "step_duration"

DEFAULT_TRAVEL_TIME: Final = 30.0  # seconds
# Milliseconds for a full 0-100 % dim. Reported for real dimmers, not verified on our hardware.
DEFAULT_DIM_TIME: Final = 3400
DEFAULT_STEP_DURATION: Final = 250  # milliseconds of one cover step

# Actions (services)
SERVICE_STORE_SCENE: Final = "store_scene"
SERVICE_RECALL_SCENE: Final = "recall_scene"
SERVICE_MOVE_STEP: Final = "move_step"
SERVICE_WRITE_NAME: Final = "write_name"
ATTR_SCENE: Final = "scene"
ATTR_DIRECTION: Final = "direction"
ATTR_DURATION: Final = "duration"
ATTR_NAME: Final = "name"
ATTR_GROUP: Final = "group"

# Safety polls: rare with a push channel, frequent without one.
PUSH_POLL_INTERVAL: Final = timedelta(minutes=5)
FALLBACK_POLL_INTERVAL: Final = timedelta(seconds=30)

# Entities stay available for this long after the event stream drops.
UNAVAILABLE_GRACE: Final = 60.0

# A direction learned from a command or key press is valid for this long.
DIRECTION_VALID_FOR: Final = 3.0

EVENT_PRESS: Final = "press"
EVENT_RELEASE: Final = "release"
