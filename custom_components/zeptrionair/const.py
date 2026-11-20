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
CONF_LEARN_TRAVEL_TIMES: Final = "learn_travel_times"
CONF_TILT_TIME: Final = "tilt_time"
# Set when a travel time was measured (learned or calibrated) rather than typed in.
CONF_LEARNED_UP: Final = "learned_up"
CONF_LEARNED_DOWN: Final = "learned_down"

DEFAULT_TRAVEL_TIME: Final = 30.0  # seconds
# Milliseconds for a full 0-100 % dim. Reported for real dimmers, not verified on our hardware.
DEFAULT_DIM_TIME: Final = 3400
DEFAULT_STEP_DURATION: Final = 250  # milliseconds of one cover step

# Actions (services)
SERVICE_STORE_SCENE: Final = "store_scene"
SERVICE_RECALL_SCENE: Final = "recall_scene"
SERVICE_MOVE_STEP: Final = "move_step"
SERVICE_WRITE_NAME: Final = "write_name"
SERVICE_CALIBRATE: Final = "calibrate"
SERVICE_PROGRAM_SMARTBUTTON: Final = "program_smartbutton"
ATTR_DEVICE_ID: Final = "device_id"
ATTR_COMMANDS: Final = "commands"
ATTR_REQUESTS: Final = "requests"
ATTR_WAIT: Final = "wait"
ATTR_COMMAND: Final = "command"

# A cover stop within this many seconds after a wall key was released was done by hand
# (keys that move a cover only while held).
HOLD_RELEASE_WINDOW: Final = 1.0
# Travel times outside this range are not learned (seconds).
LEARN_MIN: Final = 1.0
LEARN_MAX: Final = 300.0
# How much longer than the distance needs a run to an end stop may take (motor overrun, s).
END_TOLERANCE: Final = 2.5
LED_HISTORY: Final = 20
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
