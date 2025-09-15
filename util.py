from __future__ import annotations
from datetime import datetime, time
from typing import Iterable, Tuple


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def parse_time_str(s: str) -> time:
    return datetime.strptime(s, "%H:%M").time()


def in_window(now_t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now_t < end
    return now_t >= start or now_t < end

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
