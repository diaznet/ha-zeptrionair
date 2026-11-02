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

DEFAULT_TRAVEL_TIME: Final = 30.0  # seconds
DEFAULT_DIM_TIME: Final = 5000  # milliseconds for a full 0-100 % dim

# Safety polls: rare with a push channel, frequent without one.
PUSH_POLL_INTERVAL: Final = timedelta(minutes=5)
FALLBACK_POLL_INTERVAL: Final = timedelta(seconds=30)

# Entities stay available for this long after the event stream drops.
UNAVAILABLE_GRACE: Final = 60.0

# A direction learned from a command or key press is valid for this long.
DIRECTION_VALID_FOR: Final = 3.0

EVENT_PRESS: Final = "press"
EVENT_RELEASE: Final = "release"
