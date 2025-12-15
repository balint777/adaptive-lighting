from __future__ import annotations
from datetime import datetime, time, timedelta
from typing import Iterable, Tuple


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def parse_time_str(s: str) -> time:
    """Parse time string that may include seconds."""
    try:
        # Try with seconds first
        return datetime.strptime(s, "%H:%M:%S").time()
    except ValueError:
        # Fall back to format without seconds
        return datetime.strptime(s, "%H:%M").time()


def in_window(now_t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now_t < end
    return now_t >= start or now_t < end


def time_difference_minutes(time1: time, time2: time) -> float:
    """Calculate difference in minutes between two times, handling day boundary."""
    dt1 = datetime.combine(datetime.today(), time1)
    dt2 = datetime.combine(datetime.today(), time2)
    
    # If time2 is earlier than time1, it's the next day
    if dt2 < dt1:
        dt2 += timedelta(days=1)
    
    return (dt2 - dt1).total_seconds() / 60


def subtract_hours_from_time(t: time, hours: float) -> time:
    """Subtract hours from a time, handling day boundary."""
    dt = datetime.combine(datetime.today(), t)
    dt -= timedelta(hours=hours)
    return dt.time()


def add_hours_to_time(t: time, hours: float) -> time:
    """Add hours to a time, handling day boundary."""
    dt = datetime.combine(datetime.today(), t)
    dt += timedelta(hours=hours)
    return dt.time()


def is_in_transition_period(now_t: time, wind_down_target: time, wake_up: time) -> Tuple[bool, str, float]:
    """
    Check if current time is in transition period and return progress.
    
    Returns:
        (is_in_transition, wind_down, progress)
        - is_in_transition: True if in a transition period
        - wind_down: Boolean
        - progress: 0.0 to 1.0, where 0.0 is start of transition, 1.0 is end
    """
    # Calculate transition windows
    pre_night_start = subtract_hours_from_time(wind_down_target, 1.0)
    post_night_end = add_hours_to_time(wake_up, 0.5)
    
    # Check if in pre-night transition (1 hour before wind_down_target)
    if in_window(now_t, pre_night_start, wind_down_target):
        # Calculate progress from 0.0 (at pre_night_start) to 1.0 (at wind_down_target)
        total_minutes = time_difference_minutes(pre_night_start, wind_down_target)
        elapsed_minutes = time_difference_minutes(pre_night_start, now_t)
        progress = elapsed_minutes / total_minutes if total_minutes > 0 else 0.0
        return True, True, clamp(progress, 0.0, 1.0)
    
    # Check if in post-night transition (1 hour after wake_up)
    if in_window(now_t, wake_up, post_night_end):
        # Calculate progress from 0.0 (at wake_up) to 1.0 (at post_night_end)
        total_minutes = time_difference_minutes(wake_up, post_night_end)
        elapsed_minutes = time_difference_minutes(wake_up, now_t)
        progress = elapsed_minutes / total_minutes if total_minutes > 0 else 0.0
        return True, False, clamp(progress, 0.0, 1.0)

    return False, False, 0.0

# Simple CCT(K) -> RGB approximation (not physically perfect, but good enough)
# Source: widely-used approximation adapted for HA usage

def cct_to_rgb(kelvin: int) -> Tuple[int, int, int]:
    k = clamp(kelvin, 1000, 40000) / 100.0
    # Red
    if k <= 66:
        r = 255
    else:
        r = 329.698727446 * ((k - 60) ** -0.1332047592)
    # Green
    if k <= 66:
        g = 99.4708025861 * (k) - 161.1195681661
    else:
        g = 288.1221695283 * ((k - 60) ** -0.0755148492)
    # Blue
    if k >= 66:
        b = 255
    elif k <= 19:
        b = 0
    else:
        b = 138.5177312231 * (k - 10) - 305.0447927307
    return (
        int(clamp(r, 0, 255)),
        int(clamp(g, 0, 255)),
        int(clamp(b, 0, 255)),
    )
